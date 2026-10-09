# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Terrain resolution for evennia_maps.

Resolves a room's terrain_tags set (typeclasses.py MapsRoomMixin) down to
the single base terrain key that RoomTile.terrain snapshots, via the
ordered MAPS_TERRAIN_PRECEDENCE setting. First listed tag present on the room
wins; tags not listed there fall through to "" (a game's web layer is
expected to fall back to a default sprite for that case).

Kept as its own module rather than inlined in placement.py so a future
combat/terrain system can share this resolution without importing
placement's write path.

Display data (label, colour, sprite) for a resolved key comes from
``terrain_style()``, which reads ``MAPS_TERRAINS`` and falls back to the
older ``MAPS_TERRAIN_TILESET`` for sprites.
"""

import re

from django.conf import settings

# Colours reach SVG fill attributes and Leaflet path options, so only plain
# hex values pass; anything else falls back to the default swatch.
_HEX_COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def resolve_terrain(room):
    """
    Resolve a room's terrain_tags to the single base terrain key.

    Args:
        room: An ObjectDB/Room instance. A room with no terrain_tags set
            resolves to "".

    Returns:
        str: the winning terrain key, or "" if the room has no tags or
            none of them appear in settings.MAPS_TERRAIN_PRECEDENCE.
    """
    tags = getattr(room, "terrain_tags", None)
    if not tags:
        return ""
    for candidate in getattr(settings, "MAPS_TERRAIN_PRECEDENCE", []):
        if candidate in tags:
            return candidate
    return ""


def _terrains():
    return getattr(settings, "MAPS_TERRAINS", None) or {}


def terrain_style(terrain):
    """
    Display data for a resolved terrain key.

    Args:
        terrain: a key from ``resolve_terrain()``; "" for no terrain.

    Returns:
        dict: ``key``; ``label`` (the configured label, else the key in
            sentence case, else ""); ``color`` (a hex colour for a cell with
            no sprite, else ""); ``sprite`` (``MAPS_TERRAINS``' sprite, else
            ``MAPS_TERRAIN_TILESET``'s, else "").
    """
    if not terrain:
        return {"key": "", "label": "", "color": "", "sprite": ""}
    entry = _terrains().get(terrain) or {}
    color = entry.get("color") or ""
    tileset = getattr(settings, "MAPS_TERRAIN_TILESET", None) or {}
    return {
        "key": terrain,
        "label": entry.get("label") or terrain.replace("_", " ").capitalize(),
        "color": color if _HEX_COLOUR.match(color) else "",
        "sprite": entry.get("sprite") or tileset.get(terrain, ""),
    }


def terrain_legend(terrains):
    """
    Legend rows for the terrain keys present on a map, each a ``terrain_style()``.

    Ordered as ``MAPS_TERRAINS`` lists them, then ``MAPS_TERRAIN_PRECEDENCE``,
    then alphabetically; "" (no terrain) is left out.
    """
    present = {key for key in terrains if key}
    order = [*_terrains(), *getattr(settings, "MAPS_TERRAIN_PRECEDENCE", [])]
    ranked = sorted(
        present, key=lambda key: (order.index(key) if key in order else len(order), key)
    )
    return [terrain_style(key) for key in ranked]
