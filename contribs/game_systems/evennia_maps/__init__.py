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
    collect_tile_overlays   — the web tile-overlay seam: sent once per map
                              render, answered by whichever partner
                              contribs are installed (see overlays.py)

Commands (import explicitly):

    from evennia_maps.commands import CmdMap

Room mixin (import explicitly, mix into your Room typeclass):

    from evennia_maps.typeclasses import MapsRoomMixin

Web surface (requires the [web] extra; import explicitly so a game running
headless never pulls in Django REST Framework):

    evennia_maps.urls        — website routes (/map/, /map/<pk>/, .../live/)
    evennia_maps.api.urls    — DRF router (planes + nested tiles)
    evennia_maps.overlays    — the collect_tile_overlays seam and its contract
"""

__version__ = "0.2.0"

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
