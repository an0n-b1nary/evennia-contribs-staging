# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Source-owned delivery for committed weekly income and stipends."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from threading import Lock
from time import monotonic
from uuid import uuid4

from django.apps import apps
from django.conf import settings
from django.db import connection, transaction
from django.db.models import F, Q
from django.utils import timezone
from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB

from evennia_links.characters import account_ids, playable_accounts
from evennia_links.guests import is_guest
from evennia_links.runtime import get

from . import conf
from .models import EconomyNoticeReceipt, Purse, StipendPayment, UBIPayment

SOURCE = "economy"
MARKER_KEY = "last_economy_summary"
FULL_KEY = "economy_full_notified"
LIMIT = 100
# After this long, a claim that no live process still holds for settlement is stale.
_ATTEMPT_LIFETIME = 300
STIPEND_KINDS = ("starting", "reveal")
State = EconomyNoticeReceipt.State
ACKNOWLEDGED = (State.TRANSFERRED, State.SUPPRESSED, State.DELIVERED)
logger = logging.getLogger("evennia")


def _revealed():
    return get("RP_ECONOMY_REVEALED")


def reserve_writer():
    """Take SQLite's writer lock before any read that decides a payment or notice."""
    if connection.vendor == "sqlite":
        Purse.objects.filter(pk__lt=0).update(balance=F("balance"))


def lock_character(character_id):
    """Take the common writer gate before reading payment or source state."""
    reserve_writer()
    return ObjectDB.objects.select_for_update().filter(pk=character_id).first()


def latest_income(character):
    """Return the character's newest weekly income payment, including a zero one."""
    return UBIPayment.objects.filter(character_id=character.pk).order_by("-pk").first()


def full_payment(ubi):
    """A capped week: nothing was paid because the purse is at its income cap."""
    return ubi.amount == 0 and bool(ubi.details.get("tapered"))


def _backend():
    if not apps.is_installed("evennia_notices") or not getattr(settings, "NOTICES_ENABLED", True):
        return "standalone"
    configured = getattr(settings, "LINKS_NOTICE_SOURCES", {})
    if isinstance(configured, dict) and SOURCE not in configured:
        return "standalone"
    try:
        from evennia_links.notices import source_registry

        from .integrations.notices import EconomyNoticeSource

        if isinstance(source_registry().get(SOURCE), EconomyNoticeSource):
            return "inbox"
    except Exception:
        logger.warning("Economy Inbox binding could not be resolved")
    return "retry"


def owner_ids(character):
    """Return current ordinary accounts with this character on their stored roster."""
    return {
        account.pk
        for account in AccountDB.objects.in_bulk(account_ids(character)).values()
        if not is_guest(account)
    }


def _attribute(character, key):
    character.attributes.reset_cache()
    attribute = character.attributes.get(key, return_obj=True)
    if attribute is not None:
        attribute.refresh_from_db(fields=["db_value"])
        return attribute.value


def _ids(value):
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _valid_marker(value):
    if not _ids(value) or len(value) != 2:
        return False
    latest, stipends = value[0], value[1]
    if latest is not None and not (type(latest) is int and latest > 0):
        return False
    return _ids(stipends) and all(type(pk) is int and pk > 0 for pk in stipends)


def legacy_marker(character):
    """Read the 0.4 summary marker as (latest seen income pk, seen stipend pks)."""
    value = _attribute(character, MARKER_KEY)
    if value is None:
        return None, frozenset()
    if not _valid_marker(value):
        logger.warning("Economy summary marker unreadable; treating as never summarized")
        return None, frozenset()
    return value[0], frozenset(value[1])


def legacy_full(character):
    """Whether the 0.4 marker says the last summarized week was capped."""
    return _attribute(character, FULL_KEY) is True


def _rows(character):
    return EconomyNoticeReceipt.objects.filter(character_id=character.pk)


def _stage_week(character, ubi, *, inbox_origin, legacy=None):
    if ubi is None or ubi.character_id != character.pk:
        return None
    existing = _rows(character).filter(ubi=ubi).first()
    if existing is not None:
        if inbox_origin and not existing.inbox_origin and existing.state == State.PENDING:
            existing.inbox_origin = True
            existing.save(update_fields=["inbox_origin"])
            return existing
        return None
    seen, _ = legacy if legacy is not None else legacy_marker(character)
    if seen is not None and ubi.pk <= seen:
        return None
    _rows(character).filter(ubi_id__lt=ubi.pk, inbox_origin=False, state=State.PENDING).update(
        state=State.SUPERSEDED
    )
    return _rows(character).create(
        character=character,
        ubi=ubi,
        inbox_origin=inbox_origin,
        baseline_full=legacy_full(character),
    )


