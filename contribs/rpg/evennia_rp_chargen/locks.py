# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Build locks: edge and loadout freeze while a character is in a scene.

    unlocked --(IC pose, a resolved check, or +lock)--> locked
    locked --(+unlock, RP session end, or the idle TTL)--> unlocked

A pose while unlocked locks again, which covers "unlock, swap, re-lock". What
a lock freezes is `RP_CHARGEN_LOCK_SCOPES` (edge pips and loadout by default).
Draft sheets never lock: a player still building needs everything editable.

Locking and unlocking by hand are self-service and announced to the room, so
the norm doing the work is transparency rather than a staff gate. Automatic
locks and releases are told only to the character.

Hooks for the game:

- `note_ic_action(character)`: call it from the game's single pose listener
  (or its own pose method). chargen never connects to a pose signal itself.
- `check_resolved` (from evennia_rp_rules) is connected in `ready()`: a
  resolved check counts as IC action for the actor.
- With evennia_rptracker installed, its `rp_session_ended` releases the lock
  (`integrations/rptracker.py`).
- `RP_CHARGEN_LOCK_TTL` releases a lock that long after the last IC action,
  for solo posing that never makes a session and for games with no tracker.
  It's checked when the lock is read; no script runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from evennia_rp_chargen import conf

ATTR_KEY = "rp_build_locks"
ATTR_CATEGORY = "rp_chargen"

POSE = "pose"
CHECK = "check"
MANUAL = "manual"
SESSION_END = "session ended"
IDLE = "idle"


@dataclass(frozen=True)
class LockState:
    locked: bool = False
    since: datetime | None = None
    last_action: datetime | None = None
    reason: str = ""


def _has_lockable_build(character) -> bool:
    from evennia_rp_chargen.models import CharacterBuild

    return (
        CharacterBuild.objects.filter(character_id=character.id)
        .exclude(status=CharacterBuild.Status.DRAFT)
        .exists()
    )


def _load(character) -> LockState:
    raw = character.attributes.get(ATTR_KEY, category=ATTR_CATEGORY, default=None)
    if not raw:
        return LockState()
    return LockState(
        locked=bool(raw.get("locked")),
        since=raw.get("since"),
        last_action=raw.get("last_action"),
        reason=raw.get("reason", ""),
    )


def _save(character, state: LockState) -> None:
    character.attributes.add(
        ATTR_KEY,
        {
            "locked": state.locked,
            "since": state.since,
            "last_action": state.last_action,
            "reason": state.reason,
        },
        category=ATTR_CATEGORY,
    )


def _expired(state: LockState, now: datetime) -> bool:
    ttl = conf.lock_ttl()
    if not state.locked or ttl is None:
        return False
    last = state.last_action or state.since
    return last is not None and now - last >= ttl


def state(character) -> LockState:
    """The character's lock, releasing it first if the idle TTL has passed."""
    current = _load(character)
    if _expired(current, timezone.now()):
        release(character, IDLE)
        return _load(character)
    return current


def is_locked(character) -> bool:
    return state(character).locked


def scope_locked(character, scope: str) -> bool:
    """Whether changes in `scope` ("pips", "loadout") are frozen right now."""
    return scope in conf.lock_scopes() and is_locked(character)


def _announce(character, room_text: str, self_text: str) -> None:
    character.msg(self_text)
    location = getattr(character, "location", None)
    if location is not None:
        # The only substitution is the actor's name; the text itself is ours.
        location.msg_contents(
            room_text, exclude=[character], mapping={"actor": character}, from_obj=character
        )


def lock(character, *, reason: str = MANUAL, announce: bool | None = None) -> bool:
    """Lock the build. Returns False if it was already locked (the TTL clock still restarts).

    `announce` defaults to True for manual locks and False for automatic ones.
    """
    now = timezone.now()
    current = state(character)
    if current.locked:
        _save(character, LockState(True, current.since, now, current.reason))
        return False
    _save(character, LockState(True, now, now, reason))
    things = conf.locked_things()
    should_announce = reason == MANUAL if announce is None else announce
    if should_announce:
        _announce(character, f"{{actor}} locks their {things}.", f"You lock your {things}.")
    else:
        verb = "are" if " and " in things else "is"
        character.msg(
            f"Your {things} {verb} now locked for the scene. "
            "(+unlock to change them; the room is told.)"
        )
    return True


def unlock(character) -> bool:
    """Unlock by hand, announced to the room. Returns False if it wasn't locked."""
    if not state(character).locked:
        return False
    _save(character, LockState())
    things = conf.locked_things()
    _announce(
        character,
        f"{{actor}} unlocks their {things}.",
        f"You unlock your {things}. Your next IC pose locks them again.",
    )
    return True


def release(character, reason: str) -> bool:
    """Release without an announcement (session end, idle TTL). Tells the character."""
    if not _load(character).locked:
        return False
    _save(character, LockState())
    things = conf.locked_things()
    why = {SESSION_END: "your RP session ended", IDLE: "no IC activity for a while"}.get(
        reason, reason
    )
    character.msg(f"Your {things} unlocked: {why}.")
    return True


def note_ic_action(character) -> None:
    """An IC pose (or other IC action) happened: lock, or restart the idle clock.

    Cheap for characters without a finalized sheet: one indexed query, no writes.
    """
    if character is None or not _has_lockable_build(character):
        return
    lock(character, reason=POSE)


def on_check_resolved(sender, check=None, result=None, **kwargs) -> None:
    """`check_resolved` receiver: a resolved check is IC action for its actor."""
    actor = getattr(check, "actor", None)
    is_object = hasattr(actor, "attributes") and getattr(actor, "id", None) is not None
    if is_object and _has_lockable_build(actor):
        lock(actor, reason=CHECK)


__all__ = [
    "LockState",
    "is_locked",
    "lock",
    "note_ic_action",
    "on_check_resolved",
    "release",
    "scope_locked",
    "state",
    "unlock",
]
