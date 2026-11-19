# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Dispatch plot notices from committed service transitions."""

import logging
from dataclasses import dataclass
from threading import Lock
from time import monotonic, sleep
from uuid import uuid4

from django.apps import apps
from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.db.models import F
from django.utils import timezone
from evennia.accounts.models import AccountDB
from twisted.internet import reactor

from evennia_links.characters import account_ids, playable_accounts
from evennia_links.guests import is_guest
from evennia_links.ignoring import ignore_policy_changing, notice_ignore_status
from evennia_links.notices import (
    NoticeContext,
    RouteResult,
    authorize_context,
    notify,
    source_registry,
    transfer,
)

from .integrations.notices import SOURCE, PlotNoticeSource, Witnesses, event_for, event_key
from .models import PlotNoticeReceipt

State = PlotNoticeReceipt.State
logger = logging.getLogger("evennia")


def _sqlite_retry(operation):
    for attempt in range(3):
        try:
            return operation()
        except OperationalError as exc:
            if connection.vendor != "sqlite" or "locked" not in str(exc).lower() or attempt == 2:
                raise
            sleep(0.025 * (attempt + 1))


def _backend():
    """Resolve a clean standalone host separately from a broken binding."""
    if not apps.is_installed("evennia_notices") or not getattr(settings, "NOTICES_ENABLED", True):
        return "standalone"
    configured = getattr(settings, "LINKS_NOTICE_SOURCES", {})
    if not isinstance(configured, dict):
        return "retry"
    if SOURCE not in configured:
        return "standalone"
    try:
        if isinstance(source_registry().get(SOURCE), PlotNoticeSource):
            return "inbox"
    except Exception:
        logger.warning("Plots notice binding could not be resolved")
    return "retry"


def _memberships(characters, accounts=None):
    memberships = {character.pk: set() for character in characters}
    if not memberships:
        return memberships
    for pk, roster in playable_accounts(accounts):
        for character in roster:
            if character.pk in memberships:
                memberships[character.pk].add(pk)
    return memberships


def _reserve_writer():
    if connection.vendor == "sqlite":
        AccountDB.objects.filter(pk__lt=0).update(last_login=F("last_login"))


def _lock_recipient_accounts(characters):
    # Account locks precede any receipt lock. Domain witnesses are ordinary reads.
    _reserve_writer()
    characters = [character for character in characters if not is_guest(character)]
    memberships = _memberships(characters)
    accounts = {}
    for pk in sorted(set().union(*memberships.values())):
        AccountDB.objects.filter(pk=pk).update(last_login=F("last_login"))
        account = AccountDB.objects.select_for_update().filter(pk=pk).first()
        if account is not None and not is_guest(account):
            account.attributes.reset_cache()
            accounts[pk] = account
    memberships = _memberships(characters, AccountDB.objects.filter(pk__in=accounts))
    return {pk: [accounts[owner] for owner in sorted(owners)] for pk, owners in memberships.items()}


def _ignore(row, account, witnesses, cache=None):
    if account.pk in row.suppressed_accounts:
        return "suppress"
    actor = witnesses.objects.get(row.actor_id)
    return notice_ignore_status(account, actor, policy_cache=cache) if actor else "invalid"


def _snapshot(row, accounts, witnesses):
    policies = {account.pk: _ignore(row, account, witnesses) for account in accounts}
    row.suppressed_accounts = sorted(
        set(row.suppressed_accounts)
        | {pk for pk, policy in policies.items() if policy == "suppress"}
    )
    return policies


def record(kind, plot, actor, recipients, *, thread=None):
    """Stage receipts and arrange post-commit delivery for each exact recipient."""
    if actor is None:
        return
    recipients = [
        (character, owner)
        for character, owner in recipients
        if character is not None and character.pk != actor.pk
    ]
    if not recipients:
        return

    accounts = _lock_recipient_accounts([character for character, _ in recipients])
    backend = _backend()
    for character, owner in recipients:
        row = PlotNoticeReceipt(
            character=character, plot=plot, thread=thread, owner=owner, actor_id=actor.pk, kind=kind
        )
        row.event_key = event_key(row)
        owners = accounts.get(character.pk, [])
        if not owners:
            _stage_transient(row)
            continue

        witnesses = Witnesses([row])
        policies = _snapshot(row, owners, witnesses)
        if backend == "standalone":
            if witnesses.status(row) != "visible" or all(
                policy == "suppress" for policy in policies.values()
            ):
                row.state = State.SUPPRESSED
            elif _observed_offline(character, policies):
                row.state = State.STANDALONE_OFFLINE
        row.save()
        if row.state == State.PENDING:
            transaction.on_commit(lambda row=row: _safe_route(row, fresh=True), robust=True)


