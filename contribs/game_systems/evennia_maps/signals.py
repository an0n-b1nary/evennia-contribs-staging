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

collect_tile_overlays — the web tile-overlay seam. Sent once per map
                  render (never per tile) with kwargs room_ids (list[int])
                  and staff (bool), sender=MapPlane. Each connected partner
                  contrib returns {overlay_key: {room_id: value}} for the
                  rooms it has data about, merged via
                  evennia_links.collect_dicts() — which send_robust()s, so
                  a provider that raises degrades its own overlay to absent
                  rather than failing the request. Receiver order is not
                  guaranteed and must not matter: providers write disjoint
                  keys. Sent from evennia_maps.overlays.collect_overlays();
                  see that module for the full key contract and for why
                  these cannot simply be read off the partner models.
"""

from django.dispatch import Signal

tile_placed = Signal()
tile_conflicted = Signal()
terrain_changed = Signal()
collect_tile_overlays = Signal()
