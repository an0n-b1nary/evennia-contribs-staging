# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Durable routing and connected standalone delivery for Social page alerts."""

import logging
from collections import Counter
from datetime import datetime

from django.apps import apps
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Exists, F, OuterRef
from django.utils import timezone
from evennia.accounts.models import AccountDB

from evennia_links.characters import playable_accounts
from evennia_links.guests import is_guest
from evennia_links.ignoring import ignore_policy_changing
from evennia_links.notices import (
    ActorRef,
    Evaluation,
    NoticeContext,
    RouteResult,
    authorize_context,
    connected_contexts,
    evaluate,
    notify,
    source_registry,
    transfer,
)

from .integrations.notices import (
    SOURCE,
    SocialPageNoticeSource,
    event_for,
    page_actor,
    page_subjects,
    stored_event,
    subject_status,
)
from .models import PageDelivery, PageProgress

logger = logging.getLogger("evennia")
Origin = PageDelivery.Origin
State = PageDelivery.State


def reserve_writer():
    """Reserve SQLite's writer before consulting membership or routing state."""
    if connection.vendor == "sqlite":
        AccountDB.objects.filter(pk__lt=0).update(last_login=F("last_login"))


def _memberships(characters, accounts=None):
    result = {character.pk: set() for character in characters}
    for owner_id, roster in playable_accounts(accounts):
        for character in roster:
            if character.pk in result:
                result[character.pk].add(owner_id)
    return result


def lock_recipient_owners(characters):
    if not characters:
        return {}
    reserve_writer()
    memberships = _memberships(characters)
    owner_ids = set().union(*memberships.values())
    accounts = {}
    for pk in sorted(owner_ids):
        AccountDB.objects.filter(pk=pk).update(last_login=F("last_login"))
        account = AccountDB.objects.select_for_update().filter(pk=pk).first()
        if account is not None and not is_guest(account):
            account.attributes.reset_cache()
            accounts[pk] = account
    memberships = _memberships(characters, AccountDB.objects.filter(pk__in=accounts))
    return {
        character.pk: [accounts[pk] for pk in sorted(memberships[character.pk])]
        for character in characters
        if not is_guest(character)
    }


def _record(character, page, actor, origin):
    return PageDelivery(
        character=character,
        message=page,
        occurred_at=getattr(page, "subject_date", page.db_date_created),
        origin=origin,
        actor_kind=actor.kind if actor else "",
        actor_id=actor.id if actor else None,
        state=State.PENDING if actor else State.SUPPRESSED,
    )


class _CurrentPagePolicy:
    """Check a preloaded page batch through the Links notice policy seam."""

    def __init__(self, rows, pages):
        self.rows = {event_for(row).event_id: row for row in rows}
        self.pages = pages

    def evaluate(self, events, context):
        outcomes = {}
        for event in events:
            row = self.rows[event.event_id]
            status = subject_status(row, self.pages.get(row.message_id), context.character)
            if context.account.pk in row.suppressed_owners:
                status = "hidden"
            outcomes[event.event_id] = Evaluation(status)
        return outcomes


def _statuses(rows, pages, context):
    policy = _CurrentPagePolicy(rows, pages)
    events = [stored_event(row) for row in rows]
    outcomes = evaluate(policy, events, context)
    return {row.message_id: outcomes[event_for(row).event_id].status for row in rows}


def _snapshot(rows, pages, account, character, *, strict=False):
    statuses = _statuses(rows, pages, NoticeContext(account, character))
    for row in rows:
        status = statuses[row.message_id]
        if status == "defer" and strict:
            raise RuntimeError("Social page ignore policy could not be checked")
        if status == "hidden" and account.pk not in row.suppressed_owners:
            row.suppressed_owners = sorted([*row.suppressed_owners, account.pk])
    return statuses


