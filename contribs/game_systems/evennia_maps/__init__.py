# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_maps — a 2D coordinate map of your game's rooms, auto-grown from
canonical exits, for Evennia games.

Public API (model classes loaded lazily to avoid AppRegistryNotReady):

    MapPlane    — a 2D coordinate space (an overworld surface, an
                  underground layer, a standalone city interior)
    RoomTile    — places a single room at (x, y) on a MapPlane

Signals (eagerly exported — plain Signal() objects, safe at app-load time):

    tile_placed
    tile_conflicted
    terrain_changed
    collect_tile_overlays   — reserved for the web tile-overlay seam
                              (a later phase of this extraction)

Commands (import explicitly):

    from evennia_maps.commands import CmdMap

Room mixin (import explicitly, mix into your Room typeclass):

    from evennia_maps.typeclasses import MapsRoomMixin

This is the core phase of the extraction: models, geometry (direction,
terrain, placement, layout), commands, listeners, and the room mixin.
Website views, the DRF API, and the SVG/Leaflet static assets land in a
later phase — see MIGRATION_NOTES.md.
"""

__version__ = "0.1.0"

from evennia_maps.signals import (
    collect_tile_overlays,
    terrain_changed,
    tile_conflicted,
    tile_placed,
)

_LAZY = {
    "MapPlane": "models",
    "RoomTile": "models",
}

__all__ = [
    "MapPlane",
    "RoomTile",
    "collect_tile_overlays",
    "terrain_changed",
    "tile_conflicted",
    "tile_placed",
]


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{submodule}", __name__), name)


def __dir__():
    return sorted([*globals(), *_LAZY])
