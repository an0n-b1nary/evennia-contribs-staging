# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Terrain resolution for evennia_maps.

Resolves a room's terrain_tags set (typeclasses.py MapsRoomMixin) down to
the single base terrain key that RoomTile.terrain snapshots, via the
ordered TERRAIN_PRECEDENCE setting. First listed tag present on the room
wins; tags not listed there fall through to "" (a game's web layer is
expected to fall back to a default sprite for that case).

Kept as its own module rather than inlined in placement.py so a future
combat/terrain system can share this resolution without importing
placement's write path.
"""

from django.conf import settings


def resolve_terrain(room):
    """
    Resolve a room's terrain_tags to the single base terrain key.

    Args:
        room: An ObjectDB/Room instance. A room with no terrain_tags set
            resolves to "".

    Returns:
        str: the winning terrain key, or "" if the room has no tags or
            none of them appear in settings.TERRAIN_PRECEDENCE.
    """
    tags = getattr(room, "terrain_tags", None)
    if not tags:
        return ""
    for candidate in getattr(settings, "TERRAIN_PRECEDENCE", []):
        if candidate in tags:
            return candidate
    return ""