def record_offline(page, sender, targets, recipient_owners, *, fresh=True):
    actor = ActorRef("account" if isinstance(sender, AccountDB) else "character", sender.pk)
    for target in sorted(targets, key=lambda character: character.pk):
        owners = recipient_owners.get(target.pk)
        if not owners:
            continue
        row = _record(target, page, actor, Origin.OFFLINE)
        subjects = {subject.pk: subject for subject in page_subjects(target.pk).filter(pk=page.pk)}
        for owner in owners:
            _snapshot([row], subjects, owner, target)
        row.save()
        transaction.on_commit(lambda row=row: _safe_route(row.character, row.pk, fresh=fresh))


@transaction.atomic
def record_disconnected(page, sender, target):
    owners = lock_recipient_owners([target])
    if (
        owners.get(target.pk)
        and not PageDelivery.objects.filter(character=target, message=page).exists()
    ):
        record_offline(page, sender, [target], owners)


def _binding():
    """Identify deliberate absence separately from broken configured bindings."""
    configured = getattr(settings, "LINKS_NOTICE_SOURCES", {})
    if not isinstance(configured, dict):
        return "retry"
    if SOURCE not in configured:
        return "fallback_pending"
    try:
        if not isinstance(source_registry().get(SOURCE), SocialPageNoticeSource):
            return "retry"
    except (ImportError, ValueError, TypeError):
        return "retry"
    return "configured"


def _active():
    return (
        apps.is_installed("evennia_notices")
        and getattr(settings, "NOTICES_ENABLED", True)
        and _binding() == "configured"
    )


def _fallback_pending(*args):
    return RouteResult("fallback_pending")


def _route(row, *, fresh=False, context=None):
    if row.state != State.PENDING:
        return row.state
    binding = _binding()
    if binding != "configured":
        return binding
    if row.origin == Origin.LIVE:
        return "retry" if _active() else "fallback_pending"
    event = event_for(row)
    kwargs = dict(source=SOURCE, event=event, context=context, fallback=_fallback_pending)
    with transaction.atomic():
        if fresh:
            result = notify(row.character, **kwargs)
        else:
            result = transfer(row.character, transfer_id=event.event_id, **kwargs)
        if result.status == "fallback_pending":
            return result.status
        if result.status not in {"retained", "duplicate", "suppressed"}:
            raise RuntimeError("Social page route was not acknowledged")
        row.state = State.SUPPRESSED if result.status == "suppressed" else State.INBOX
        row.save(update_fields=["state"])
        return row.state


def _safe_route(character, row_id, *, fresh=False, context=None):
    try:
        with transaction.atomic():
            owners = lock_recipient_owners([character]).get(character.pk)
            if not owners or (
                context is not None and context.account.pk not in {owner.pk for owner in owners}
            ):
                return "retry"
            row = _pending(character).filter(pk=row_id).first()
            return _route(row, fresh=fresh, context=context) if row else "settled"
    except Exception:
        logger.warning("Social page routing deferred")
        return "retry"


def _pending(character):
    return (
        PageDelivery.objects.select_for_update()
        .filter(character_id=character.pk, state=State.PENDING)
        .order_by("message_id")
    )


def _unclaimed_pages(character, cutoff):
    claimed = PageDelivery.objects.filter(character=character, message_id=OuterRef("pk"))
    pages = page_subjects(character.pk).filter(~Exists(claimed)).order_by("pk")
    return pages.filter(db_date_created__gt=cutoff) if cutoff else pages


def _cutoff(character):
    return datetime.fromisoformat(character.last_page_seen) if character.last_page_seen else None


def _stage(character, pages, owners):
    rows = [
        _record(character, page, page_actor(page), Origin.LIVE if page.generated else Origin.LEGACY)
        for page in pages
    ]
    pages = {page.pk: page for page in pages}
    for owner in owners:
        _snapshot(rows, pages, owner, character)
    PageDelivery.objects.bulk_create(rows)


