# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Permission helpers for evennia_regions commands, web views, and API.

Settings:
    REGIONS_STAFF_LOCK — lock string for create/edit/membership operations
        (default "cmd:perm(Builder)").
    REGIONS_ROOM_VISIBILITY — dotted path to a callable(room) -> bool for
        games whose room-hiding rules differ from the default. Without an
        override, a room is web-visible unless its ``room_type`` attribute
        is ``"staff"`` or its ``allow_teleport`` attribute is ``"secret"``
        (both read via getattr, so games without those attributes see
        every room as visible).
"""

from django.conf import settings

from evennia_links import resolve_dotted


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


def _default_room_visible(room) -> bool:
    room_type = getattr(room, "room_type", "ic") or "ic"
    allow_teleport = getattr(room, "allow_teleport", "public") or "public"
    return room_type != "staff" and allow_teleport != "secret"


def is_room_web_visible(room) -> bool:
    """Return True if *room* may be named or located on a public web page.

    Checks REGIONS_ROOM_VISIBILITY first — a dotted path to a
    callable(room) -> bool — falling back to the default rule when no
    override is configured or the override fails to resolve.
    """
    override_path = getattr(settings, "REGIONS_ROOM_VISIBILITY", None)
    if override_path:
        try:
            override = resolve_dotted(override_path)
        except ImportError:
            override = None
        if override is not None:
            return bool(override(room))
    return _default_room_visible(room)
