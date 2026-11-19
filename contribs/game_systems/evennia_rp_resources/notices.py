# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Source-owned delivery for committed weekly grants and paid plot awards."""

import logging
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from uuid import uuid4

from django.apps import apps
from django.conf import settings
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone
from evennia.accounts.models import AccountDB
from evennia.objects.models import ObjectDB

from evennia_links.characters import account_ids, playable_accounts
from evennia_links.guests import is_guest
from evennia_links.runtime import get

from .models import PlotPayoutReceipt, ResourceGrant, ResourceNoticeReceipt

SOURCE = "resources"
WEEK_KEY = "last_resource_summary_week"
FULL_KEY = "resource_full_notified"
LIMIT = 100
State = ResourceNoticeReceipt.State
ACKNOWLEDGED = (State.TRANSFERRED, State.SUPPRESSED, State.DELIVERED)
logger = logging.getLogger("evennia")


def lock_character(character_id):
    """Take the common writer gate before reading award or source state."""
    if connection.vendor == "sqlite":
        ResourceGrant.objects.filter(pk__lt=0).update(quantity=F("quantity"))
    return ObjectDB.objects.select_for_update().filter(pk=character_id).first()


def latest_receipt(character):
    """Return the current completed weekly grant, including a zero-gain grant."""
    return (
        ResourceGrant.objects.filter(character_id=character.pk, source="trickle", resource=None)
        .order_by("-pk")
        .first()
    )


def _backend():
    if not apps.is_installed("evennia_notices") or not getattr(settings, "NOTICES_ENABLED", True):
        return "standalone"
    configured = getattr(settings, "LINKS_NOTICE_SOURCES", {})
    if isinstance(configured, dict) and SOURCE not in configured:
        return "standalone"
    try:
        from evennia_links.notices import source_registry

        from .integrations.notices import ResourcesNoticeSource

        if isinstance(source_registry().get(SOURCE), ResourcesNoticeSource):
            return "inbox"
    except Exception:
        logger.warning("Resources Inbox binding could not be resolved")
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


def _rows(character):
    return ResourceNoticeReceipt.objects.filter(character_id=character.pk)


def _stage_week(character, marker, *, inbox_origin):
    if marker is None or marker.character_id != character.pk:
        return None
    existing = _rows(character).filter(weekly=marker).first()
    if existing is not None:
        if inbox_origin and not existing.inbox_origin and existing.state == State.PENDING:
            existing.inbox_origin = True
            existing.save(update_fields=["inbox_origin"])
            return existing
        return None
    if marker.week == _attribute(character, WEEK_KEY):
        return None
    _rows(character).filter(
        weekly_id__lt=marker.pk, inbox_origin=False, state=State.PENDING
    ).update(state=State.SUPERSEDED)
    return _rows(character).create(
        character=character,
        weekly=marker,
        inbox_origin=inbox_origin,
        baseline_full=bool(_attribute(character, FULL_KEY)),
    )


def stage_award(character, *, weekly=None, plot=None, predecessor=None):
    """Save the notice witness under the award's lock, then dispatch after commit."""
    try:
        with transaction.atomic():
            if not get("RP_RESOURCES_REVEALED"):
                return
            if is_guest(character):
                sessions = _eligible_sessions(character, "guest")
                if sessions:
                    row = ResourceNoticeReceipt(character=character, weekly=weekly, plot=plot)
                    if valid_award(row):
                        transaction.on_commit(
                            lambda: _stage_guest(character, row, sessions), robust=True
                        )
                return
            backend = _backend()
            offered = backend != "standalone" and bool(owner_ids(character))
            if weekly is not None:
                if offered:
                    _stage_week(character, predecessor, inbox_origin=True)
                row = _stage_week(character, weekly, inbox_origin=offered)
            else:
                row = ResourceNoticeReceipt(character=character, plot=plot, inbox_origin=offered)
                if not valid_award(row):
                    return
                row.save()
            if row is not None and offered and backend == "inbox":
                transaction.on_commit(lambda: _route_fresh(character, row), robust=True)
    except Exception:
        logger.exception("Resources notice staging deferred for #%s", character.pk)