def prepare(context, *, limit=100, allow_fallback=False):
    """Discover one legacy batch and rotate pending work through quiet transfers."""
    character = context.character
    if character is None or not authorize_context(context) or is_guest(character):
        return Counter(), False
    if not _active():
        return Counter(), False
    with transaction.atomic():
        owners = lock_recipient_owners([character]).get(character.pk)
        if not owners or context.account.pk not in {owner.pk for owner in owners}:
            return Counter(), False
        progress, _ = PageProgress.objects.get_or_create(character=character)
        candidates = _unclaimed_pages(character, _cutoff(character)).filter(
            pk__gt=progress.legacy_position, generated=False
        )
        pages = list(candidates[:limit])
        if pages:
            _stage(character, pages, owners)
            progress.legacy_position = pages[-1].pk
        pending = _pending(character).exclude(origin=Origin.LIVE)
        rows = list(pending.filter(message_id__gt=progress.retry_position)[:limit])
        if not rows and progress.retry_position:
            rows = list(pending[:limit])
        progress.retry_position = rows[-1].message_id if rows else 0
        progress.save(update_fields=["legacy_position", "retry_position"])
    outcomes = Counter(_safe_route(character, row.pk, context=context) for row in rows)
    if allow_fallback and outcomes["fallback_pending"]:
        _standalone(character, discover=False)
    more = (
        len(pages) == limit
        or PageDelivery.objects.filter(character=character, state=State.PENDING)
        .exclude(origin=Origin.LIVE)
        .exists()
    )
    return outcomes, more


def _snapshot_ignore(sender, viewer, kind=None, **kwargs):
    if kind not in (None, "notices") or is_guest(viewer):
        return
    for character_id, roster in playable_accounts(AccountDB.objects.filter(pk=viewer.pk)):
        if character_id != viewer.pk:
            continue
        for character in sorted(roster, key=lambda item: item.pk):
            rows = list(
                PageDelivery.objects.select_for_update()
                .filter(character=character, state__in=(State.PENDING, State.CLAIMED))
                .order_by("message_id")
            )
            if not rows:
                continue
            pages = {
                page.pk: page
                for page in page_subjects(character.pk).filter(
                    pk__in=[row.message_id for row in rows]
                )
            }
            _snapshot(rows, pages, viewer, character, strict=True)
            PageDelivery.objects.bulk_update(rows, ["suppressed_owners"])


def register():
    ignore_policy_changing.connect(_snapshot_ignore, dispatch_uid="evennia_social.page_notices")


def _sessions(character, *, guest=False):
    if not guest:
        return list(connected_contexts(character))
    from evennia.server.sessionhandler import SESSIONS

    return [
        NoticeContext(account, character, session)
        for session in SESSIONS.get_sessions()
        if (account := session.get_account()) is not None
        and is_guest(account)
        and session.get_puppet() == character
        and character.account == account
    ]


def _still_connected(context, *, guest):
    return any(
        current.session is context.session and current.account == context.account
        for current in _sessions(context.character, guest=guest)
    )


def _render_reminder(count):
    plural = "s" if count != 1 else ""
    return f"|wYou have {count} unread page{plural}.|n Use |wpage/last {count}|n to view."


def _visible_reminder_pages(rows, character, context, *, guest):
    if not guest:
        rows = list(
            PageDelivery.objects.filter(pk__in=[row.pk for row in rows], state=State.CLAIMED)
        )
    pages = {
        page.pk: page
        for page in page_subjects(character.pk).filter(pk__in=[row.message_id for row in rows])
    }
    return {pk for pk, status in _statuses(rows, pages, context).items() if status == "visible"}


def _send_reminder(rows, character, contexts, attempted, delivered, *, guest=False):
    for context in contexts:
        try:
            if not _still_connected(context, guest=guest):
                continue
            visible = _visible_reminder_pages(rows, character, context, guest=guest)
            if not visible:
                continue
            text = _render_reminder(len(visible))
            if visible != _visible_reminder_pages(
                rows, character, context, guest=guest
            ) or not _still_connected(context, guest=guest):
                continue
            attempted.update(visible)
            context.session.msg(text)
            delivered.update(visible)
        except Exception:
            logger.warning("Social page reminder did not complete on one connection")


