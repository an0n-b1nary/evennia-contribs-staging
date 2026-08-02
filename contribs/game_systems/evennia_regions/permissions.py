# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Permission helpers for evennia_regions commands, web views, and API.

Settings:
    REGIONS_STAFF_LOCK — lock string for create/edit/membership operations
        (default "cmd:perm(Builder)").
    REGIONS_ROOM_VISIBILITY — dotted path to a callable(room) -> bool for
        games whose room-hiding rules differ from the default. Without an
        override, a room is web-visible unless it is flagged ``room_type
        == "staff"`` or ``allow_teleport == "secret"``.

``is_room_web_visible`` is a privacy predicate, so every uncertain answer
resolves to "hidden". See its docstring for why.
"""

import logging

from django.conf import settings

from evennia_links import resolve_dotted

_log = logging.getLogger("evennia")


def _staff_lock_expr():
    lock = getattr(settings, "REGIONS_STAFF_LOCK", "cmd:perm(Builder)")
    return lock[4:] if lock.startswith("cmd:") else lock


def is_staff(character) -> bool:
    """Return True if *character* has regions staff permission level."""
    try:
        return bool(character.locks.check_lockstring(character, _staff_lock_expr()))
    except Exception:
        return False


def is_staff_user(request) -> bool:
    """Return True if the request's account has regions staff permission."""
    if not request.user.is_authenticated:
        return False
    account = request.user
    try:
        return bool(account.locks.check_lockstring(account, _staff_lock_expr()))
    except Exception:
        return bool(getattr(account, "is_superuser", False))


def _room_flag_values(room, name):
    """Return every value the game might have stored for a room flag.

    Games store room flags two ways: as a typeclass attribute (an
    ``AttributeProperty`` descriptor, or a plain class default) or as an
    ordinary Evennia Attribute (``room.db.room_type = "staff"``). ``getattr``
    sees only the first — it never consults the AttributeHandler — which is
    why the source game can read these with ``getattr`` alone: its own Room
    typeclass declares both flags as AttributeProperty. A game that instead
    writes ``room.db.room_type`` would have had every such room published.

    Both sources are returned rather than picking a winner, because a plain
    class attribute can shadow an Attribute that disagrees with it and a
    privacy predicate has no basis for preferring the permissive one. The
    caller lets the hidden answer win.
    """
    values = []
    direct = getattr(room, name, None)
    if direct is not None:
        values.append(direct)
    handler = getattr(room, "attributes", None)
    if handler is not None:
        stored = handler.get(name, default=None)
        if stored is not None:
            values.append(stored)
    return values


def _default_room_visible(room) -> bool:
    try:
        room_types = _room_flag_values(room, "room_type")
        teleport_settings = _room_flag_values(room, "allow_teleport")
    except Exception:
        _log.exception(
            "evennia_regions: could not read visibility flags for room %r; treating as hidden",
            getattr(room, "pk", room),
        )
        return False
    return "staff" not in room_types and "secret" not in teleport_settings


def is_room_web_visible(room) -> bool:
    """Return True if *room* may be named or located on a public web page.

    When REGIONS_ROOM_VISIBILITY names a ``callable(room) -> bool``, that
    callable is the whole answer. Otherwise a room is visible unless it is
    flagged ``room_type == "staff"`` or ``allow_teleport == "secret"``.

    **Fails closed.** A configured-but-unusable override returns False (room
    hidden) rather than falling back to the default rule. The fallback looks
    tidier, but it is a silent privacy leak: a game only sets this setting
    because its hiding rules are *stricter* than the default, so quietly
    reverting to the default on a typo publishes exactly the rooms the
    operator was trying to withhold. A region page that suddenly lists no
    rooms is loud, logged, and diagnosable; one that lists secret rooms is
    none of those.

    Catches Exception rather than ImportError alone: resolving the path
    imports the target module, which runs the game's own top-level code and
    can fail any way that code can fail — and calling the override runs game
    code too.
    """
    override_path = getattr(settings, "REGIONS_ROOM_VISIBILITY", None)
    if not override_path:
        return _default_room_visible(room)

    try:
        override = resolve_dotted(override_path)
    except Exception:
        _log.exception(
            "evennia_regions: REGIONS_ROOM_VISIBILITY=%r failed to import; hiding all rooms",
            override_path,
        )
        return False
    if override is None:
        _log.error(
            "evennia_regions: REGIONS_ROOM_VISIBILITY=%r resolved to None; hiding all rooms",
            override_path,
        )
        return False

    try:
        return bool(override(room))
    except Exception:
        _log.exception(
            "evennia_regions: REGIONS_ROOM_VISIBILITY=%r raised for room %r; treating as hidden",
            override_path,
            getattr(room, "pk", room),
        )
        return False
