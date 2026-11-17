# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Durable account outcomes, optional Inbox routing and standalone delivery."""

import logging
from dataclasses import asdict

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone
from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB

from evennia_links.guests import is_guest
from evennia_links.notices import (
    ActorRef,
    NoticeEvent,
    RouteResult,
    StoredEvent,
    SubjectRef,
    authorize_context,
    connected_contexts,
    evaluate,
    normalize_rendered,
    source_registry,
    transfer,
)
from evennia_links.notices import notify as route_event

from .integrations.notices import ModerationNoticeSource, event_for, render_payload
from .models import Notice, NoticeCursor

logger = logging.getLogger("evennia")
TERMINAL = {"inbox", "fallback", "suppressed", "invalid"}


def record_unknown(account, text):
    """Preserve custom history without guessing its subject, actor or disclosure policy."""
    if account is not None and not is_guest(account):
        return Notice.objects.create(account=account, text=text)
    return None


def _actor_refs(actor):
    if actor is None:
        return ()
    if not isinstance(actor, AccountDB | ObjectDB) or not actor.pk:
        raise ValueError("Outcome actor must be a saved account or character")
    return (ActorRef("account" if isinstance(actor, AccountDB) else "character", actor.pk),)


def record_outcome(
    account, *, kind, submission_id, applicant_name, actor=None, reason="", shared_reason=False
):
    """Record one source transition inside the admissions transaction.

    Only a known system lapse has no actor. The producer supplies the durable
    original submission identity, never an applicant-name or timestamp guess.
    """
    if account is None:
        return None
    if kind not in {"approved", "declined", "lapsed"}:
        raise ValueError("Unknown moderation outcome")
    if type(submission_id) is not int or submission_id <= 0:
        raise ValueError("Original submission identity required")
    if (kind in {"approved", "declined"} and actor is None) or (
        kind == "lapsed" and actor is not None
    ):
        raise ValueError("Outcome requires explicit reviewer or system provenance")
    if (
        type(shared_reason) is not bool
        or not isinstance(reason, str)
        or not isinstance(applicant_name, str)
    ):
        raise ValueError("Invalid outcome presentation snapshot")
    shared_reason = kind == "declined" and shared_reason
    payload = {
        "kind": kind,
        "recipient": account.pk,
        "submission": submission_id,
        "applicant_name": applicant_name,
        "reason": reason if shared_reason else "",
        "shared_reason": shared_reason,
    }
    key = f"moderation-{submission_id}-{kind}-{account.pk}"
    return _record(account, key, payload, _actor_refs(actor))


def record_example(account, token):
    """Record a labelled simulation without creating any admissions workflow record."""
    if not isinstance(token, str) or not token or len(token) > 64:
        raise ValueError("Synthetic identity required")
    payload = {
        "kind": "example",
        "recipient": account.pk,
        "applicant_name": "",
        "reason": "",
        "shared_reason": False,
    }
    return _record(account, f"moderation-example-{account.pk}-{token}", payload, ())


def _record(account, key, payload, actors):
    if not isinstance(account, AccountDB) or not account.pk:
        raise ValueError("Moderation outcomes require a saved account recipient")
    if is_guest(account):
        transaction.on_commit(lambda: _safe_guest(account, key, payload, actors))
        return None
    with transaction.atomic():
        # A writer before get_or_create avoids read-to-write upgrades on SQLite.
        Notice.objects.filter(event_key=key).update(event_key=F("event_key"))
        row, created = Notice.objects.get_or_create(
            event_key=key,
            defaults={
                "account": account,
                "text": normalize_rendered(render_payload(payload, mode="account")).text,
                "kind": payload["kind"],
                "provenance_known": True,
            },
        )
        complete = {**payload, "notice": row.pk}
        if created:
            event = NoticeEvent(
                key, row.created_at, SubjectRef("moderation-outcome", str(row.pk)), actors, complete
            )
            row.envelope = asdict(event)
            row.envelope["occurred_at"] = event.occurred_at.isoformat()
            row.save(update_fields=["envelope"])
        else:
            event = event_for(row)
            if (
                row.account_id != account.pk
                or row.envelope["payload"] != complete
                or event.actors != actors
            ):
                raise ValueError("Outcome identity collision")
        transaction.on_commit(lambda: _safe_route(row.pk, fresh=created))
    return row


