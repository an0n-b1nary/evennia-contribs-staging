# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Serialized ingestion and one privacy projection for every inbox reader."""

import hashlib
import json
import logging
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F, Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from evennia.accounts.models import AccountDB

from evennia_links.notices import (
    ActorRef,
    Evaluation,
    NoticeContext,
    RouteResult,
    StoredEvent,
    SubjectRef,
    connected_contexts,
    evaluate,
    normalize_rendered,
    recipient_identity,
    source_registry,
    validate_event,
)

from .context import ownerships
from .models import (
    DeliveryReceipt,
    Notice,
    NoticeEvent,
    Recipient,
    SourcePreference,
    ViewerSuppression,
)

logger = logging.getLogger("evennia")


class RetryRouting(Exception):
    """The source must leave pending work unacknowledged."""


class ProjectionPage(list):
    """Bounded projected results plus a safe continuation token, even for hidden rows."""

    next_cursor = None


@dataclass(frozen=True)
class ProjectedNotice:
    """A currently authorized rendered envelope with safe constituent state."""

    notice: object
    events: tuple
    evaluations: tuple
    text: str
    actions: tuple
    label: str

    @property
    def unread(self):
        """Whether at least one eligible constituent remains unread."""
        return any(e.read_at is None for e in self.events)

    @property
    def outstanding(self):
        """Whether any eligible current source decision remains outstanding."""
        return any(e.outstanding for e in self.evaluations)

    @property
    def cleared(self):
        """Whether every eligible constituent was explicitly cleared."""
        return all(e.cleared_at is not None for e in self.events)


def _retry(operation):
    for attempt in range(3):
        try:
            return operation()
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 2:
                raise
            time.sleep(0.025 * (attempt + 1))


def _lock_account(account_id):
    # No-op UPDATE acquires SQLite's writer before any mutation-state read.
    AccountDB.objects.filter(pk=account_id).update(last_login=F("last_login"))
    return AccountDB.objects.select_for_update().get(pk=account_id)


def _recipient(kind, pk):
    fields = {f"{kind}_id": pk}
    # Attempt the write by ownership before even looking up an existing row.
    # A preliminary SELECT would make concurrent SQLite readers race to upgrade.
    if not Recipient.objects.filter(**fields).update(revision=F("revision")):
        try:
            with transaction.atomic():
                Recipient.objects.create(**fields)
        except IntegrityError:
            pass
        Recipient.objects.filter(**fields).update(revision=F("revision"))
    return Recipient.objects.select_for_update().get(**fields)


def _scope(context):
    query = Q(pk__in=[])
    for kind, pk in ownerships(context):
        query |= Q(**{f"{kind}_id": pk})
    return query


def _stored(row):
    kind, pk = row.notice.recipient.identity
    return StoredEvent(
        row.event_id,
        row.occurred_at,
        SubjectRef(**row.subject) if row.subject else None,
        tuple(ActorRef(**a) for a in row.actors),
        row.payload,
        row.replacement_key,
        row.action_kind,
        kind,
        pk,
    )


def _fingerprint(event):
    data = asdict(event)
    data["occurred_at"] = event.occurred_at.isoformat()
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def effective_mode(account, source, outstanding=False):
    """Return effective immediate/summary/off for routine or sought-seat activity."""
    choice = (
        SourcePreference.objects.filter(account=account, source=source)
        .values_list("mode", flat=True)
        .first()
    )
    if outstanding:
        return "immediate" if choice is None or choice == "immediate" else "summary"
    return choice or "summary"


