# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""XP-owned staging and delivery for committed weekly summaries."""

import logging
from dataclasses import dataclass
from threading import Lock
from time import monotonic, sleep
from uuid import uuid4

from django.apps import apps
from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.db.models import Exists, F, OuterRef
from django.utils import timezone
from evennia.accounts.accounts import DefaultGuest
from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB

from .models import CharacterXP, XPLog, XPNoticeReceipt
from .summary import SUMMARY_WEEK_ATTRIBUTE, grouped_totals, summary_text

SOURCE = "xp"
Origin = XPNoticeReceipt.Origin
State = XPNoticeReceipt.State
ACKNOWLEDGED = (State.TRANSFERRED, State.SUPPRESSED, State.DELIVERED)
logger = logging.getLogger("evennia")


def reserve_writer():
    """Acquire the SQLite write reservation before any reads in the transaction."""
    if connection.vendor == "sqlite":
        CharacterXP.objects.filter(pk__lt=0).update(total_earned=F("total_earned"))


def _sqlite_retry(operation):
    try:
        return operation()
    except OperationalError as exc:
        if connection.vendor != "sqlite" or "locked" not in str(exc).lower():
            raise
    sleep(0.025)
    return operation()


def _backend():
    if not apps.is_installed("evennia_notices") or not getattr(settings, "NOTICES_ENABLED", True):
        return "standalone"
    configured = getattr(settings, "LINKS_NOTICE_SOURCES", {})
    try:
        from evennia_links.notices import source_registry

        from .integrations.notices import XPNoticeSource

        sources = source_registry()
        if SOURCE not in configured:
            return "standalone"
        if isinstance(sources.get(SOURCE), XPNoticeSource):
            return "inbox"
    except Exception:
        logger.warning("XP notice binding could not be resolved")
    return "retry"


def _core_roster(account):
    account.attributes.reset_cache()
    # Refresh the stored Attribute value as well as the handler's lookup cache.
    attribute = account.attributes.get("_playable_characters", return_obj=True)
    if attribute is not None:
        attribute.refresh_from_db(fields=["db_value"])
    return account.characters.all()


def owner_ids(character):
    """Resolve current ordinary roster membership, including offline owners."""
    if apps.is_installed("evennia_links"):
        from evennia_links.characters import account_ids

        accounts = AccountDB.objects.in_bulk(account_ids(character))
        return {
            account.pk for account in accounts.values() if not isinstance(account, DefaultGuest)
        }

    return {
        account.pk
        for account in AccountDB.objects.all().iterator()
        if not isinstance(account, DefaultGuest) and character in _core_roster(account)
    }


def _on_roster(account, character):
    if apps.is_installed("evennia_links"):
        from evennia_links.characters import playable_accounts

        return any(
            character in roster
            for _, roster in playable_accounts(AccountDB.objects.filter(pk=account.pk))
        )
    return character in _core_roster(account)


def _is_guest(obj):
    if apps.is_installed("evennia_links"):
        from evennia_links.guests import is_guest

        return is_guest(obj)
    if isinstance(obj, AccountDB):
        return isinstance(obj, DefaultGuest)
    if isinstance(obj, ObjectDB):
        if isinstance(obj.account, DefaultGuest):
            return True
        return any(
            isinstance(account, DefaultGuest) and obj in _core_roster(account)
            for account in AccountDB.objects.all().iterator()
        )
    return False


def _disposable(character):
    return _is_guest(character) and not owner_ids(character)


def _seen(character):
    character.attributes.reset_cache()
    attribute = character.attributes.get(SUMMARY_WEEK_ATTRIBUTE, return_obj=True)
    if attribute is not None:
        attribute.refresh_from_db(fields=["db_value"])
        return attribute.value
    return None


def _week_logs(aggregate, week, *, exclude=None):
    logs = XPLog.objects.filter(character_id=aggregate.character_id, week=week)
    if exclude is not None:
        logs = logs.exclude(pk=exclude)
    return logs


def _stage_legacy(aggregate, character, *, exclude=None, origin=Origin.LEGACY):
    week = aggregate.last_payout_week
    if not week or character is None:
        return
    receipts = XPNoticeReceipt.objects.filter(summary=aggregate, week=week)
    if receipts.exists() or _seen(character) == week:
        return
    first = _week_logs(aggregate, week, exclude=exclude).order_by("awarded_at", "pk").first()
    if first is not None:
        return XPNoticeReceipt.objects.create(
            summary=aggregate, week=week, occurred_at=first.awarded_at, origin=origin
        )