def _registered_sessions():
    from evennia.server.sessionhandler import SESSIONS

    return SESSIONS.get_sessions()


def _session_context(session, character, mode):
    try:
        if not session.logged_in or session.get_puppet() != character:
            return None
        account = session.get_account()
        if not isinstance(account, AccountDB) or not account.pk:
            return None
        if mode == "guest":
            eligible = is_guest(account) and is_guest(character) and character.account == account
        elif mode == "nonroster":
            eligible = (
                not is_guest(account) and not is_guest(character) and not account_ids(character)
            )
        else:
            account.attributes.reset_cache()
            eligible = not is_guest(character) and authorize_context(
                NoticeContext(account, character, session)
            )
        return NoticeContext(account, character, session) if eligible else None
    except Exception:
        logger.warning("Plots notice skipped an unavailable connection")
        return None


def _sessions(character, mode="playable"):
    return [
        context
        for session in _registered_sessions()
        if (context := _session_context(session, character, mode)) is not None
    ]


def _observed_offline(character, policies):
    try:
        return not any(
            policies.get(context.account.pk) in {"allow", "defer"}
            for context in _sessions(character)
        )
    except Exception:
        logger.warning("Plots notice could not check for a connected character")
        return False


def _same_connection(context, mode):
    if not any(session is context.session for session in _registered_sessions()):
        return False
    current = _session_context(context.session, context.character, mode)
    return current is not None and (current.account.pk, current.account.date_joined) == (
        context.account.pk,
        context.account.date_joined,
    )


def _fallback_pending(*args):
    return RouteResult("fallback_pending")


@transaction.atomic
def _route(row_id, character, *, fresh=False, context=None):
    accounts = _lock_recipient_accounts([character]).get(character.pk, [])
    if not accounts or (context and context.account.pk not in {a.pk for a in accounts}):
        return
    row = (
        PlotNoticeReceipt.objects.select_for_update()
        .filter(pk=row_id, character=character, state=State.PENDING)
        .first()
    )
    if row is None:
        return

    backend = _backend()
    row.last_attempt = timezone.now()
    witnesses = Witnesses([row])
    status = witnesses.status(row)
    policies = _snapshot(row, accounts, witnesses) if status == "visible" else {}
    if status == "invalid" or (
        policies and all(value == "suppress" for value in policies.values())
    ):
        row.state = State.SUPPRESSED
    elif backend == "inbox":
        event = event_for(row)
        kwargs = dict(source=SOURCE, event=event, context=context, fallback=_fallback_pending)
        result = (
            notify(character, **kwargs)
            if fresh
            else transfer(character, transfer_id=event.event_id, **kwargs)
        )
        # Links validates the immutable event and matching fingerprint before
        # returning duplicate, even if the old Inbox event was cleared.
        if result.receipt and result.status in {"retained", "duplicate", "suppressed"}:
            row.state = State.SUPPRESSED if result.status == "suppressed" else State.INBOX
    elif backend == "standalone" and status == "visible":
        sessions = [
            item for item in _sessions(character) if policies.get(item.account.pk) == "allow"
        ]
        if sessions:
            row.state = State.ATTEMPTING
            row.claim = uuid4()
            row.save(update_fields=["state", "claim", "last_attempt", "suppressed_accounts"])
            return row, sessions
    row.save(update_fields=["state", "last_attempt", "suppressed_accounts"])


def _safe_route(row, *, fresh=False, context=None):
    try:
        claim = _sqlite_retry(lambda: _route(row.pk, row.character, fresh=fresh, context=context))
        if claim:
            claimed, sessions = claim
            attempted, delivered, _ = _send(claimed, sessions)
            _settle(claimed, attempted, delivered)
    except Exception:
        logger.warning("Plots notice dispatch deferred")
        # A DB or adapter exception must also move behind peers on the next
        # bounded pass. This update cannot acknowledge an in-flight claim.
        try:
            _sqlite_retry(lambda: _mark_retry(row.pk))
        except Exception:
            logger.warning("Plots notice retry position unavailable")