def route(recipient, *, source, event, context=None, transfer_id=None):
    """Persist one routing decision atomically, before acknowledging source work."""
    validate_event(event)
    kind, pk = recipient_identity(recipient)
    fingerprint = _fingerprint(event)

    from evennia_links.characters import playable_accounts

    policy_accounts = (
        [recipient]
        if kind == "account"
        else list(
            AccountDB.objects.filter(
                pk__in=[
                    account_id
                    for account_id, chars in playable_accounts()
                    if pk in {c.pk for c in chars}
                ]
            ).order_by("pk")
        )
    )
    if not policy_accounts:
        return RouteResult("retry")

    def operation():
        with transaction.atomic():
            for account in sorted(policy_accounts, key=lambda a: a.pk):
                _lock_account(account.pk)
            owner = _recipient(kind, pk)
            existing = (
                owner.receipts.filter(source=source)
                .filter(
                    Q(event_id=event.event_id)
                    | (Q(transfer_id=transfer_id) if transfer_id else Q(pk__in=[]))
                )
                .first()
            )
            if existing:
                if existing.event_id != event.event_id or existing.fingerprint != fingerprint:
                    raise ValueError("Notice identity reused with different event data")
                if transfer_id and existing.transfer_id not in (None, transfer_id):
                    raise ValueError("Notice transfer identity mismatch")
                if transfer_id and existing.transfer_id is None:
                    existing.transfer_id = transfer_id
                    existing.save(update_fields=["transfer_id"])
                return RouteResult("duplicate", str(existing.pk))
            if not getattr(settings, "NOTICES_ENABLED", True):
                return RouteResult("unavailable")
            try:
                adapter = source_registry()[source]
            except (KeyError, ImportError, ValueError) as exc:
                raise RetryRouting from exc
            stored = StoredEvent(**event.__dict__, recipient_kind=kind, recipient_id=pk)
            viewer_outcomes = {}
            viewer_suppressed = {}
            for account in policy_accounts:
                current = (
                    context
                    if context and context.account.pk == account.pk
                    else NoticeContext(account, recipient if kind == "character" else None)
                )
                outcome = evaluate(adapter, [stored], current)[event.event_id]
                mode = effective_mode(account, source, bool(event.action_kind))
                if mode == "off" and not event.action_kind:
                    viewer_suppressed[account.pk] = "preference"
                elif outcome.status in {"hidden", "invalid"}:
                    viewer_suppressed[account.pk] = outcome.status
                elif outcome.status == "defer" and outcome.reason != "context":
                    raise RetryRouting
                viewer_outcomes[account.pk] = (outcome, current, mode)
            suppressed = len(viewer_suppressed) == len(policy_accounts)
            eligible = [
                value for aid, value in viewer_outcomes.items() if aid not in viewer_suppressed
            ]
            outcome, current, mode = (
                eligible[0] if eligible else next(iter(viewer_outcomes.values()))
            )
            row = None
            if not suppressed:
                sources = set(
                    owner.notices.filter(
                        retired_at__isnull=True,
                        events__inactive_at__isnull=True,
                        events__cleared_at__isnull=True,
                        events__read_at__isnull=True,
                        events__action_kind__isnull=True,
                    ).values_list("source", flat=True)
                )
                limit = getattr(settings, "NOTICES_ROUTINE_LIMIT", 500)
                if not event.action_kind and len(sources | {source}) > limit:
                    raise RetryRouting
                prior_events = (
                    list(
                        NoticeEvent.objects.filter(
                            notice__recipient=owner,
                            notice__source=source,
                            replacement_key=event.replacement_key,
                            inactive_at__isnull=True,
                            notice__retired_at__isnull=True,
                        ).select_related("notice__recipient")
                    )
                    if event.replacement_key
                    else []
                )
                old_actions = [e for e in prior_events if e.action_kind]
                for _, old_context, _ in viewer_outcomes.values():
                    if old_actions:
                        outcomes = evaluate(adapter, [_stored(e) for e in old_actions], old_context)
                        if any(o.outstanding or o.status == "defer" for o in outcomes.values()):
                            raise RetryRouting
                if prior_events:
                    now = timezone.now()
                    NoticeEvent.objects.filter(pk__in=[e.pk for e in prior_events]).update(
                        inactive_at=now, inactive_reason="replaced"
                    )
                    for parent_id in {e.notice_id for e in prior_events}:
                        if not NoticeEvent.objects.filter(
                            notice_id=parent_id, inactive_at__isnull=True
                        ).exists():
                            Notice.objects.filter(pk=parent_id).update(retired_at=now)
                for collision_attempt in range(3):
                    try:
                        with transaction.atomic():
                            envelope = Notice.objects.create(
                                recipient=owner,
                                source=source,
                                replacement_key=event.replacement_key,
                            )
                        break
                    except IntegrityError:
                        if collision_attempt == 2:
                            raise
                row = NoticeEvent.objects.create(
                    notice=envelope,
                    event_id=event.event_id,
                    occurred_at=event.occurred_at,
                    replacement_key=event.replacement_key,
                    subject=asdict(event.subject) if event.subject else None,
                    actors=[asdict(a) for a in event.actors],
                    payload=event.payload,
                    action_kind=event.action_kind,
                )
                if any(
                    o.status == "visible" and mode == "immediate"
                    for aid, (o, _, mode) in viewer_outcomes.items()
                    if aid not in viewer_suppressed
                ):
                    row.hint_attempted_at = timezone.now()
                    row.save(update_fields=["hint_attempted_at"])
                    transaction.on_commit(lambda: _immediate(recipient, source, event.event_id))
                _compact_locked(owner)
                Recipient.objects.filter(pk=owner.pk).update(revision=F("revision") + 1)
            receipt = DeliveryReceipt.objects.create(
                recipient=owner,
                source=source,
                event_id=event.event_id,
                transfer_id=transfer_id,
                fingerprint=fingerprint,
                disposition="suppressed" if suppressed else "retained",
                stored_event=row,
            )
            if row is not None:
                ViewerSuppression.objects.bulk_create(
                    [
                        ViewerSuppression(receipt=receipt, account_id=aid, reason=reason)
                        for aid, reason in viewer_suppressed.items()
                    ]
                )
            return RouteResult(receipt.disposition, str(receipt.pk))

    try:
        return _retry(operation)
    except (RetryRouting, OperationalError):
        return RouteResult("retry")