def stage_award(aggregate, log):
    """Stage only after the new ledger row exists and before its pointer replaces the old one."""
    character = ObjectDB.objects.filter(pk=aggregate.character_id).first()
    if character is not None:
        try:
            if _disposable(character):
                sessions = _eligible_connections(character, "guest")
                if sessions and not _week_logs(aggregate, log.week, exclude=log.pk).exists():
                    transaction.on_commit(
                        lambda: _stage_guest(character, log.week, sessions), robust=True
                    )
                return
        except Exception:
            logger.warning("XP notice could not resolve guest identity")
            return

    backend = _backend()
    if backend != "standalone":
        _stage_legacy(aggregate, character, exclude=log.pk)
    receipts = XPNoticeReceipt.objects.filter(summary=aggregate)
    if receipts.filter(week=log.week).exists():
        return
    previous = _week_logs(aggregate, log.week, exclude=log.pk).order_by("awarded_at", "pk").first()
    seen = _seen(character) if character is not None else None
    state = (
        State.SUPERSEDED
        if seen == log.week or (previous is not None and aggregate.last_payout_week != log.week)
        else State.PENDING
    )
    if backend == "standalone":
        origin = Origin.STANDALONE
        if state == State.PENDING:
            receipts.filter(origin=Origin.STANDALONE, state=State.PENDING).update(
                state=State.SUPERSEDED
            )
    else:
        origin = Origin.INBOX if previous is None else Origin.LEGACY
    receipt = receipts.create(
        summary=aggregate,
        week=log.week,
        occurred_at=(previous or log).awarded_at,
        origin=origin,
        state=state,
    )
    if state == State.PENDING and backend == "inbox" and character is not None:
        transaction.on_commit(
            lambda: _safe_route(character, receipt.pk, fresh=origin == Origin.INBOX),
            robust=True,
        )


@dataclass(frozen=True)
class Connection:
    session: object
    account: AccountDB
    character: ObjectDB


def _registered_sessions():
    from evennia.server.sessionhandler import SESSIONS

    return SESSIONS.get_sessions()


def is_live_connection(current):
    session, account, character = current.session, current.account, current.character
    return (
        any(item is session for item in _registered_sessions())
        and session.logged_in
        and session.get_puppet() is character
        and session.get_account() is account
        and character.account is account
    )


def _eligible(current, mode):
    if mode == "guest":
        allowed = (
            _is_guest(current.account)
            and _on_roster(current.account, current.character)
            and not owner_ids(current.character)
        )
    else:
        if _is_guest(current.account):
            return False
        owners = owner_ids(current.character)
        if owners:
            allowed = mode != "nonroster" and current.account.pk in owners
        else:
            allowed = mode != "inbox" and not _is_guest(current.character)
    return allowed and is_live_connection(current)


def _eligible_connections(character, mode, *, session=None):
    connections = []
    for registered in _registered_sessions():
        if session is not None and registered is not session:
            continue
        try:
            if not registered.logged_in or registered.get_puppet() is not character:
                continue
            account = registered.get_account()
            if not isinstance(account, AccountDB) or not account.pk:
                continue
            current = Connection(registered, account, character)
            if _eligible(current, mode):
                connections.append(current)
        except Exception:
            logger.warning("XP notice skipped an unavailable connection")
    return connections


def _locked_summary(character):
    reserve_writer()
    return CharacterXP.objects.select_for_update().filter(character_id=character.pk).first()


def _acknowledge(row, character):
    """Repair the compatibility Attribute in settlement order, under the aggregate lock."""
    siblings = XPNoticeReceipt.objects.filter(summary_id=row.summary_id, state__in=ACKNOWLEDGED)
    latest = siblings.order_by("-acknowledged_at", "-pk").first()
    if latest is None:
        return
    try:
        with transaction.atomic():
            if latest.compatibility_pending and _seen(character) != latest.week:
                character.attributes.add(SUMMARY_WEEK_ATTRIBUTE, latest.week)
            siblings.filter(compatibility_pending=True).update(compatibility_pending=False)
    except Exception:
        logger.warning("XP summary compatibility marker update deferred")


def _fallback_pending(*args):
    from evennia_links.notices import RouteResult

    return RouteResult("fallback_pending")