def stage_payment(character, *, ubi=None, stipend=None, predecessor=None):
    """Save the notice witness under the payment's lock, then dispatch after commit."""
    try:
        with transaction.atomic():
            if not _revealed():
                return
            if is_guest(character) and not owner_ids(character):
                _stage_guest_payment(character, ubi=ubi, stipend=stipend)
                return
            backend = _backend()
            offered = backend != "standalone" and bool(owner_ids(character))
            if ubi is not None:
                if offered:
                    _stage_week(character, predecessor, inbox_origin=True)
                row = _stage_week(character, ubi, inbox_origin=offered)
            else:
                row = EconomyNoticeReceipt(
                    character=character, stipend=stipend, inbox_origin=offered
                )
                if not valid_payment(row):
                    return
                row.save()
            if row is not None and offered and backend == "inbox":
                transaction.on_commit(lambda: _route_fresh(character, row), robust=True)
    except Exception:
        logger.exception("Economy notice staging deferred for #%s", character.pk)


def valid_payment(row):
    """Verify the receipt's payment and its independently recorded owner."""
    if row.ubi_id is not None:
        return row.ubi.character_id == row.character_id
    if row.stipend_id is not None:
        stipend = row.stipend
        return stipend.character_id == row.character_id and stipend.kind in STIPEND_KINDS
    return False


def _registered_sessions():
    from evennia.server.sessionhandler import SESSIONS

    return SESSIONS.get_sessions()


@dataclass(frozen=True)
class Connection:
    session: object
    account: AccountDB
    character: ObjectDB
    roster_member: bool


def live_connection(current):
    """Require the exact registered session and its current account and puppet."""
    session, account, character = current.session, current.account, current.character
    return (
        any(item is session for item in _registered_sessions())
        and session.logged_in
        and session.get_account() is account
        and session.get_puppet() is character
        and character.account is account
        and ObjectDB.objects.filter(pk=character.pk, db_account=account).exists()
    )


def _eligible(current, mode, owners):
    if not live_connection(current):
        return False
    if mode == "guest":
        return (
            not owners
            and is_guest(current.account)
            and any(
                current.character in roster
                for _, roster in playable_accounts(AccountDB.objects.filter(pk=current.account.pk))
            )
        )
    if is_guest(current.account) or is_guest(current.character):
        return False
    if current.roster_member:
        return mode != "nonroster" and current.account.pk in owners
    return not owners and mode in ("standalone", "nonroster")


def _eligible_sessions(character, mode, *, context=None):
    owners = owner_ids(character)
    candidates = []
    for session in _registered_sessions():
        try:
            if context is not None and session is not context.session:
                continue
            if not session.logged_in or session.get_puppet() is not character:
                continue
            account = session.get_account()
            if not isinstance(account, AccountDB) or not account.pk:
                continue
            if context is not None and account is not context.account:
                continue
            current = Connection(session, account, character, account.pk in owners)
            if _eligible(current, mode, owners):
                candidates.append(current)
        except Exception:
            logger.warning("Economy notice skipped an unavailable session")
    return candidates


def _latest_checkpoint(character, *, before=None):
    rows = _rows(character).filter(ubi_id__isnull=False, state__in=ACKNOWLEDGED)
    if before is not None:
        rows = rows.filter(ubi_id__lt=before)
    return rows.select_related("ubi").order_by("-ubi_id").first()


def _weekly_presentation(character, row):
    """Return (cap warning, quiet): a capped week is told once, not weekly."""
    previous = _latest_checkpoint(character, before=row.ubi_id)
    already_full = full_payment(previous.ubi) if previous else row.baseline_full
    full = full_payment(row.ubi)
    return full and not already_full, full and already_full


def _inbox_quiet(character, row):
    """Inbox and guest presentation: zero payments that aren't a cap notice stay quiet."""
    if row.stipend_id is not None:
        return False, row.stipend.amount == 0
    if row.ubi.amount == 0 and not full_payment(row.ubi):
        return False, True
    return _weekly_presentation(character, row)