def _evaluate_rows(rows, context):
    """Evaluate bounded batches with independent owner/source event namespaces."""
    registry = source_registry()
    groups = {}
    for row in rows:
        groups.setdefault((row.notice.recipient_id, row.notice.source), []).append(row)
    outcomes = {}
    policy_cache = {}
    for (_, source), batch in groups.items():
        adapter = registry.get(source)
        for offset in range(0, len(batch), 100):
            chunk = batch[offset : offset + 100]
            result = (
                evaluate(adapter, [_stored(r) for r in chunk], context, policy_cache=policy_cache)
                if adapter
                else {}
            )
            for row in chunk:
                outcomes[row.pk] = result.get(
                    row.event_id, Evaluation("defer", reason="unavailable")
                )
    return outcomes, registry


def project(
    context,
    status="active",
    source=None,
    cursor=None,
    render=True,
    public_ref=None,
    event_ids=None,
    page_size=25,
):
    """Project a bounded page or one explicitly addressed authorized envelope."""
    if not getattr(settings, "NOTICES_ENABLED", True):
        return []
    owners = Recipient.objects.filter(_scope(context))
    envelopes = Notice.objects.filter(recipient__in=owners).order_by("created_at", "pk")
    if source:
        envelopes = envelopes.filter(source=source)
    if public_ref:
        envelopes = envelopes.filter(public_ref=public_ref)
    if status not in {"history", "all"}:
        envelopes = envelopes.filter(
            retired_at__isnull=True,
            events__inactive_at__isnull=True,
            events__cleared_at__isnull=True,
        )
    if status == "history":
        envelopes = envelopes.filter(
            Q(retired_at__isnull=False)
            | Q(events__read_at__isnull=False)
            | Q(events__cleared_at__isnull=False)
            | Q(events__inactive_at__isnull=False)
        )
    elif status == "pending":
        envelopes = envelopes.filter(events__action_kind__isnull=False)
    if cursor:
        previous = envelopes.filter(public_ref=cursor).first()
        if previous is None:
            return []
        envelopes = envelopes.filter(
            Q(created_at__gt=previous.created_at)
            | Q(created_at=previous.created_at, pk__gt=previous.pk)
        )
    candidates = list(envelopes.distinct()[:page_size]) if page_size else list(envelopes.distinct())
    ids = [row.pk for row in candidates]
    rows_query = NoticeEvent.objects.filter(notice_id__in=ids)
    if event_ids is not None:
        rows_query = rows_query.filter(pk__in=event_ids)
    suppressed = ViewerSuppression.objects.filter(
        account=context.account, receipt__stored_event__isnull=False
    ).values_list("receipt__stored_event_id", flat=True)
    rows = list(
        rows_query.exclude(pk__in=suppressed)
        .select_related("notice__recipient")
        .order_by("occurred_at", "pk")
    )
    outcomes, registry = _evaluate_rows(rows, context)
    grouped = {}
    for row in rows:
        outcome = outcomes[row.pk]
        if outcome.status != "visible":
            continue
        historical = (
            row.inactive_at is not None
            or row.cleared_at is not None
            or row.notice.retired_at is not None
        )
        if status == "history" and not (historical or row.read_at):
            continue
        if status not in {"history", "all"} and (
            historical or (row.action_kind and not outcome.outstanding)
        ):
            continue
        if status in {"unread", "routine"} and row.read_at is not None and not outcome.outstanding:
            continue
        if status == "pending" and not outcome.outstanding:
            continue
        if status == "routine" and outcome.outstanding:
            continue
        grouped.setdefault(row.notice_id, []).append(row)
    result = ProjectionPage()
    result.next_cursor = (
        candidates[-1].public_ref if page_size and len(candidates) == page_size else None
    )
    for batch in grouped.values():
        envelope = batch[0].notice
        adapter = registry[envelope.source]
        try:
            rendered = (
                normalize_rendered(adapter.render([_stored(r) for r in batch], context))
                if render
                else None
            )
            actions = []
            for action in rendered.actions if rendered else ():
                url = None
                if action.route_name:
                    with suppress(NoReverseMatch):
                        url = reverse(action.route_name, args=action.route_args)
                actions.append((action.label, action.command, url))
        except Exception:
            logger.warning("Notice source presentation unavailable; retaining activity")
            continue
        result.append(
            ProjectedNotice(
                envelope,
                tuple(batch),
                tuple(outcomes[r.pk] for r in batch),
                rendered.text if rendered else "",
                tuple(actions),
                adapter.label,
            )
        )
    return result