@transaction.atomic
def _route(character, receipt_id, *, fresh, context=None):
    from evennia_links.notices import notify, transfer

    aggregate = _locked_summary(character)
    if aggregate is None or _backend() != "inbox" or _disposable(character):
        return
    if context is not None:
        current = Connection(context.session, context.account, character)
        if not _eligible(current, "inbox"):
            return
    elif not owner_ids(character):
        return
    row = (
        XPNoticeReceipt.objects.select_for_update()
        .filter(summary=aggregate, pk=receipt_id, state=State.PENDING)
        .first()
    )
    if row is None or not _week_logs(aggregate, row.week).exists():
        return
    row.last_attempt_at = timezone.now()
    row.save(update_fields=["last_attempt_at"])
    from .integrations.notices import event_for

    event = event_for(row, character.pk)
    kwargs = dict(source=SOURCE, event=event, context=context, fallback=_fallback_pending)
    result = (
        notify(character, **kwargs)
        if fresh
        else transfer(character, transfer_id=event.event_id, **kwargs)
    )
    if not result.receipt or result.status not in {"retained", "duplicate", "suppressed"}:
        return
    row.state = State.SUPPRESSED if result.status == "suppressed" else State.TRANSFERRED
    row.acknowledged_at = timezone.now()
    row.compatibility_pending = True
    row.save(update_fields=["state", "acknowledged_at", "compatibility_pending"])
    _acknowledge(row, character)


@transaction.atomic
def _mark_attempt(character, receipt_id):
    aggregate = _locked_summary(character)
    if aggregate is not None:
        XPNoticeReceipt.objects.filter(
            summary=aggregate, pk=receipt_id, state=State.PENDING
        ).update(last_attempt_at=timezone.now())


def _safe_route(character, receipt_id, *, fresh=False, context=None):
    try:
        _sqlite_retry(lambda: _route(character, receipt_id, fresh=fresh, context=context))
    except Exception:
        logger.warning("XP notice dispatch deferred")
        try:
            _sqlite_retry(lambda: _mark_attempt(character, receipt_id))
        except Exception:
            logger.warning("XP notice retry position unavailable")


@transaction.atomic
def _prepare_receipts(character, mode):
    aggregate = _locked_summary(character)
    if aggregate is None or _disposable(character):
        return None
    _stage_legacy(
        aggregate, character, origin=Origin.LEGACY if mode == "inbox" else Origin.STANDALONE
    )
    rows = XPNoticeReceipt.objects.filter(summary=aggregate)
    repair = rows.filter(compatibility_pending=True).first()
    if repair is not None:
        _acknowledge(repair, character)
    if mode == "inbox":
        ledger = XPLog.objects.filter(character_id=character.pk, week=OuterRef("week"))
        return list(
            rows.filter(Exists(ledger), state=State.PENDING)
            .order_by(F("last_attempt_at").asc(nulls_first=True), "pk")
            .values_list("pk", flat=True)[:100]
        )
    expected = "inbox" if mode == "nonroster" else "standalone"
    if _backend() != expected:
        return None
    row = (
        rows.select_for_update()
        .filter(week=aggregate.last_payout_week, state=State.PENDING)
        .first()
    )
    if row is None:
        return None
    claim = uuid4()
    # The claim is durable before transport. Its order, assigned under the same
    # aggregate lock as Inbox settlements, governs a delayed marker repair.
    claimed = rows.filter(pk=row.pk, state=State.PENDING).update(
        state=State.ATTEMPTING, claim=claim, acknowledged_at=timezone.now()
    )
    if claimed:
        row.claim = claim
        return row


def _send(character, week, connections, mode, *, claim=None):
    from .summary import uses_screenreader

    attempted = delivered = False
    for current in connections:
        try:
            if not is_live_connection(current):
                continue
            totals = grouped_totals(character.pk, [week]).get(week)
            if not totals:
                continue
            text = summary_text(week, totals, plain=uses_screenreader(current.account))
            writer = character.msg
            if not callable(writer):
                continue
            if mode == "guest":
                if not _guest_attempting(character, claim):
                    continue
            else:
                expected = "inbox" if mode == "nonroster" else "standalone"
                if (
                    _backend() != expected
                    or not XPNoticeReceipt.objects.filter(
                        pk=claim.pk,
                        claim=claim.claim,
                        state=State.ATTEMPTING,
                        summary__last_payout_week=week,
                    ).exists()
                ):
                    continue
            if not _eligible(current, mode):
                continue
            attempted = True
            writer(text, session=current.session)
            delivered = True
        except Exception:
            logger.warning("XP notice did not complete on one connection")
    return attempted, delivered