@transaction.atomic
def _mark_retry(row_id):
    _reserve_writer()
    PlotNoticeReceipt.objects.filter(pk=row_id, state=State.PENDING).update(
        last_attempt=timezone.now()
    )


@transaction.atomic
def _finalize(row, character, *, attempted, delivered):
    _lock_recipient_accounts([character])
    if delivered:
        state = State.FALLBACK_DELIVERED
    elif attempted:
        state = State.UNCERTAIN
    else:
        state = State.PENDING
    PlotNoticeReceipt.objects.filter(pk=row.pk, claim=row.claim, state=State.ATTEMPTING).update(
        state=state, claim=None, last_attempt=timezone.now()
    )


_waiting_finalizations = {}
_finalizations_lock = Lock()


def _settle(row, attempted, delivered):
    try:
        _sqlite_retry(
            lambda: _finalize(row, row.character, attempted=attempted, delivered=delivered)
        )
    except Exception:
        # The process knows whether it wrote to the socket. Keep that outcome
        # and retry only the claim CAS, never transport.
        with _finalizations_lock:
            _waiting_finalizations[row.claim] = row, attempted, delivered
        logger.warning("Plots notice finalization deferred")
    else:
        with _finalizations_lock:
            _waiting_finalizations.pop(row.claim, None)


def _current_claim(row, mode):
    if mode != "playable":
        return row
    return PlotNoticeReceipt.objects.filter(
        pk=row.pk, claim=row.claim, state=State.ATTEMPTING
    ).first()


def _write_policy(row, context, mode):
    if mode == "playable" and _backend() != "standalone":
        return "defer", None
    current = _current_claim(row, mode)
    if current is None:
        return "invalid", None
    context.account.attributes.reset_cache()
    witnesses = Witnesses([current])
    status = witnesses.status(current)
    if status != "visible":
        return status, None
    return _ignore(current, context.account, witnesses), witnesses


def _write_boundary(row, context, mode):
    if mode == "playable" and _backend() != "standalone":
        return "defer"
    current = _current_claim(row, mode)
    if current is None:
        return "invalid"
    status = Witnesses([current]).status(current)
    if status != "visible":
        return status
    if not _same_connection(context, mode):
        return "defer"
    return "suppress" if context.account.pk in current.suppressed_accounts else "allow"


def _send(row, sessions, *, mode="playable"):
    attempted = delivered = False
    outcomes = []
    for context in sessions:
        outcomes.append("defer")
        try:
            if not _same_connection(context, mode):
                continue
            policy, witnesses = _write_policy(row, context, mode)
            outcomes[-1] = policy
            if policy != "allow":
                continue
            text = witnesses.presentation(row, standalone=True).text
            writer = context.session.msg
            if not callable(writer):
                continue
            policy, _ = _write_policy(row, context, mode)
            if policy == "allow":
                policy = _write_boundary(row, context, mode)
            outcomes[-1] = policy
            if policy != "allow":
                continue
            # Only invocation of the verified writer starts an attempt.
            attempted = True
            writer(text)
            delivered = True
        except Exception:
            logger.warning("Plots notice did not complete on one connection")
    return (
        attempted,
        delivered,
        bool(outcomes) and all(result in {"invalid", "suppress"} for result in outcomes),
    )


def prepare(context, *, limit=100):
    """Retry bounded recorded work; a later transfer cannot trigger a live hint."""
    character = context.character
    if character is None or not authorize_context(context) or _backend() != "inbox":
        return
    _drain(character, limit=limit, context=context)


def _drain(character, *, limit=100, context=None):
    transaction.on_commit(lambda: _drain_committed(character, limit, context), robust=True)


def _drain_committed(character, limit, context):
    with _finalizations_lock:
        waiting = [
            outcome
            for outcome in _waiting_finalizations.values()
            if outcome[0].character_id == character.pk
        ][:limit]
    for outcome in waiting:
        _settle(*outcome)
    rows = list(
        PlotNoticeReceipt.objects.filter(character=character, state=State.PENDING).order_by(
            F("last_attempt").asc(nulls_first=True), "pk"
        )[:limit]
    )
    for row in rows:
        _safe_route(row, context=context)


