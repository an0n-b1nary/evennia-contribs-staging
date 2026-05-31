# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
RPTracker session manager.

Manages the runtime logic for detecting and tracking RP sessions. This
module is the single integration point called from your Character typeclass's
pose hook and disconnect hook. See README for the full integration recipe.

Architecture:
- A module-level dict (_active_sessions) keyed by character.id holds
  lightweight session state for the hot path, avoiding a DB query per pose.
- record_rp_activity(character, room) is the entry point, called on every
  qualifying pose.
- DB writes are batched: pose_count is flushed every RPTRACKER_POSE_FLUSH_THRESHOLD
  poses or on session end, not on every individual pose.
- RPIdleCheckScript (Evennia Script) runs periodically to close idle sessions.
- flush_all_sessions() is called on graceful server shutdown.
- recover_orphaned_sessions() is called on startup to close any ACTIVE sessions
  that were left open by a crash.

In-memory state per character entry in _active_sessions:
{
    "status": "pending" | "active",
    "session_id": int | None,       # RPSession.pk once activated
    "room_id": int,                  # Room pk where tracking started
    "started_at": float,             # Unix timestamp when tracking began
    "last_pose_at": float,           # Unix timestamp of most recent pose
    "pose_count": int,               # Total poses in this tracking cycle
    "pending_pose_count": int,       # Poses not yet flushed to the DB
    "partner_pose_counts": dict,     # {partner_char_id: int} approximate
}

Activation threshold: RPTRACKER_SESSION_ACTIVATION_POSES poses from the
character AND at least 1 other character in the room whose last_pose_time
is within the past RPTRACKER_PARTNER_ACTIVE_WINDOW seconds.