def valid_award(row):
    """Verify the receipt's witness and its independently recorded owner."""
    if row.weekly_id is not None:
        marker = row.weekly
        return (
            marker.character_id == row.character_id
            and marker.source == "trickle"
            and marker.resource_id is None
            and marker.quantity == 0
            and bool(marker.week)
        )
    if row.plot_id is not None:
        award = row.plot
        return (
            award.character_id == row.character_id
            and award.paid_at is not None
            and not award.skipped
            and bool(award.run.amounts)
        )
    return False


def plots_model():
    """Return the optional authorization model, or defer if it is unavailable."""
    if not apps.is_installed("evennia_plots"):
        return None
    return apps.get_model("evennia_plots", "PlotThread")


def _registered_sessions():
    from evennia.server.sessionhandler import SESSIONS

    return SESSIONS.get_sessions()


@dataclass(frozen=True)
class Connection:
    session: object
    account: AccountDB
    character: ObjectDB


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
    if mode == "nonroster":
        return not owners
    return current.account.pk in owners if owners else mode == "standalone"


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
            current = Connection(session, account, character)
            if _eligible(current, mode, owners):
                candidates.append(current)
        except Exception:
            logger.warning("Resources notice skipped an unavailable session")
    return candidates


def can_view_plot(plot, character, current, *, owner=None):
    """Enforce live plot visibility without borrowing another account's permissions."""
    if plot.privacy != plot.Privacy.PRIVATE:
        return plot.can_view(character)
    if owner is None:
        owner = plot.is_owner(character)
    if owner:
        return plot.can_view(character)
    if current is None or not live_connection(current):
        return False
    account = current.account
    account.refresh_from_db(fields=["is_superuser"])
    _attribute(account, "_quell")
    account.permissions.reset_cache()
    character.permissions.reset_cache()
    character.locks.cache_lock_bypass(character)
    return plot.can_view(character) and live_connection(current)


def grouped_gains(character, weeks):
    """Read positive weekly component grants grouped by their award periods."""
    result = {}
    rows = ResourceGrant.objects.filter(
        character_id=character.pk, source="trickle", week__in=weeks, quantity__gt=0
    ).values_list("week", "quantity", "resource__name")
    for week, quantity, name in rows:
        result.setdefault(week, []).append(f"{quantity} {name}")
    return result


def full_week(marker):
    """Read capacity from the grant snapshot."""
    return "cap" in marker.details and marker.details.get("held", 0) >= marker.details["cap"]


def _latest_checkpoint(character, *, before=None):
    rows = _rows(character).filter(weekly_id__isnull=False, state__in=ACKNOWLEDGED)
    if before is not None:
        rows = rows.filter(weekly_id__lt=before)
    return rows.select_related("weekly").order_by("-weekly_id").first()


def _weekly_presentation(character, row):
    marker = row.weekly
    previous = _latest_checkpoint(character, before=marker.pk)
    already_full = full_week(previous.weekly) if previous else row.baseline_full
    full = full_week(marker)
    quiet = full and already_full and not grouped_gains(character, [marker.week])
    return full and not already_full, quiet


def award_text(row, *, gains=(), plot=None, inbox=False):
    """Render the snapshot with a live-authorized plot title where permitted."""
    if row.weekly_id is not None:
        marker = row.weekly
        full = full_week(marker)
        text = "This week you gathered: " + (", ".join(gains) or "none") + "."
        if row.full_warning:
            text += " Your stores are full."
        elif marker.details.get("tapered") and not full:
            text += " Your stores are nearing capacity."
    else:
        private = plot.privacy == plot.Privacy.PRIVATE
        heading = "Private plot award" if private and inbox else f"Plot award ({plot.name})"
        amounts = ", ".join(f"{quantity} {key}" for key, quantity in row.plot.run.amounts.items())
        text = f"{heading}: {amounts}."
    return text + " Use +resources to view your stores."