def payment_text(row):
    """Per-payment wording for the Inbox and guest connections."""
    if row.ubi_id is not None:
        ubi = row.ubi
        text = f"Weekly income: {conf.currency(ubi.amount)}."
        if row.full_warning:
            text += " Your purse is at its income cap."
        elif ubi.details.get("tapered") and not full_payment(ubi):
            text += " Your purse is near its income cap."
        return text + " See +balance."
    return f"Stipend received: {conf.currency(row.stipend.amount)}. See +balance."


def _repair_checkpoints(character):
    """Keep the 0.4 marker current without making an acknowledged payment deliverable again."""
    rows = _rows(character).filter(repair_checkpoint=True)
    if not rows.exists():
        return
    try:
        with transaction.atomic():
            seen_ubi, seen_stipends = legacy_marker(character)
            acknowledged = _rows(character).filter(state__in=ACKNOWLEDGED)
            latest = _latest_checkpoint(character)
            latest_id = seen_ubi
            if latest is not None and (seen_ubi is None or latest.ubi_id >= seen_ubi):
                latest_id = latest.ubi_id
            stipends = set(
                StipendPayment.objects.filter(
                    character_id=character.pk, pk__in=seen_stipends
                ).values_list("pk", flat=True)
            ) | set(
                acknowledged.filter(stipend_id__isnull=False).values_list("stipend_id", flat=True)
            )
            character.attributes.reset_cache()
            character.attributes.add(MARKER_KEY, [latest_id, sorted(stipends)])
            if latest is not None and latest.ubi_id == latest_id:
                character.attributes.add(FULL_KEY, full_payment(latest.ubi))
            rows.update(repair_checkpoint=False)
    except Exception:
        logger.warning("Economy notice compatibility marker update deferred")


def _acknowledge(row, state):
    row.state = state
    row.repair_checkpoint = True
    row.save(update_fields=["state", "full_warning", "repair_checkpoint"])
    _repair_checkpoints(row.character)


def _pending(character, receipt_id):
    return (
        _rows(character)
        .filter(pk=receipt_id, state=State.PENDING)
        .select_related("ubi", "stipend", "character")
        .first()
    )


def _fallback_pending(*args):
    from evennia_links.notices import RouteResult

    return RouteResult("fallback_pending")


@transaction.atomic
def _route(character, receipt_id, *, fresh, context):
    from evennia_links.notices import notify, transfer

    from .integrations.notices import event_for

    if (
        lock_character(character.pk) is None
        or not _revealed()
        or _backend() != "inbox"
        or not owner_ids(character)
        or is_guest(character)
        or (context is not None and not _eligible_sessions(character, "inbox", context=context))
    ):
        return
    row = _pending(character, receipt_id)
    if row is None or not valid_payment(row):
        return
    if not row.inbox_origin:
        row.inbox_origin = True
        row.save(update_fields=["inbox_origin"])
    if row.ubi_id is not None and _prior_pending_weeks(character, row.ubi_id).exists():
        return
    row.full_warning, quiet = _inbox_quiet(character, row)
    if quiet:
        if _revealed():
            _acknowledge(row, State.SUPPRESSED)
        return
    row.save(update_fields=["full_warning"])
    event = event_for(row)
    kwargs = dict(source=SOURCE, event=event, context=context, fallback=_fallback_pending)
    result = (
        notify(character, **kwargs)
        if fresh
        else transfer(character, transfer_id=event.event_id, **kwargs)
    )
    if not _revealed():
        # Inbox may have durably handled preference-off before checking visibility.
        transaction.set_rollback(True)
        return
    if result.receipt and result.status in {"retained", "duplicate", "suppressed"}:
        _acknowledge(row, State.SUPPRESSED if result.status == "suppressed" else State.TRANSFERRED)


def _prior_pending_weeks(character, ubi_id):
    return _rows(character).filter(
        ubi_id__lt=ubi_id, state=State.PENDING, ubi__character_id=character.pk
    )


def _route_fresh(character, row):
    if row.ubi_id is not None:
        prior = list(
            _prior_pending_weeks(character, row.ubi_id)
            .order_by("ubi_id")
            .values_list("pk", flat=True)[:LIMIT]
        )
        for receipt_id in prior:
            _safe_route(character, receipt_id)
    _safe_route(character, row.pk, fresh=True)