def mutate(context, public_ref, operation):
    """Recheck read/clear under the same writer lock as replacement and compaction."""
    if operation not in {"read", "clear"}:
        raise ValueError("Unknown notice operation")

    def change():
        with transaction.atomic():
            _lock_account(context.account.pk)
            owners = list(
                Recipient.objects.filter(_scope(context)).order_by("account_id", "character_id")
            )
            for owner in owners:
                Recipient.objects.filter(pk=owner.pk).update(revision=F("revision"))
            item = next(iter(project(context, status="all", public_ref=public_ref)), None)
            if item is None:
                raise ValueError("Notice not available")
            if operation == "clear" and item.outstanding:
                raise ValueError("This decision must be resolved at its source")
            now = timezone.now()
            ids = [e.pk for e in item.events]
            if operation == "read":
                NoticeEvent.objects.filter(pk__in=ids, read_at__isnull=True).update(read_at=now)
            else:
                NoticeEvent.objects.filter(pk__in=ids, read_at__isnull=True).update(read_at=now)
                NoticeEvent.objects.filter(pk__in=ids, cleared_at__isnull=True).update(
                    cleared_at=now
                )
            Recipient.objects.filter(pk=item.notice.recipient_id).update(revision=F("revision") + 1)
            return item

    return _retry(change)