def _repair_checkpoints(character):
    """Repair old markers without making an acknowledged notice deliverable again."""
    rows = _rows(character).filter(repair_checkpoint=True)
    if not rows.exists():
        return
    try:
        with transaction.atomic():
            if rows.filter(weekly_id__isnull=False).exists():
                latest = _latest_checkpoint(character)
                character.attributes.reset_cache()
                character.attributes.add(WEEK_KEY, latest.weekly.week)
                character.attributes.add(FULL_KEY, full_week(latest.weekly))
            for row in rows.filter(plot_id__isnull=False, state=State.DELIVERED):
                PlotPayoutReceipt.objects.filter(pk=row.plot_id, notified_at=None).update(
                    notified_at=row.attempted_at
                )
            rows.update(repair_checkpoint=False)
    except Exception:
        logger.warning("Resources notice compatibility marker update deferred")


def _acknowledge(row, state):
    row.state = state
    row.repair_checkpoint = row.weekly_id is not None or state == State.DELIVERED
    row.save(update_fields=["state", "full_warning", "repair_checkpoint"])
    _repair_checkpoints(row.character)


def _pending(character, receipt_id):
    return (
        _rows(character)
        .filter(pk=receipt_id, state=State.PENDING)
        .select_related("weekly__character", "plot__run")
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
        or not get("RP_RESOURCES_REVEALED")
        or _backend() != "inbox"
        or not owner_ids(character)
        or is_guest(character)
        or (context is not None and not _eligible_sessions(character, "inbox", context=context))
    ):
        return
    row = _pending(character, receipt_id)
    if row is None or not valid_award(row):
        return
    if not row.inbox_origin:
        row.inbox_origin = True
        row.save(update_fields=["inbox_origin"])
    if row.weekly_id is not None:
        if _prior_pending_weeks(character, row.weekly_id).exists():
            return
        row.full_warning, quiet = _weekly_presentation(character, row)
        if quiet:
            if get("RP_RESOURCES_REVEALED"):
                _acknowledge(row, State.SUPPRESSED)
            return
        row.save(update_fields=["full_warning"])
    elif plots_model() is None:
        return
    event = event_for(row)
    kwargs = dict(source=SOURCE, event=event, context=context, fallback=_fallback_pending)
    result = (
        notify(character, **kwargs)
        if fresh
        else transfer(character, transfer_id=event.event_id, **kwargs)
    )
    if not get("RP_RESOURCES_REVEALED"):
        # Inbox may have durably handled preference-off before checking visibility.
        transaction.set_rollback(True)
        return
    if result.receipt and result.status in {"retained", "duplicate", "suppressed"}:
        _acknowledge(row, State.SUPPRESSED if result.status == "suppressed" else State.TRANSFERRED)


def _prior_pending_weeks(character, weekly_id):
    return (
        _rows(character)
        .filter(
            weekly_id__lt=weekly_id,
            state=State.PENDING,
            weekly__character_id=character.pk,
            weekly__source="trickle",
            weekly__resource=None,
            weekly__quantity=0,
        )
        .exclude(weekly__week="")
    )


def _route_fresh(character, row):
    if row.weekly_id is not None:
        prior = list(
            _prior_pending_weeks(character, row.weekly_id)
            .order_by("weekly_id")
            .values_list("pk", flat=True)[:LIMIT]
        )
        for receipt_id in prior:
            _safe_route(character, receipt_id)
    _safe_route(character, row.pk, fresh=True)


def _safe_route(character, receipt_id, *, fresh=False, context=None):
    try:
        _route(character, receipt_id, fresh=fresh, context=context)
    except Exception:
        logger.exception("Resources notice routing deferred for #%s", character.pk)


