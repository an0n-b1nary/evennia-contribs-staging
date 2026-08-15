# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Permission helpers for evennia_maps commands, web views, and API.

Settings:
    MAPS_STAFF_LOCK — lock string for place/move/unplace/pin/reflow/check
        operations (default "cmd:perm(Builder)").
    MAPS_ROOM_VISIBILITY — dotted path to a callable(room) -> bool for
        games whose room-hiding rules differ from the default. Without an
        override, a room is web-visible unless it is flagged ``room_type
        == "staff"`` or ``allow_teleport == "secret"``.

``is_room_web_visible`` is a privacy predicate, so every uncertain answer
resolves to "hidden". See its docstring for why.

**This is a deliberate ten-line duplicate of
``evennia_regions.permissions.is_room_web_visible``.** A map tile and a
region's member-room list expose the same fact (this room exists, and it is
called *that*), so the two must not drift; but evennia_maps and
evennia_regions otherwise share no models, no imports, and no install
ordering, and a dependency edge between them purely to dedupe this
predicate would be a worse trade than keeping the two copies in step. A
game that installs both and overrides one rule should set both
``MAPS_ROOM_VISIBILITY`` and ``REGIONS_ROOM_VISIBILITY`` to the same path.
"""

import logging

from django.conf import settings

from evennia_links import resolve_dotted

_log = logging.getLogger("evennia")


def _staff_lock_expr():
    lock = getattr(settings, "MAPS_STAFF_LOCK", "cmd:perm(Builder)")
    return lock[4:] if lock.startswith("cmd:") else lock


def is_staff(character) -> bool:
    """Return True if *character* has maps staff permission level."""
    try:
        return bool(character.locks.check_lockstring(character, _staff_lock_expr()))
    except Exception:
        return False


def is_staff_user(request) -> bool:
    """Return True if the request's account has maps staff permission."""
    if request is None or not request.user.is_authenticated:
        return False
    account = request.user
    try:
        return bool(account.locks.check_lockstring(account, _staff_lock_expr()))
    except Exception:
        return bool(getattr(account, "is_superuser", False))


def room_attr_values(room, name):
    """Return every value the game might have stored for a room attribute.

    Games store room state two ways: as a typeclass attribute (an
    ``AttributeProperty`` descriptor, or a plain class default) or as an
    ordinary Evennia Attribute (``room.db.room_type = "staff"``). ``getattr``
    sees only the first — it never consults the AttributeHandler — which is
    why a game whose own Room typeclass declares these as AttributeProperty
    can read them with ``getattr`` alone, and why a game that instead writes
    ``room.db.room_type`` would have had every such room published.

    Both sources are returned rather than picking a winner, because a plain
    class attribute can shadow an Attribute that disagrees with it and a
    privacy predicate has no basis for preferring the permissive one. The
    privacy caller lets the hidden answer win; the cosmetic caller
    (hangout markers) takes the first value present.
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


def read_room_attr(room, name, default=None):
    """First value stored for *name* on *room*, or *default*.

    The cosmetic counterpart to the privacy read above — used for
    ``hangout_type``, which carries no privacy dimension. Failing soft (a
    missing marker) is the right degradation for a decoration.
    """
    try:
        values = room_attr_values(room, name)
    except Exception:
        return default
    return values[0] if values else default


def _default_room_visible(room) -> bool:
    try:
        room_types = room_attr_values(room, "room_type")
        teleport_settings = room_attr_values(room, "allow_teleport")
    except Exception:
        _log.exception(
            "evennia_maps: could not read visibility flags for room %r; treating as hidden",
            getattr(room, "pk", room),
        )
        return False
    return "staff" not in room_types and "secret" not in teleport_settings


def is_room_web_visible(room) -> bool:
    """Return True if *room* may be named or located on a public web page.

    When MAPS_ROOM_VISIBILITY names a ``callable(room) -> bool``, that
    callable is the whole answer. Otherwise a room is visible unless it is
    flagged ``room_type == "staff"`` or ``allow_teleport == "secret"``.

    **Fails closed.** A configured-but-unusable override returns False (room
    hidden) rather than falling back to the default rule. The fallback looks
    tidier, but it is a silent privacy leak: a game only sets this setting
    because its hiding rules are *stricter* than the default, so quietly
    reverting to the default on a typo publishes exactly the rooms the
    operator was trying to withhold. A map that suddenly renders empty is
    loud, logged, and diagnosable; one that plots secret rooms is none of
    those.

    Catches Exception rather than ImportError alone: resolving the path
    imports the target module, which runs the game's own top-level code and
    can fail any way that code can fail — and calling the override runs game
    code too.
    """
    override_path = getattr(settings, "MAPS_ROOM_VISIBILITY", None)
    if not override_path:
        return _default_room_visible(room)

    try:
        override = resolve_dotted(override_path)
    except Exception:
        _log.exception(
            "evennia_maps: MAPS_ROOM_VISIBILITY=%r failed to import; hiding all rooms",
            override_path,
        )
        return False
    if override is None:
        _log.error(
            "evennia_maps: MAPS_ROOM_VISIBILITY=%r resolved to None; hiding all rooms",
            override_path,
        )
        return False

    try:
        return bool(override(room))
    except Exception:
        _log.exception(
            "evennia_maps: MAPS_ROOM_VISIBILITY=%r raised for room %r; treating as hidden",
            override_path,
            getattr(room, "pk", room),
        )
        return False