def _actor_policy(account, actors):
    from evennia_links.ignoring import notice_ignore_status

    for actor in actors:
        model = {"account": AccountDB, "character": ObjectDB}[actor.kind]
        live = model.objects.filter(pk=actor.id).first()
        if live is None:
            return "defer"
        status = notice_ignore_status(account, live)
        if status != "allow":
            return status
    return "allow"


def _live_context(context, account):
    return authorize_context(context, account) and any(
        current.session is context.session for current in connected_contexts(account)
    )


def _safe_guest(account, key, payload, actors):
    """Guests retain only transient session claims, including uncertain attempts."""
    try:
        for context in connected_contexts(account):
            if not AccountDB.objects.filter(pk=account.pk).exists() or not _live_context(
                context, account
            ):
                continue
            if _actor_policy(account, actors) != "allow":
                continue
            seen = getattr(context.session, "_moderation_notice_attempts", set())
            if not isinstance(seen, set):
                seen = set()
            if key in seen:
                continue
            text = normalize_rendered(render_payload(payload)).text
            if not _live_context(context, account):
                continue
            context.session._moderation_notice_attempts = seen | {key}
            try:
                context.session.msg(text)
            except Exception:
                logger.warning("Moderation guest delivery uncertain; transient claim retained")
    except Exception:
        logger.warning("Moderation guest delivery deferred")


def _safe_route(pk, *, fresh=False, context=None):
    try:
        return route_notice(pk, fresh=fresh, context=context)
    except Exception:
        logger.warning("Moderation notice routing deferred", exc_info=True)
        return "retry"


def _ack(row, state):
    row.route_state = state
    row.acknowledged_at = timezone.now() if state in TERMINAL else None
    fields = ["route_state", "acknowledged_at"]
    if state == "fallback":
        row.delivered_at = row.acknowledged_at
        fields.append("delivered_at")
    row.save(update_fields=fields)


def _allowed(row, context):
    event = StoredEvent(
        **event_for(row).__dict__, recipient_kind="account", recipient_id=row.account_id
    )
    return evaluate(ModerationNoticeSource(), [event], context)[event.event_id].status


def route_notice(pk, *, fresh=False, context=None):
    """Choose one durable route under account then source locks, never Jobs locks."""
    candidate = Notice.objects.get(pk=pk)
    with transaction.atomic():
        AccountDB.objects.filter(pk=candidate.account_id).update(last_login=F("last_login"))
        account = AccountDB.objects.select_for_update().get(pk=candidate.account_id)
        Notice.objects.filter(pk=pk).update(route_state=F("route_state"))
        row = Notice.objects.select_for_update().get(pk=pk)
        if row.account_id != account.pk:
            return "retry"
        if row.delivered_at is not None:
            return "fallback"
        if row.route_state != "pending":
            return row.route_state
        if not row.provenance_known:
            return "held"
        try:
            event_for(row)
        except (KeyError, ValueError, TypeError, AttributeError):
            return "held"
        if is_guest(account):
            # Unknown pre-adapter guest history remains held, never imported.
            return "held"
        if context is not None and not authorize_context(context, account):
            return "held"
        try:
            registry = source_registry()
            configured = getattr(settings, "LINKS_NOTICE_SOURCES", {})
            if "moderation" in configured and "moderation" not in registry:
                return "retry"
            if "moderation" in registry:
                with transaction.atomic():
                    result = (route_event if fresh else transfer)(
                        account,
                        source="moderation",
                        event=event_for(row),
                        context=context,
                        fallback=lambda *args: RouteResult("fallback_pending"),
                        **(
                            {} if fresh else {"transfer_id": f"moderation-transfer-{row.event_key}"}
                        ),
                    )
                    if result.status in {"retained", "duplicate", "suppressed"}:
                        _ack(row, "suppressed" if result.status == "suppressed" else "inbox")
                        return row.route_state
                    if result.status != "fallback_pending":
                        raise RuntimeError("Routing not acknowledged")
        except Exception:
            return "retry"
        contexts = list(connected_contexts(account))
        if not contexts:
            return "pending"
        statuses = [_allowed(row, current) for current in contexts]
        if all(status in {"invalid", "hidden"} for status in statuses):
            _ack(row, "invalid" if "invalid" in statuses else "suppressed")
            return row.route_state
        if "visible" not in statuses:
            return "held"
        try:
            # Deterministic configuration/presentation failures precede a socket
            # claim. They remain retryable rather than become uncertain sends.
            normalize_rendered(render_payload(row.envelope["payload"]))
        except Exception:
            return "retry"
        row.route_state = "attempting"
        row.save(update_fields=["route_state"])
    # The source attempt must commit before any socket side effect.
    if connection.in_atomic_block:
        transaction.on_commit(lambda: _safe_deliver_claim(pk, contexts))
        return "attempting"
    return _safe_deliver_claim(pk, contexts)