@transaction.atomic
def _prepare(character, mode, kind):
    if lock_character(character.pk) is None or not get("RP_RESOURCES_REVEALED"):
        return []
    expected = "inbox" if mode == "nonroster" else mode
    if _backend() != expected or is_guest(character):
        return []
    _repair_checkpoints(character)
    rows = _rows(character)
    marker = None
    if kind in (None, "weekly"):
        marker = latest_receipt(character)
        _stage_week(character, marker, inbox_origin=mode == "inbox")
        if marker is not None:
            rows.filter(weekly_id__lt=marker.pk, inbox_origin=False, state=State.PENDING).update(
                state=State.SUPERSEDED
            )
    if kind in (None, "plot") and plots_model() is not None:
        legacy = (
            PlotPayoutReceipt.objects.filter(
                character_id=character.pk,
                skipped=False,
                paid_at__isnull=False,
                notified_at__isnull=True,
                notice_receipt__isnull=True,
            )
            .exclude(run__amounts={})
            .order_by("pk")[:LIMIT]
        )
        ResourceNoticeReceipt.objects.bulk_create(
            [ResourceNoticeReceipt(character=character, plot=award) for award in legacy]
        )
    pending = rows.filter(state=State.PENDING)
    work = []
    if marker is not None:
        weeks = pending.filter(weekly_id__isnull=False)
        if mode != "inbox":
            weeks = weeks.filter(weekly_id=marker.pk)
        work.extend(weeks.order_by("weekly_id").values_list("pk", flat=True)[:LIMIT])
    if kind in (None, "plot"):
        work.extend(
            pending.filter(plot_id__isnull=False)
            .order_by(F("attempted_at").asc(nulls_first=True), "plot_id")
            .values_list("pk", flat=True)[:LIMIT]
        )
        # Rotate temporarily inaccessible and failed plot work through the bounded sweep.
        rows.filter(pk__in=work, plot_id__isnull=False).update(attempted_at=timezone.now())
    return work


def _standalone_text(row, current):
    if row.weekly_id is not None:
        return award_text(
            row, gains=grouped_gains(current.character, [row.weekly.week]).get(row.weekly.week, ())
        )
    plot = _standalone_plot(row, current)
    return award_text(row, plot=plot) if plot is not None else None


def _standalone_plot(row, current):
    model = plots_model()
    plot = model.objects.filter(pk=row.plot.run.thread_id).first() if model else None
    if plot is not None and can_view_plot(plot, current.character, current):
        return plot


def _current_award(row, character):
    if not valid_award(row):
        return False
    return row.weekly_id is None or row.weekly_id == getattr(latest_receipt(character), "pk", None)


@transaction.atomic
def _claim(character, receipt_id, mode):
    expected = "inbox" if mode == "nonroster" else "standalone"
    if (
        lock_character(character.pk) is None
        or not get("RP_RESOURCES_REVEALED")
        or _backend() != expected
    ):
        return
    row = _pending(character, receipt_id)
    if row is None or not _current_award(row, character):
        return
    if row.weekly_id is not None:
        row.full_warning, quiet = _weekly_presentation(character, row)
        if quiet:
            if _eligible_sessions(character, mode) and get("RP_RESOURCES_REVEALED"):
                _acknowledge(row, State.SUPPRESSED)
            return
    row.state = State.ATTEMPTING
    row.attempt = uuid4()
    row.attempted_at = timezone.now()
    row.save(update_fields=["state", "attempt", "attempted_at", "full_warning"])
    return row


def _claim_query(row):
    return ResourceNoticeReceipt.objects.filter(
        pk=row.pk, attempt=row.attempt, state=State.ATTEMPTING
    )


def _transport_allowed(row, current, mode):
    character = current.character
    if (
        not get("RP_RESOURCES_REVEALED")
        or not _eligible(current, mode, owner_ids(character))
        or not _current_award(row, character)
    ):
        return False
    if mode == "guest":
        return True
    expected = "inbox" if mode == "nonroster" else "standalone"
    return _backend() == expected and _claim_query(row).exists()


