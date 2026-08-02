# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Django signals for evennia_maps.

Declared here (rather than in listeners.py) so they're eager-safe and
export-ready — no listeners are connected by importing this module.

tile_placed     — fires when a RoomTile is created or moved.
tile_conflicted — fires when placement targets an already-occupied cell.
terrain_changed — fires when a room's terrain changes, so a placed tile's
                  denormalized terrain snapshot can be refreshed. Games
                  using MapsRoomMixin get this for free via set_terrain().

collect_tile_overlays — reserved for a later phase of this extraction
                  (web tile-overlay seam, sent once per tiles request with
                  kwargs room_ids and staff, merged via
                  evennia_links.collect_dicts()). Declared now so partner
                  contribs can be written against a stable import path;
                  nothing sends or connects to it yet.
"""

from django.dispatch import Signal

tile_placed = Signal()
tile_conflicted = Signal()
terrain_changed = Signal()
collect_tile_overlays = Signal()