def _safe_route(character, receipt_id, *, fresh=False, context=None):
    try:
        _route(character, receipt_id, fresh=fresh, context=context)
    except Exception:
        logger.exception("Economy notice routing deferred for #%s", character.pk)


def _import(character, *, inbox_origin):
    """Stage the latest unseen week and every unseen stipend that has no receipt yet."""
    legacy = legacy_marker(character)
    latest = latest_income(character)
    _stage_week(character, latest, inbox_origin=inbox_origin, legacy=legacy)
    if latest is not None:
        _rows(character).filter(
            ubi_id__lt=latest.pk, inbox_origin=False, state=State.PENDING
        ).update(state=State.SUPERSEDED)
    unseen = (
        StipendPayment.objects.filter(
            character_id=character.pk, kind__in=STIPEND_KINDS, notice_receipt__isnull=True
        )
        .exclude(pk__in=legacy[1])
        .order_by("pk")[:LIMIT]
    )
    EconomyNoticeReceipt.objects.bulk_create(
        [
            EconomyNoticeReceipt(character=character, stipend=stipend, inbox_origin=inbox_origin)
            for stipend in unseen
        ]
    )
    return latest


@transaction.atomic
def _prepare(character):
    """Import committed payments for the Inbox and list the pending receipts to route."""
    if (
        lock_character(character.pk) is None
        or not _revealed()
        or _backend() != "inbox"
        or is_guest(character)
    ):
        return []
    _repair_checkpoints(character)
    _import(character, inbox_origin=True)
    pending = _rows(character).filter(state=State.PENDING)
    work = list(
        pending.filter(ubi_id__isnull=False).order_by("ubi_id").values_list("pk", flat=True)[:LIMIT]
    )
    work.extend(
        pending.filter(stipend_id__isnull=False)
        .order_by("stipend_id")
        .values_list("pk", flat=True)[:LIMIT]
    )
    return work


@dataclass(frozen=True)
class LineClaim:
    """One standalone combined line covering the latest week and pending stipends."""

    character_id: int
    receipt_ids: frozenset
    attempt: object
    latest_ubi_id: int | None
    stipend_ids: frozenset
    full_warning: bool


def _expected(mode):
    return "inbox" if mode == "nonroster" else "standalone"


@transaction.atomic
def _claim_line(character, mode):
    if (
        lock_character(character.pk) is None
        or not _revealed()
        or _backend() != _expected(mode)
        or is_guest(character)
    ):
        return None
    _repair_checkpoints(character)
    latest = _import(character, inbox_origin=False)
    rows = _rows(character).filter(state=State.PENDING)
    week = None
    if latest is not None:
        week = rows.filter(ubi=latest).select_related("ubi").first()
    stipends = list(
        rows.filter(stipend_id__isnull=False)
        .select_related("stipend")
        .order_by("stipend_id")[:LIMIT]
    )
    stipends = [row for row in stipends if valid_payment(row)]
    full_warning = False
    if week is not None:
        full_warning, quiet = _weekly_presentation(character, week)
        if quiet and not stipends:
            if _eligible_sessions(character, mode) and _revealed():
                week.full_warning = False
                _acknowledge(week, State.SUPPRESSED)
            return None
    claimed = ([week] if week is not None else []) + stipends
    if not claimed:
        return None
    attempt = uuid4()
    EconomyNoticeReceipt.objects.filter(pk__in=[row.pk for row in claimed]).update(
        state=State.ATTEMPTING, attempt=attempt, attempted_at=timezone.now()
    )
    if week is not None:
        EconomyNoticeReceipt.objects.filter(pk=week.pk).update(full_warning=full_warning)
    return LineClaim(
        character.pk,
        frozenset(row.pk for row in claimed),
        attempt,
        latest.pk if latest is not None else None,
        frozenset(
            StipendPayment.objects.filter(character_id=character.pk).values_list("pk", flat=True)
        ),
        full_warning,
    )


def line_text(character, claim):
    """The 0.4 combined first-puppet line, read from current payments."""
    latest = latest_income(character)
    text = (
        f"Your latest income: {conf.currency(latest.amount)}."
        if latest is not None
        else "Your purse is ready."
    )
    stipends = list(
        StipendPayment.objects.filter(character_id=character.pk).values_list("amount", flat=True)
    )
    if stipends:
        text += f" Stipends received: {conf.currency(sum(stipends))}."
    if claim.full_warning:
        text += " Your purse is at its income cap."
    elif latest is not None and latest.details.get("tapered") and not full_payment(latest):
        text += " Your purse is near its income cap."
    return text + " See +balance."