def _send(row, sessions, mode):
    attempted = delivered = False
    for current in sessions:
        try:
            if not _transport_allowed(row, current, mode):
                continue
            writer = current.character.msg
            if not callable(writer):
                continue
            text = _standalone_text(row, current)
            if not text or not _transport_allowed(row, current, mode):
                continue
            if row.plot_id is not None:
                plot = _standalone_plot(row, current)
                if plot is None or text != award_text(row, plot=plot):
                    continue
            attempted = True
            writer(text, session=current.session)
            delivered = True
        except Exception:
            logger.warning("Resources notice did not complete on one session")
    return attempted, delivered


@transaction.atomic
def _finalize(row, attempted, delivered):
    character = lock_character(row.character_id)
    if character is None:
        return
    state = State.DELIVERED if delivered else (State.UNCERTAIN if attempted else State.PENDING)
    updates = {"state": state, "attempt": None, "repair_checkpoint": delivered}
    if delivered:
        updates["attempted_at"] = timezone.now()
    if _claim_query(row).update(**updates) and delivered:
        _repair_checkpoints(character)


_waiting = {}
_waiting_lock = Lock()


def _settle(row, attempted, delivered):
    try:
        _finalize(row, attempted, delivered)
    except Exception:
        with _waiting_lock:
            _waiting[row.attempt] = (row, attempted, delivered)
        logger.warning("Resources notice finalization deferred")
    else:
        with _waiting_lock:
            _waiting.pop(row.attempt, None)


def _finish_known(character):
    with _waiting_lock:
        outcomes = [item for item in _waiting.values() if item[0].character_id == character.pk][
            :LIMIT
        ]
    for outcome in outcomes:
        _settle(*outcome)


@dataclass
class GuestClaim:
    row: ResourceNoticeReceipt
    sessions: tuple[Connection, ...]
    expires: float
    attempting: bool = False
    consumed: bool = False


_guests = {}
_guest_lock = Lock()
_GUEST_LIFETIME = 300


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

    key = character.pk, row.weekly_id, row.plot_id
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


def _send_guest(character, kind=None):
    with _guest_lock:
        claims = [
            claim
            for claim in _guests.values()
            if claim.row.character_id == character.pk
            and not claim.attempting
            and not claim.consumed
            and claim.expires > monotonic()
            and (kind is None or (kind == "weekly") == (claim.row.weekly_id is not None))
        ][:LIMIT]
        for claim in claims:
            claim.attempting = True
    confirmed = False
    for claim in claims:
        row = claim.row
        if row.weekly_id is not None:
            row.full_warning = full_week(row.weekly)
        attempted, delivered = _send(row, claim.sessions, "guest")
        with _guest_lock:
            claim.attempting = False
            claim.consumed = attempted
        confirmed |= delivered
    return confirmed


def _prepare_committed(character, *, context=None, kind=None):
    try:
        if not get("RP_RESOURCES_REVEALED"):
            return False
        if is_guest(character):
            if context is None and not owner_ids(character):
                return _send_guest(character, kind)
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
        work = _prepare(character, mode, kind)
        if mode == "inbox":
            for receipt_id in work:
                _safe_route(character, receipt_id, context=context)
            return False
        confirmed = False
        for receipt_id in work:
            try:
                row = _claim(character, receipt_id, mode)
                if row is not None:
                    attempted, delivered = _send(row, sessions, mode)
                    _settle(row, attempted, delivered)
                    confirmed |= delivered
            except Exception:
                logger.exception("Resources standalone notice deferred for #%s", character.pk)
        return confirmed
    except Exception:
        logger.exception("Resources notice preparation deferred for #%s", character.pk)
    return False


def prepare_character(character, *, context=None, kind=None):
    """Prepare committed work and report whether a standalone write confirmed."""
    if connection.in_atomic_block:
        transaction.on_commit(
            lambda: _prepare_committed(character, context=context, kind=kind), robust=True
        )
        return False
    return _prepare_committed(character, context=context, kind=kind)