def set_preference(context, source, mode):
    """Store one account-wide source choice without replaying or reading activity."""
    if source not in source_registry() or mode not in {"immediate", "summary", "off"}:
        raise ValueError("Unknown source or preference")
    ownerships(context)

    def change():
        with transaction.atomic():
            _lock_account(context.account.pk)
            return SourcePreference.objects.update_or_create(
                account=context.account, source=source, defaults={"mode": mode}
            )[0]

    return _retry(change)


def _compact_locked(owner):
    limit = getattr(settings, "NOTICES_ROUTINE_LIMIT", 500)
    candidates = list(
        owner.notices.filter(
            retired_at__isnull=True,
            events__inactive_at__isnull=True,
            events__cleared_at__isnull=True,
            events__read_at__isnull=True,
            events__action_kind__isnull=True,
        )
        .distinct()
        .order_by("created_at", "pk")
    )
    if len(candidates) <= limit:
        return 0
    groups = {}
    for row in candidates:
        # An envelope containing a potential obligation is never compacted.
        if row.events.filter(action_kind__isnull=False, inactive_at__isnull=True).exists():
            continue
        groups.setdefault(row.source, []).append(row)
    total = len(candidates)
    if len(groups) > limit:
        raise RetryRouting
    changed = 0
    for batch in groups.values():
        if total <= limit:
            break
        if len(batch) < 2:
            continue
        target = next((n for n in batch if n.is_compacted), batch[0])
        target.is_compacted = True
        target.replacement_key = None
        target.save(update_fields=["is_compacted", "replacement_key"])
        others = [n.pk for n in batch if n.pk != target.pk]
        NoticeEvent.objects.filter(notice_id__in=others).update(notice=target)
        Notice.objects.filter(pk__in=others).delete()
        total -= len(others)
        changed += len(others)
    if total > limit:
        raise RetryRouting
    return changed


def _immediate(recipient, source, event_id):
    """Dispatch only the immutable new event, wherever compaction moved it."""
    try:
        kind, pk = recipient_identity(recipient)
        row_id = (
            DeliveryReceipt.objects.filter(
                recipient__in=Recipient.objects.filter(**{f"{kind}_id": pk}),
                source=source,
                event_id=event_id,
            )
            .values_list("stored_event_id", flat=True)
            .first()
        )
        if not row_id:
            return
        for context in connected_contexts(recipient):
            items = project(context, event_ids=[row_id], source=source, page_size=None)
            for item in items:
                if effective_mode(context.account, source, item.outstanding) == "immediate":
                    context.session.msg(f"{item.text}\nUse +notices to read or manage this alert.")
    except Exception:
        logger.warning("Notice immediate hint failed; durable inbox retained")


def summarize(context):
    """Count current safe activity without invoking source renderers or names."""
    items = project(context, status="unread", render=False, page_size=None)
    portions = {}
    for item in items:
        key = item.notice.recipient.identity
        rows = portions.setdefault(key, [])
        rows.extend(
            (item.notice.source, e.event_id, bool(e.read_at), o.outstanding, item.notice.public_ref)
            for e, o in zip(item.events, item.evaluations, strict=True)
        )
    session = context.session
    seen = getattr(session, "_notice_summaries", {}) if session else {}
    new = {k: tuple(sorted(v)) for k, v in portions.items() if tuple(sorted(v)) != seen.get(k)}
    if session:
        session._notice_summaries = {k: tuple(sorted(v)) for k, v in portions.items()}
    unread = len({r[4] for rows in new.values() for r in rows if not r[2]})
    pending = sum(r[3] for rows in new.values() for r in rows)
    if (unread or pending) and session:
        session.msg(
            f"Notices: {unread} unread alerts; {pending} outstanding decisions. Use +notices."
        )
    return unread, pending