def _claim_query(claim):
    return EconomyNoticeReceipt.objects.filter(attempt=claim.attempt, state=State.ATTEMPTING)


def _transport_line(claim, current, mode):
    """Require the claim, its payments and the connection's scope to be unchanged."""
    character = current.character
    if (
        not _revealed()
        or not _eligible(current, mode, owner_ids(character))
        or _backend() != _expected(mode)
        or character.pk != claim.character_id
    ):
        return False
    claimed = list(
        _claim_query(claim).filter(pk__in=claim.receipt_ids).select_related("ubi", "stipend")
    )
    if len(claimed) != len(claim.receipt_ids) or not all(
        row.character_id == character.pk and valid_payment(row) for row in claimed
    ):
        return False
    latest = latest_income(character)
    if (latest.pk if latest is not None else None) != claim.latest_ubi_id:
        return False
    if latest is not None and latest.pk not in {row.ubi_id for row in claimed}:
        with _waiting_lock:
            waiting = {
                attempt
                for attempt, item in _waiting.items()
                if item[0].character_id == character.pk
            }
        in_flight = Q(attempted_at__gte=timezone.now() - timedelta(seconds=_ATTEMPT_LIFETIME)) | Q(
            attempt__in=waiting
        )
        busy = (
            _rows(character)
            .filter(ubi_id=latest.pk)
            .filter(
                Q(state=State.PENDING)
                | (Q(state=State.ATTEMPTING) & ~Q(attempt=claim.attempt) & in_flight)
            )
        )
        if busy.exists():
            return False
    current_stipends = frozenset(
        StipendPayment.objects.filter(character_id=character.pk).values_list("pk", flat=True)
    )
    return current_stipends == claim.stipend_ids


def _send_line(claim, sessions, mode):
    attempted = delivered = False
    for current in sessions:
        try:
            if not _transport_line(claim, current, mode):
                continue
            writer = current.character.msg
            if not callable(writer):
                continue
            text = line_text(current.character, claim)
            if not _transport_line(claim, current, mode) or not live_connection(current):
                continue
            attempted = True
            writer(text, session=current.session)
            delivered = True
        except Exception:
            logger.warning("Economy notice did not complete on one session")
    return attempted, delivered


@transaction.atomic
def _finalize(claim, attempted, delivered):
    character = lock_character(claim.character_id)
    if character is None:
        return
    state = State.DELIVERED if delivered else (State.UNCERTAIN if attempted else State.PENDING)
    updates = {"state": state, "attempt": None, "repair_checkpoint": delivered}
    if delivered:
        updates["attempted_at"] = timezone.now()
    if _claim_query(claim).update(**updates) and delivered:
        _repair_checkpoints(character)


_waiting = {}
_waiting_lock = Lock()


def _settle(claim, attempted, delivered):
    try:
        _finalize(claim, attempted, delivered)
    except Exception:
        with _waiting_lock:
            _waiting[claim.attempt] = (claim, attempted, delivered)
        logger.warning("Economy notice finalization deferred")
    else:
        with _waiting_lock:
            _waiting.pop(claim.attempt, None)


def _finish_known(character):
    with _waiting_lock:
        outcomes = [item for item in _waiting.values() if item[0].character_id == character.pk][
            :LIMIT
        ]
    for outcome in outcomes:
        _settle(*outcome)


@dataclass
class GuestClaim:
    row: EconomyNoticeReceipt
    sessions: tuple[Connection, ...]
    expires: float
    attempting: bool = False
    consumed: bool = False


_guests = {}
_guest_lock = Lock()
_GUEST_LIFETIME = 300


def _stage_guest_payment(character, *, ubi=None, stipend=None):
    """Connected-only guest lines: nothing about a disposable guest is saved."""
    sessions = _eligible_sessions(character, "guest")
    if not sessions:
        return
    row = EconomyNoticeReceipt(character=character, ubi=ubi, stipend=stipend)
    if not valid_payment(row):
        return
    _, quiet = _inbox_quiet(character, row)
    if quiet:
        return
    if ubi is not None:
        row.full_warning = full_payment(ubi)  # guests have no checkpoint history
    transaction.on_commit(lambda: _stage_guest(character, row, sessions), robust=True)