@transaction.atomic
def _claim_fallback(character, contexts, *, discover):
    owners = lock_recipient_owners([character]).get(character.pk)
    if not owners:
        return [], None
    if discover and _active():
        return [], None
    owner_ids = {owner.pk for owner in owners}
    contexts = [
        context
        for context in contexts
        if context.account.pk in owner_ids and authorize_context(context)
    ]
    if not contexts:
        return [], None
    boundary = timezone.now().isoformat()
    if discover:
        _stage(character, list(_unclaimed_pages(character, _cutoff(character))), owners)
    eligible = []
    unresolved = False
    for row in _pending(character):
        try:
            result = _route(row)
        except Exception:
            result = "retry"
        if result == "fallback_pending":
            eligible.append(row)
        elif result == "retry":
            unresolved = True
    if eligible:
        pages = {
            page.pk: page
            for page in page_subjects(character.pk).filter(
                pk__in=[row.message_id for row in eligible]
            )
        }
        visible = set()
        for context in contexts:
            for pk, status in _statuses(eligible, pages, context).items():
                if status == "visible":
                    visible.add(pk)
                elif status == "defer":
                    unresolved = True
        eligible = [row for row in eligible if row.message_id in visible]
    for row in eligible:
        row.state = State.CLAIMED
    PageDelivery.objects.bulk_update(eligible, ["state"])
    if discover and not eligible and not unresolved:
        character.last_page_seen = boundary
    return eligible, boundary if discover else None


@transaction.atomic
def _finish_fallback(character, rows, attempted, delivered, boundary):
    if not lock_recipient_owners([character]).get(character.pk):
        return
    for row in rows:
        state = (
            State.FALLBACK
            if row.message_id in delivered
            else State.UNCERTAIN
            if row.message_id in attempted
            else State.PENDING
        )
        PageDelivery.objects.filter(pk=row.pk, state=State.CLAIMED).update(state=state)
    if attempted and boundary is not None:
        previous = _cutoff(character)
        if previous is None or previous < datetime.fromisoformat(boundary):
            character.last_page_seen = boundary


def _standalone(character, *, discover=True):
    contexts = _sessions(character)
    if not contexts:
        return
    rows, boundary = _claim_fallback(character, contexts, discover=discover)
    if rows:
        attempted, delivered = set(), set()
        try:
            _send_reminder(rows, character, contexts, attempted, delivered)
        finally:
            _finish_fallback(character, rows, attempted, delivered, boundary)


def _guest_reminder(character):
    contexts = _sessions(character, guest=True)
    if not contexts:
        return
    if character.ndb.social_page_claim is not None:
        return
    seen = character.ndb.social_page_attempts or set()
    cutoff = character.ndb.social_page_cutoff
    if cutoff is None:
        cutoff = character.ndb.social_page_cutoff = _cutoff(character) or False
    pages = page_subjects(character.pk).exclude(pk__in=seen)
    if cutoff:
        pages = pages.filter(db_date_created__gt=cutoff)
    rows = [
        _record(character, page, actor, Origin.LIVE)
        for page in pages
        if (actor := page_actor(page)) is not None
    ]
    if rows:
        attempted, delivered = set(), set()
        character.ndb.social_page_claim = attempted
        try:
            _send_reminder(rows, character, contexts, attempted, delivered, guest=True)
        finally:
            character.ndb.social_page_attempts = seen | attempted
            character.ndb.social_page_claim = None


def puppet_reminder(character):
    """Preserve the standalone aggregate and connected-only guest reminders."""
    try:
        if is_guest(character):
            _guest_reminder(character)
        elif not _active():
            transaction.on_commit(lambda: _standalone(character), robust=True)
    except Exception:
        logger.warning("Social page reminder deferred")