def _safe_deliver_claim(pk, contexts):
    try:
        return _deliver_claim(pk, contexts)
    except Exception:
        logger.warning("Moderation fallback status unavailable; source attempt retained")
        return "attempting"


def _deliver_claim(pk, contexts):
    """Recheck each current account session after the durable transport claim."""
    row = Notice.objects.get(pk=pk)
    delivered = False
    for context in contexts:
        try:
            row.refresh_from_db()
            if not _live_context(context, row.account) or _allowed(row, context) != "visible":
                continue
            text = normalize_rendered(render_payload(row.envelope["payload"])).text
            if _live_context(context, row.account):
                context.session.msg(text)
                delivered = True
        except Exception:
            logger.warning("Moderation delivery uncertain; source attempt retained")
    _ack(row, "fallback" if delivered else "uncertain")
    return row.route_state


def transfer_pending(account=None, *, context=None, limit=None):
    """Advance one bounded page past held/failed rows, with independent row retries."""
    limit = getattr(settings, "MODERATION_NOTICE_TRANSFER_BATCH", 100) if limit is None else limit
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Moderation transfer limit must be 1 through 1000")
    query = Notice.objects.filter(route_state="pending", delivered_at__isnull=True).order_by("pk")
    if account is not None:
        query = query.filter(account=account)
    guest = account is not None and is_guest(account)
    scope = f"account-{account.pk}" if account is not None else "all"
    cursor = None if guest else NoticeCursor.objects.get_or_create(scope=scope)[0]
    last = (
        (getattr(account.ndb, "moderation_transfer_position", 0) or 0) if guest else cursor.last_pk
    )
    ids = list(query.filter(pk__gt=last).values_list("pk", flat=True)[:limit])
    if not ids and last:
        ids = list(query.values_list("pk", flat=True)[:limit])
    counts = dict.fromkeys(
        (
            "inbox",
            "fallback",
            "suppressed",
            "invalid",
            "held",
            "retry",
            "pending",
            "uncertain",
            "attempting",
        ),
        0,
    )
    for pk in ids:
        outcome = _safe_route(pk, context=context)
        counts[outcome] = counts.get(outcome, 0) + 1
    if ids:
        if guest:
            account.ndb.moderation_transfer_position = ids[-1]
        else:
            cursor.last_pk = ids[-1]
            cursor.save(update_fields=["last_pk"])
    counts["continuation"] = query.filter(pk__gt=ids[-1] if ids else last).count()
    return counts


def deliver_notices(account, only=None, *, context=None):
    """Compatibility entry point; raw text history is never transported."""
    if only is not None:
        if Notice.objects.filter(pk=only, account=account).exists():
            return _safe_route(only, context=context)
        return "held"
    return transfer_pending(account, context=context)