def _guest_key(row):
    if row.ubi_id is not None:
        return row.character_id, "income", row.ubi_id
    return row.character_id, "stipend", row.stipend_id


def _expire_guest(key, claim):
    from twisted.internet import reactor

    live = False
    for current in claim.sessions:
        try:
            if live_connection(current):
                live = True
                break
        except Exception:
            continue
    with _guest_lock:
        if _guests.get(key) is not claim:
            return
        if not claim.attempting and (not claim.consumed or not live):
            _guests.pop(key)
            return
    reactor.callLater(_GUEST_LIFETIME, _expire_guest, key, claim)


def _stage_guest(character, row, sessions):
    from twisted.internet import reactor

    key = _guest_key(row)
    with _guest_lock:
        if key in _guests:
            return
        claim = GuestClaim(row, tuple(sessions), monotonic() + _GUEST_LIFETIME)
        _guests[key] = claim
    if reactor.running:
        reactor.callFromThread(reactor.callLater, _GUEST_LIFETIME, _expire_guest, key, claim)
    else:
        reactor.callLater(_GUEST_LIFETIME, _expire_guest, key, claim)
    _send_guest(character)


def _transport_payment(row, current):
    """Reload the guest's payment and require the connection's original scope."""
    character = current.character
    if not _revealed() or not _eligible(current, "guest", owner_ids(character)):
        return None
    fresh = EconomyNoticeReceipt(character_id=row.character_id, full_warning=row.full_warning)
    if row.ubi_id is not None:
        fresh.ubi = UBIPayment.objects.filter(pk=row.ubi_id).first()
    else:
        fresh.stipend = StipendPayment.objects.filter(pk=row.stipend_id).first()
    if (
        (fresh.ubi_id is not None or fresh.stipend_id is not None)
        and fresh.character_id == character.pk
        and valid_payment(fresh)
    ):
        return fresh
    return None


def _send_payment(row, sessions):
    attempted = delivered = False
    for current in sessions:
        try:
            fresh = _transport_payment(row, current)
            if fresh is None:
                continue
            writer = current.character.msg
            if not callable(writer):
                continue
            text = payment_text(fresh)
            if _transport_payment(row, current) is None or not live_connection(current):
                continue
            attempted = True
            writer(text, session=current.session)
            delivered = True
        except Exception:
            logger.warning("Economy notice did not complete on one session")
    return attempted, delivered


def _send_guest(character):
    with _guest_lock:
        claims = [
            claim
            for claim in _guests.values()
            if claim.row.character_id == character.pk
            and not claim.attempting
            and not claim.consumed
            and claim.expires > monotonic()
        ][:LIMIT]
        for claim in claims:
            claim.attempting = True
    confirmed = False
    for claim in claims:
        attempted, delivered = _send_payment(claim.row, claim.sessions)
        with _guest_lock:
            claim.attempting = False
            claim.consumed = attempted
        confirmed |= delivered
    return confirmed


def _prepare_committed(character, *, context=None):
    try:
        if not _revealed():
            return False
        if is_guest(character):
            if context is None and not owner_ids(character):
                return _send_guest(character)
            return False
        mode = _backend()
        if mode == "retry":
            return False
        if context is None and mode == "inbox":
            if owner_ids(character):
                return False  # Inbox prepares from its explicit puppet context.
            mode = "nonroster"
        if context is not None and mode != "inbox":
            return False
        sessions = _eligible_sessions(character, mode, context=context)
        if not sessions:
            return False
        _finish_known(character)
        if mode == "inbox":
            for receipt_id in _prepare(character):
                _safe_route(character, receipt_id, context=context)
            return False
        claim = _claim_line(character, mode)
        if claim is None:
            return False
        attempted, delivered = _send_line(claim, sessions, mode)
        _settle(claim, attempted, delivered)
        return delivered
    except Exception:
        logger.exception("Economy notice preparation deferred for #%s", character.pk)
    return False


def prepare_character(character, *, context=None):
    """Prepare committed payments and report whether a standalone write confirmed."""
    if connection.in_atomic_block:
        transaction.on_commit(lambda: _prepare_committed(character, context=context), robust=True)
        return False
    return _prepare_committed(character, context=context)