Tests that need a different threshold value should patch the module global
directly (e.g. ``tracker.SESSION_ACTIVATION_POSES = 1``), not override
settings — the constants are resolved at import time.
"""

import logging
import time

from django.conf import settings

logger = logging.getLogger("evennia")

# ---------------------------------------------------------------------------
# Constants — resolved from settings at import time.
# ---------------------------------------------------------------------------

SESSION_IDLE_TIMEOUT = getattr(settings, "RPTRACKER_SESSION_IDLE_TIMEOUT", 3600)
PARTNER_ACTIVE_WINDOW = getattr(settings, "RPTRACKER_PARTNER_ACTIVE_WINDOW", 3600)
SESSION_ACTIVATION_POSES = getattr(settings, "RPTRACKER_SESSION_ACTIVATION_POSES", 2)
POSE_FLUSH_THRESHOLD = getattr(settings, "RPTRACKER_POSE_FLUSH_THRESHOLD", 5)

# ---------------------------------------------------------------------------
# In-memory session state
# ---------------------------------------------------------------------------

_active_sessions = {}  # character.id -> state dict


def _make_pending_state(room_id, partner_ids):
    """Return a fresh pending state dict for a new tracking entry."""
    now = time.time()
    return {
        "status": "pending",
        "session_id": None,
        "room_id": room_id,
        "started_at": now,
        "last_pose_at": now,
        "pose_count": 1,
        "pending_pose_count": 0,
        "partner_pose_counts": {pid: 0 for pid in partner_ids},
    }


# ---------------------------------------------------------------------------
# Partner detection
# ---------------------------------------------------------------------------


def _get_active_partner_ids(character, room, now):
    """Return a set of character IDs who are actively posing in the room.

    "Actively posing" means: the character is in the room, is a puppeted
    object (has an account), has a ``last_pose_time`` attribute set, and
    that pose was within RPTRACKER_PARTNER_ACTIVE_WINDOW seconds ago.
    NPCs (tagged ``"npc"`` in category ``"npc_system"``) are excluded.

    Args:
        character: The posing Character (excluded from results).
        room: The Room object.
        now (float): Current unix timestamp.

    Returns:
        set: Character IDs of active partners.
    """
    cutoff = now - PARTNER_ACTIVE_WINDOW
    partner_ids = set()
    for obj in room.contents:
        if obj is character:
            continue
        if not hasattr(obj, "last_pose_time"):
            continue
        if obj.tags.get("npc", category="npc_system"):
            continue
        last_pose = getattr(obj, "last_pose_time", None)
        if last_pose and last_pose > cutoff:
            partner_ids.add(obj.id)
    return partner_ids


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------


def _flush_session(char_id, state):
    """Persist the pending pose count for an active session to the DB.

    Also syncs RPSessionPartner records with current partner_pose_counts.
    Resets pending_pose_count to 0.
    """
    from evennia_rptracker.models import RPSession, RPSessionPartner

    session_id = state.get("session_id")
    if not session_id:
        return

    pending = state.get("pending_pose_count", 0)
    if pending > 0:
        try:
            from django.db.models import F

            RPSession.objects.filter(pk=session_id).update(pose_count=F("pose_count") + pending)
        except Exception:
            logger.exception("RPTracker: failed to flush pose_count for session #%s", session_id)
    state["pending_pose_count"] = 0

    from evennia.objects.models import ObjectDB

    partner_names = {}
    if state["partner_pose_counts"]:
        for obj in ObjectDB.objects.filter(pk__in=state["partner_pose_counts"].keys()).only(
            "pk", "db_key"
        ):
            partner_names[obj.pk] = obj.db_key

    for partner_id, p_count in state["partner_pose_counts"].items():
        try:
            obj, created = RPSessionPartner.objects.get_or_create(
                session_id=session_id,
                partner_id=partner_id,
                defaults={
                    "pose_count": p_count,
                    "partner_name": partner_names.get(partner_id, ""),
                },
            )
            if not created:
                changed = False
                if obj.pose_count != p_count:
                    obj.pose_count = p_count
                    changed = True
                if not obj.partner_name and partner_id in partner_names:
                    obj.partner_name = partner_names[partner_id]
                    changed = True
                if changed:
                    obj.save(update_fields=["pose_count", "partner_name"])
        except Exception:
            logger.exception(
                "RPTracker: failed to sync partner %s for session #%s",
                partner_id,
                session_id,
            )


def _activate_session(char_id, character, room, state):
    """Transition a pending tracking entry to an active RPSession in the DB."""
    from evennia_rptracker.models import RPSession
    from evennia_rptracker.signals import rp_session_started

    try:
        session = RPSession.objects.create(
            character=character,
            character_name=character.key,
            room=room,
            room_name=room.key if room else "",
            status=RPSession.Status.ACTIVE,
        )
        from django.utils import timezone

        session.activated_at = timezone.now()
        session.save(update_fields=["activated_at"])
    except Exception:
        logger.exception("RPTracker: failed to create RPSession for character %s", char_id)
        return

    state["status"] = "active"
    state["session_id"] = session.pk

    try:
        rp_session_started.send(sender=RPSession, session=session)
    except Exception:
        logger.exception("RPTracker: rp_session_started signal failed for session #%s", session.pk)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_rp_activity(character, room):
    """Main entry point — call from your Character's pose hook.

    Skips non-IC rooms (``room.room_type != "ic"``) and NPC characters
    (``character.tags.get("npc", category="npc_system")``).

    Character must expose ``last_pose_time`` (float unix timestamp) so
    partner detection can determine which characters are actively posing.

    Args:
        character: The posing Character typeclass instance.
        room: The Room typeclass instance (character.location).
    """
    if getattr(room, "room_type", "ic") != "ic":
        return
    if character.tags.get("npc", category="npc_system"):
        return

    now = time.time()
    char_id = character.id
    partner_ids = _get_active_partner_ids(character, room, now)

    if char_id not in _active_sessions:
        _active_sessions[char_id] = _make_pending_state(room.pk, partner_ids)
        return

    state = _active_sessions[char_id]

    if state["room_id"] != room.pk:
        if state["status"] == "active":
            end_session(char_id, manual=False)
        _active_sessions[char_id] = _make_pending_state(room.pk, partner_ids)
        return

    state["last_pose_at"] = now
    state["pose_count"] += 1

    for pid in partner_ids:
        state["partner_pose_counts"][pid] = state["partner_pose_counts"].get(pid, 0) + 1

    if state["status"] == "pending":
        if state["pose_count"] >= SESSION_ACTIVATION_POSES and partner_ids:
            _activate_session(char_id, character, room, state)
            if state["status"] == "active":
                _fire_activity_signal(character, state, room)
        return

    if state["status"] == "active":
        state["pending_pose_count"] += 1
        if state["pending_pose_count"] >= POSE_FLUSH_THRESHOLD:
            _flush_session(char_id, state)
        _fire_activity_signal(character, state, room)


def _fire_activity_signal(character, state, room):
    """Fire rp_activity_recorded for an active session."""
    from evennia_rptracker.signals import rp_activity_recorded

    try:
        rp_activity_recorded.send(
            sender=character.__class__,
            character=character,
            session_id=state["session_id"],
            room=room,
        )
    except Exception:
        logger.exception(
            "RPTracker: rp_activity_recorded signal failed for session #%s",
            state.get("session_id"),
        )


def end_session(character_id, manual=False):
    """End the tracked session for a character.

    Call from your Character's disconnect hook (``at_post_unpuppet``) and
    from the +activity/end command handler.

    Args:
        character_id (int): The character's DB id.
        manual (bool): True if triggered by the player via +activity/end.
    """
    state = _active_sessions.pop(character_id, None)
    if not state:
        return

    session_id = state.get("session_id")
    if not session_id:
        return

    _flush_session(character_id, state)

    from evennia_rptracker.models import RPSession
    from evennia_rptracker.signals import rp_session_ended

    try:
        session = RPSession.objects.get(pk=session_id)
    except RPSession.DoesNotExist:
        return

    session.complete(manual=manual)

    if manual:
        _check_manual_end_flag(session)

    try:
        rp_session_ended.send(sender=RPSession, session=session)
    except Exception:
        logger.exception("RPTracker: rp_session_ended signal failed for session #%s", session_id)


def _check_manual_end_flag(session):
    """Auto-flag if the character has too many manual session ends today."""
    from django.conf import settings
    from django.utils import timezone

    from evennia_rptracker.models import RPSession

    threshold = getattr(settings, "RPTRACKER_MANUAL_END_ABUSE_COUNT", 3)
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    manual_today = RPSession.objects.filter(
        character=session.character,
        ended_manually=True,
        ended_at__gte=today_start,
    ).count()
    if manual_today >= threshold:
        session.flag(
            reason=(
                f"Auto-flag: {manual_today} manual session ends today "
                f"(threshold: {threshold}). Review for session-splitting."
            )
        )


def get_active_session_id(character_id):
    """Return the RPSession PK for a character's active session, or None."""
    state = _active_sessions.get(character_id)
    if state and state["status"] == "active":
        return state["session_id"]
    return None