def maintain(now=None):
    """Recheck source state, compact and prune aged acknowledged history."""
    if not getattr(settings, "NOTICES_ENABLED", True):
        return {"removed": 0, "compacted": 0}
    now = now or timezone.now()
    cutoff = now - timedelta(days=getattr(settings, "NOTICES_RETENTION_DAYS", 30))
    removed = compacted = 0
    for identity in Recipient.objects.order_by("pk").values_list("account_id", "character_id"):
        account_id, character_id = identity
        from evennia.objects.models import ObjectDB

        context = NoticeContext(
            AccountDB.objects.get(pk=account_id) if account_id else None,
            ObjectDB.objects.get(pk=character_id) if character_id else None,
        )
        with transaction.atomic():
            if account_id:
                _lock_account(account_id)
            owner = _recipient("account" if account_id else "character", account_id or character_id)
            rows = list(
                NoticeEvent.objects.filter(notice__recipient=owner).select_related(
                    "notice__recipient"
                )
            )
            outcomes, _ = _evaluate_rows(rows, context)
            for row in rows:
                outcome = outcomes[row.pk]
                if outcome.status == "invalid" or (account_id and outcome.status == "hidden"):
                    row.delete()
                    removed += 1
                elif (
                    row.action_kind
                    and outcome.status == "visible"
                    and not outcome.outstanding
                    and row.inactive_at is None
                ):
                    row.inactive_at, row.inactive_reason = now, "resolved"
                    row.save(update_fields=["inactive_at", "inactive_reason"])
                elif not row.action_kind or (not outcome.outstanding and outcome.status != "defer"):
                    clocks = [
                        clock for clock in (row.read_at, row.cleared_at, row.inactive_at) if clock
                    ]
                    clock = min(clocks) if clocks else None
                    if clock and clock <= cutoff:
                        row.delete()
                        removed += 1
            Notice.objects.filter(recipient=owner, events__isnull=True).delete()
            compacted += _compact_locked(owner)
    return {"removed": removed, "compacted": compacted}


def snapshot_ignore(sender, viewer, kind=None, **kwargs):
    """Remove activity already suppressed by old policy before unignore can revive it."""
    if kind is not None:
        return
    from evennia_links.characters import web_roster

    contexts = [NoticeContext(viewer)] + [NoticeContext(viewer, c) for c in web_roster(viewer)]
    with transaction.atomic():
        _lock_account(viewer.pk)
        for context in contexts:
            for owner in Recipient.objects.filter(_scope(context)).order_by("pk"):
                Recipient.objects.filter(pk=owner.pk).update(revision=F("revision"))
                rows = list(
                    NoticeEvent.objects.filter(notice__recipient=owner).select_related(
                        "notice__recipient"
                    )
                )
                outcomes, _ = _evaluate_rows(rows, context)
                if any(
                    r.actors
                    and outcomes[r.pk].status == "defer"
                    and outcomes[r.pk].reason != "context"
                    for r in rows
                ):
                    raise RetryRouting("Cannot safely snapshot current notice ignore policy")

                hidden_ids = [r.pk for r in rows if outcomes[r.pk].status == "hidden"]
                invalid_ids = [r.pk for r in rows if outcomes[r.pk].status == "invalid"]
                if owner.character_id:
                    receipts = DeliveryReceipt.objects.filter(stored_event_id__in=hidden_ids)
                    for receipt in receipts:
                        ViewerSuppression.objects.get_or_create(
                            receipt=receipt, account=viewer, defaults={"reason": "hidden"}
                        )
                    NoticeEvent.objects.filter(pk__in=invalid_ids).delete()
                else:
                    NoticeEvent.objects.filter(pk__in=hidden_ids + invalid_ids).delete()
                Notice.objects.filter(recipient=owner, events__isnull=True).delete()
