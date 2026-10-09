# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Independent IC-channel sessions. Only recent speakers supply partners."""

import logging
import time
from datetime import UTC, datetime

from django.conf import settings
from django.db import transaction

from evennia_links import resolve_dotted

logger = logging.getLogger("evennia")
_active_channel_sessions = {}  # (character id, channel id) -> state
_recent_speakers = {}  # channel id -> {character id: (timestamp, account ids)}


def eligible(character):
    """Common validation for the typeclass and direct collection entry point."""
    if character is None or not getattr(character, "account", None):
        return False
    if character.tags.get("npc", category="npc_system"):
        return False
    hook = getattr(settings, "RPTRACKER_CHANNEL_ELIGIBLE", None)
    try:
        if isinstance(hook, str):
            hook = resolve_dotted(hook)
        return not hook or bool(hook(character))
    except Exception:
        logger.exception("RPTracker: channel eligibility policy failed")
        return False


def _accounts(character):
    from evennia_links.characters import account_ids

    return {character.account.pk, *account_ids(character)}


def _at(timestamp):
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _signal(name, **kwargs):
    from evennia_rptracker import signals
    from evennia_rptracker.models import RPSession

    getattr(signals, name).send_robust(sender=RPSession, **kwargs)


@transaction.atomic
def _flush(state):
    from evennia.objects.models import ObjectDB

    from evennia_rptracker.models import RPSession, RPSessionPartner

    if not state["session_id"]:
        return False
    session = RPSession.objects.filter(pk=state["session_id"])
    if not session.exists():
        return False
    session.update(pose_count=state["pose_count"], last_activity_at=_at(state["last_activity"]))
    names = dict(ObjectDB.objects.filter(pk__in=state["partners"]).values_list("pk", "db_key"))
    for partner, count in state["partners"].items():
        if partner in names:
            RPSessionPartner.objects.update_or_create(
                session_id=state["session_id"],
                partner_id=partner,
                defaults={"partner_name": names[partner], "pose_count": count},
            )
    state["unflushed"] = 0
    return True


def record_rp_channel_activity(character, channel):
    """Count one accepted IC message, without reading or modifying room pose state."""
    if not eligible(character):
        return
    now = time.time()
    check_idle_sessions(now)
    accounts = _accounts(character)
    window = getattr(settings, "RPTRACKER_CHANNEL_PARTNER_ACTIVE_WINDOW", 1800)
    recent = _recent_speakers.setdefault(channel.pk, {})
    from evennia.objects.models import ObjectDB

    candidates = ObjectDB.objects.filter(pk__in=recent)
    partners = {
        obj.pk
        for obj in candidates
        if obj.pk != character.pk
        and eligible(obj)
        and recent[obj.pk][0] > now - window
        and not (accounts & _accounts(obj))
    }
    recent[character.pk] = (now, accounts)
    key = (character.pk, channel.pk)
    state = _active_channel_sessions.get(key)
    if state and state["status"] == "active" and not partners:
        end_channel_session(*key)
        # Ending our session removes our recent-speaker record too.
        _recent_speakers.setdefault(channel.pk, {})[character.pk] = (now, accounts)
        state = None
    if state is None:
        _active_channel_sessions[key] = {
            "status": "pending",
            "session_id": None,
            "started_at": now,
            "last_message": now,
            "last_activity": now,
            "pose_count": 1,
            "partners": {},
            "unflushed": 0,
            "accounts": accounts,
        }
        return
    state["last_message"] = now
    state["pose_count"] += 1
    if not partners:
        return
    state["last_activity"] = now
    for partner in partners:
        state["partners"][partner] = state["partners"].get(partner, 0) + 1
    from evennia_rptracker.models import RPSession

    if state["status"] == "pending":
        if state["pose_count"] < getattr(settings, "RPTRACKER_CHANNEL_ACTIVATION_MESSAGES", 2):
            return
        with transaction.atomic():
            session = RPSession.objects.create(
                source_type=RPSession.Source.CHANNEL,
                character=character,
                character_name=character.key,
                channel=channel,
                channel_name=channel.key,
                status=RPSession.Status.ACTIVE,
                account_id_snapshot=character.account.pk,
                activated_at=_at(now),
                last_activity_at=_at(now),
                pose_count=state["pose_count"],
            )
            state["session_id"] = session.pk
            _flush(state)
        state["status"] = "active"
        _signal("rp_channel_session_started", session=session)
    else:
        state["unflushed"] += 1
        if state["unflushed"] >= getattr(
            settings, "RPTRACKER_POSE_FLUSH_THRESHOLD", 5
        ) and not _flush(state):
            _active_channel_sessions.pop(key, None)
            return
    _signal(
        "rp_channel_activity_recorded",
        character=character,
        session_id=state["session_id"],
        channel=channel,
    )


def end_channel_session(character_id, channel_id, manual=False):
    """Close one channel session at its last qualifying message, never at wall time."""
    state = _active_channel_sessions.pop((character_id, channel_id), None)
    speakers = _recent_speakers.get(channel_id, {})
    speakers.pop(character_id, None)
    if not speakers:
        _recent_speakers.pop(channel_id, None)
    if not state or not state["session_id"] or not _flush(state):
        return None
    from evennia_rptracker.models import RPSession
    from evennia_rptracker.tracker import _check_manual_end_flag

    session = RPSession.objects.get(pk=state["session_id"])
    session.complete(manual=manual)
    if manual:
        _check_manual_end_flag(session)
    _signal("rp_channel_session_ended", session=session)
    return session.pk


def end_character_channel_sessions(character_id):
    for char_id, channel_id in list(_active_channel_sessions):
        if char_id == character_id:
            end_channel_session(char_id, channel_id)


def end_subscriber_sessions(subscriber, channel_id):
    """Leaving an account subscription ends all its characters on this channel."""
    from evennia.accounts.models import AccountDB

    for (char_id, chan_id), state in list(_active_channel_sessions.items()):
        matches = (
            subscriber.pk in state["accounts"]
            if isinstance(subscriber, AccountDB)
            else subscriber.pk == char_id
        )
        if chan_id == channel_id and matches:
            end_channel_session(char_id, chan_id)


def check_idle_sessions(now=None):
    now = time.time() if now is None else now
    idle = getattr(settings, "RPTRACKER_CHANNEL_SESSION_IDLE_TIMEOUT", 1800)
    window = getattr(settings, "RPTRACKER_CHANNEL_PARTNER_ACTIVE_WINDOW", 1800)
    for key, state in list(_active_channel_sessions.items()):
        if state["last_message"] <= now - idle:
            end_channel_session(*key)
    for channel_id, speakers in list(_recent_speakers.items()):
        for char_id, (last, _accounts_ids) in list(speakers.items()):
            if last <= now - window:
                speakers.pop(char_id, None)
        if not speakers:
            _recent_speakers.pop(channel_id, None)


def flush_all_sessions():
    for key in list(_active_channel_sessions):
        end_channel_session(*key)
    _recent_speakers.clear()
