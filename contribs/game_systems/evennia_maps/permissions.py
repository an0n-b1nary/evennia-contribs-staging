# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Permission helpers for evennia_maps commands.

Settings:
    MAPS_STAFF_LOCK — lock string for place/move/unplace/pin/reflow/check
        operations (default "cmd:perm(Builder)").

Web/API-facing helpers (is_staff_user, is_room_web_visible +
MAPS_ROOM_VISIBILITY) land with this contrib's web surface in a later
phase of this extraction — mirrored from evennia_regions.permissions,
which already ships the hardened version of the same seam.
"""

from django.conf import settings


def _staff_lock_expr():
    lock = getattr(settings, "MAPS_STAFF_LOCK", "cmd:perm(Builder)")
    return lock[4:] if lock.startswith("cmd:") else lock


def is_staff(character) -> bool:
    """Return True if *character* has maps staff permission level."""
    try:
        return bool(character.locks.check_lockstring(character, _staff_lock_expr()))
    except Exception:
        return False