def _snapshot_ignore(sender, viewer, kind=None, **kwargs):
    if kind not in (None, "notices"):
        return
    _snapshot_transient(viewer)
    if is_guest(viewer):
        return
    account_roster = playable_accounts(AccountDB.objects.filter(pk=viewer.pk))
    character_ids = {character.pk for _, roster in account_roster for character in roster}
    rows = list(
        PlotNoticeReceipt.objects.select_for_update()
        .filter(character_id__in=character_ids, state__in=(State.PENDING, State.ATTEMPTING))
        .order_by("pk")
    )
    witnesses = Witnesses(rows)
    cache = {}
    changed = []
    for row in rows:
        if witnesses.status(row) == "invalid":
            continue
        policy = _ignore(row, viewer, witnesses, cache)
        if policy == "defer":
            raise RuntimeError("Plots notice ignore policy could not be checked")
        if policy == "suppress" and viewer.pk not in row.suppressed_accounts:
            row.suppressed_accounts = sorted([*row.suppressed_accounts, viewer.pk])
            changed.append(row)
    if changed:
        PlotNoticeReceipt.objects.bulk_update(changed, ["suppressed_accounts"])


# Transient work is never rediscovered from domain rows on a later login.
_TRANSIENT_WINDOW = 60
_transient = {}
_transient_lock = Lock()


@dataclass
class _TransientClaim:
    expires: float
    row: PlotNoticeReceipt | None
    mode: str
    sessions: tuple
    state: str = "pending"


def _stage_transient(row):
    mode = "guest" if is_guest(row.character) else "nonroster"
    try:
        sessions = tuple(_sessions(row.character, mode))
    except Exception:
        logger.warning("Transient Plots notice could not find its connection")
        return
    if not sessions:
        return
    accounts = {context.account.pk: context.account for context in sessions}
    for account in accounts.values():
        account.attributes.reset_cache()
    _snapshot(row, accounts.values(), Witnesses([row]))
    transaction.on_commit(lambda: _start_transient(row, mode, sessions), robust=True)


def _start_transient(row, mode, sessions):
    key = row.character_id, row.event_key, row.occurred_at
    with _transient_lock:
        if key not in _transient:
            claim = _TransientClaim(monotonic() + _TRANSIENT_WINDOW, row, mode, sessions)
            _transient[key] = claim
            reactor.callFromThread(
                reactor.callLater, _TRANSIENT_WINDOW, _expire_transient, key, claim.expires
            )
    _retry_transient(key)


def _expire_transient(key, expires):
    with _transient_lock:
        claim = _transient.get(key)
        if claim and claim.expires == expires:
            del _transient[key]


def _snapshot_transient(viewer):
    with _transient_lock:
        claims = [
            claim
            for claim in _transient.values()
            if claim.state != "consumed"
            and claim.expires > monotonic()
            and any(context.account == viewer for context in claim.sessions)
        ]
    for claim in claims:
        row = claim.row
        if row is None:
            continue
        policy = _ignore(row, viewer, Witnesses([row]))
        if policy == "defer":
            raise RuntimeError("Transient Plots notice ignore policy could not be checked")
        if policy == "suppress":
            # The account already hides this notice under the old policy. A
            # rollback leaves that policy in place, so capture the mask now.
            with _transient_lock:
                row.suppressed_accounts = sorted({*row.suppressed_accounts, viewer.pk})


def _retry_transient(key):
    with _transient_lock:
        claim = _transient.get(key)
        if not claim or claim.expires <= monotonic() or claim.state != "pending":
            return
        claim.state = "sending"
    attempted, _, suppressed = _send(claim.row, claim.sessions, mode=claim.mode)
    with _transient_lock:
        if attempted or suppressed:
            claim.state = "consumed"
            claim.row = None
            claim.sessions = ()
        else:
            claim.state = "pending"


def _puppet(sender, session=None, **kwargs):
    if session is None:
        return

    def retry():
        with _transient_lock:
            keys = [key for key in _transient if key[0] == sender.pk]
        for key in keys:
            _retry_transient(key)
        if _backend() == "standalone" and _session_context(session, sender, "playable"):
            _drain(sender)

    transaction.on_commit(retry, robust=True)


def register():
    from evennia.server.signals import SIGNAL_OBJECT_POST_PUPPET

    SIGNAL_OBJECT_POST_PUPPET.connect(_puppet, dispatch_uid="evennia_plots.notices_puppet")
    ignore_policy_changing.connect(_snapshot_ignore, dispatch_uid="evennia_plots.notices_ignore")