def get_session_state(character_id):
    """Return a copy of the in-memory state for a character, or None."""
    state = _active_sessions.get(character_id)
    if state is None:
        return None
    return dict(state)


# ---------------------------------------------------------------------------
# Idle check
# ---------------------------------------------------------------------------


def _check_idle_sessions():
    """Close sessions idle for longer than RPTRACKER_SESSION_IDLE_TIMEOUT."""
    now = time.time()
    cutoff = now - SESSION_IDLE_TIMEOUT
    timed_out = [
        char_id
        for char_id, state in list(_active_sessions.items())
        if state["last_pose_at"] < cutoff
    ]
    for char_id in timed_out:
        state = _active_sessions.get(char_id)
        if not state:
            continue
        if state["status"] == "active":
            end_session(char_id, manual=False)
        else:
            _active_sessions.pop(char_id, None)


# ---------------------------------------------------------------------------
# Server lifecycle hooks
# ---------------------------------------------------------------------------


def flush_all_sessions():
    """Persist all in-memory sessions and mark them COMPLETED.

    Call from ``at_server_stop()`` in your server startup/shutdown module.
    """
    for char_id in list(_active_sessions.keys()):
        end_session(char_id, manual=False)


def recover_orphaned_sessions():
    """Mark orphaned ACTIVE sessions as COMPLETED on startup.

    Call from ``at_server_start()`` in your server startup/shutdown module.
    """
    from django.utils import timezone

    from evennia_rptracker.models import RPSession

    orphans = RPSession.objects.filter(status=RPSession.Status.ACTIVE)
    count = orphans.count()
    if count:
        logger.info(
            "RPTracker: recovering %d orphaned ACTIVE session(s) from previous run.",
            count,
        )
        orphans.update(status=RPSession.Status.COMPLETED, ended_at=timezone.now())


# ---------------------------------------------------------------------------
# IC-channel seam (inert — future extension point)
# ---------------------------------------------------------------------------


def record_rp_channel_activity(character, channel):
    """Entry point for IC-channel RP activity detection (inert seam).

    This is a no-op placeholder for a future IC-channel XP collector. When
    a character sends an IC-channel message, the channel typeclass can call
    this function. Today it logs a debug message and returns immediately.

    Args:
        character: The Character ObjectDB who sent the channel message.
        channel: The Channel instance.
    """
    logger.debug(
        "RPTracker: IC-channel activity from %s on channel %s (seam, no-op).",
        getattr(character, "key", character),
        getattr(channel, "key", channel),
    )


# ---------------------------------------------------------------------------
# Evennia Script: idle check runner
# ---------------------------------------------------------------------------


def ensure_idle_check_running():
    """Create the RPIdleCheckScript if it is not already running.

    Call from ``at_server_start()``. Safe to call multiple times.
    """
    from evennia.utils.search import search_script

    existing = search_script("rp_idle_check")
    if not existing:
        from evennia.utils.create import create_script

        create_script(
            "evennia_rptracker.tracker.RPIdleCheckScript",
            key="rp_idle_check",
            persistent=True,
            autostart=True,
        )
        logger.info("RPTracker: idle check Script started.")


try:
    from evennia import DefaultScript

    if DefaultScript is None:
        raise ImportError("DefaultScript not yet available")

    class RPIdleCheckScript(DefaultScript):
        """Evennia Script that periodically closes idle RP sessions."""

        def at_script_creation(self):
            from django.conf import settings

            self.key = "rp_idle_check"
            self.desc = "Closes idle RPTracker sessions."
            self.interval = getattr(settings, "RPTRACKER_IDLE_CHECK_INTERVAL", 300)
            self.persistent = True
            self.repeats = 0

        def at_repeat(self):
            _check_idle_sessions()

except (ImportError, TypeError):
    RPIdleCheckScript = None