@transaction.atomic
def _finalize(character, row, attempted, delivered):
    aggregate = _locked_summary(character)
    if aggregate is None:
        return
    state = State.DELIVERED if delivered else (State.UNCERTAIN if attempted else State.PENDING)
    claim = XPNoticeReceipt.objects.filter(
        summary=aggregate, pk=row.pk, claim=row.claim, state=State.ATTEMPTING
    )
    updates = dict(state=state, claim=None, compatibility_pending=delivered)
    if not delivered:
        updates["acknowledged_at"] = None
    if claim.update(**updates) and delivered:
        _acknowledge(row, character)


_waiting = {}
_waiting_lock = Lock()


def _settle(character, row, attempted, delivered):
    try:
        _sqlite_retry(lambda: _finalize(character, row, attempted, delivered))
    except Exception:
        with _waiting_lock:
            _waiting[row.claim] = (character, row, attempted, delivered)
        logger.warning("XP notice finalization deferred")
    else:
        with _waiting_lock:
            _waiting.pop(row.claim, None)


def _finish_known(character):
    with _waiting_lock:
        outcomes = [outcome for outcome in _waiting.values() if outcome[0].pk == character.pk][:100]
    for outcome in outcomes:
        _settle(*outcome)


def _prepare_committed(character, *, context=None):
    try:
        if _disposable(character):
            return _send_guest(character) if context is None else False
        mode = _backend()
        if mode == "retry":
            return False
        if mode == "inbox" and context is None and not owner_ids(character):
            mode = "nonroster"
        sessions = _eligible_connections(
            character, mode, session=context.session if context is not None else None
        )
        if context is not None and (
            mode != "inbox" or not any(current.account is context.account for current in sessions)
        ):
            return False
        if not sessions:
            return False
        _finish_known(character)
        work = _sqlite_retry(lambda: _prepare_receipts(character, mode))
        if mode == "inbox":
            for receipt_id in work or ():
                _safe_route(character, receipt_id, context=context)
        elif work is not None:
            attempted, delivered = _send(character, work.week, sessions, mode, claim=work)
            _settle(character, work, attempted, delivered)
            return delivered
    except Exception:
        logger.exception("XP notice preparation deferred")
    return False


def prepare_character(character, *, context=None):
    """Defer external delivery until a caller's outer transaction has committed."""
    if connection.in_atomic_block:
        transaction.on_commit(lambda: _prepare_committed(character, context=context), robust=True)
        return False
    return _prepare_committed(character, context=context)


@dataclass
class GuestClaim:
    character: ObjectDB
    week: str
    sessions: tuple[Connection, ...]
    expires: float
    attempting: bool = False
    consumed: bool = False


_guest_claims = {}
_guest_lock = Lock()
_GUEST_LIFETIME = 300


def _plan_guest_cleanup(key, claim):
    from twisted.internet import reactor

    if reactor.running:
        reactor.callFromThread(reactor.callLater, _GUEST_LIFETIME, _expire_guest, key, claim)
    else:
        reactor.callLater(_GUEST_LIFETIME, _expire_guest, key, claim)


def _expire_guest(key, claim):
    live = False
    for current in claim.sessions:
        try:
            if is_live_connection(current):
                live = True
                break
        except Exception:
            continue
    with _guest_lock:
        if _guest_claims.get(key) is not claim:
            return
        if not claim.attempting and (not claim.consumed or not live):
            _guest_claims.pop(key)
            return
    _plan_guest_cleanup(key, claim)


def _guest_attempting(character, claim):
    with _guest_lock:
        return (
            _guest_claims.get((character.pk, claim.week)) is claim
            and claim.attempting
            and claim.expires > monotonic()
        )


def _stage_guest(character, week, sessions):
    # Only the sessions present during the award can ever reuse its transient work.
    key = character.pk, week
    with _guest_lock:
        if key in _guest_claims:
            return
        claim = GuestClaim(character, week, tuple(sessions), monotonic() + _GUEST_LIFETIME)
        _guest_claims[key] = claim
    _plan_guest_cleanup(key, claim)
    _send_guest(character)


def _send_guest(character):
    with _guest_lock:
        for claim in reversed(_guest_claims.values()):
            if (
                claim.character is character
                and not claim.attempting
                and not claim.consumed
                and claim.expires > monotonic()
            ):
                claim.attempting = True
                break
        else:
            return False
    attempted, delivered = _send(character, claim.week, claim.sessions, "guest", claim=claim)
    with _guest_lock:
        claim.attempting = False
        claim.consumed = attempted
    return delivered
