# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Signal listeners for evennia_maps.

Two independent listeners, both wired from MapsConfig.ready():

- on_object_post_create (evennia.server.signals.SIGNAL_OBJECT_POST_CREATE):
  the auto-placement trigger. Evennia typeclasses are Django *proxy*
  models (this contrib has no control over that), so Django's own
  post_save fires with sender=<the proxy class>, not sender=ObjectDB —
  filtering on sender=ObjectDB would silently never match a real Exit.
  SIGNAL_OBJECT_POST_CREATE sidesteps that: it's Evennia's own signal,
  fired once at the end of every create.create_object() call (which is
  what dig/@tunnel/open all funnel through) with `sender` being the
  already-typeclassed instance itself. Filtered to newly-created objects
  with a destination whose source room already has a RoomTile, so
  `dig <dir>=<room>` grows the map without any override of the
  dig/tunnel/open commands themselves. A mapping failure here must never
  break building, so the body is wrapped in a broad try/except.

  This is also the one placement path a builder never asked for: the
  tile is a side effect of digging an exit, not a thing anyone typed.
  MAPS_UNMAPPABLE_ROOM_TYPES is honoured *here and only here* for that
  reason — see _is_unmappable().

- on_terrain_changed (evennia_maps.signals.terrain_changed): refreshes a
  placed tile's denormalized terrain snapshot. A game using
  MapsRoomMixin gets this via Room.set_terrain(); a game that doesn't
  can still send the signal by hand if it manages terrain some other way.
"""

import logging

from django.conf import settings
from django.dispatch import receiver
from evennia.server.signals import SIGNAL_OBJECT_POST_CREATE

logger = logging.getLogger("evennia")


def _is_unmappable(room):
    """Return True if the game has declared *room*'s room_type off-map.

    Games routinely keep rooms that are not part of the physical world at
    all — an OOC lounge, a character-generation suite, a staff office —
    and those have no business taking a cell on a spatial grid. Listing
    their room_type in MAPS_UNMAPPABLE_ROOM_TYPES keeps the auto-placer
    from annexing one the moment somebody digs a directional exit into it.

    Deliberately *not* a privacy rule and deliberately *not* consulted by
    the explicit +map/place path:

    - Not privacy. is_room_web_visible() hides a tile that exists; this
      stops the tile existing. Hiding is the wrong tool here — the row
      would still hold its cell under the (plane, x, y) unique
      constraint, layout.plan() would still route around it, and
      +map/check would still report it, leaving an invisible occupied
      hole in the grid. Privacy flags ("staff", "secret") stay hardcoded
      and fail-closed in permissions.py; this one is game cosmology, so
      it is configuration and defaults to empty.

    - Not the command. A builder who types +map/place on such a room
      meant it, and refusing them would be this contrib overruling the
      game's own staff. +map/check reports the result instead, which is
      the honest split: block the accident, report the decision.

    Reads through room_attr_values() so a game that stores room_type as a
    plain Evennia Attribute (room.db.room_type) is seen, not just one
    using an AttributeProperty descriptor. Failure is *not* swallowed to
    a permissive answer here the way a cosmetic read would be: a room
    whose flags cannot be read is treated as unmappable, matching the
    fail-closed direction the rest of this contrib takes.
    """
    unmappable = getattr(settings, "MAPS_UNMAPPABLE_ROOM_TYPES", ())
    if not unmappable:
        return False
    from evennia_maps.permissions import room_attr_values

    try:
        room_types = room_attr_values(room, "room_type")
    except Exception:
        logger.exception(
            "evennia_maps.listeners: could not read room_type for room #%s; "
            "treating as unmappable",
            getattr(room, "id", None),
        )
        return True
    return bool(set(room_types) & set(unmappable))


@receiver(SIGNAL_OBJECT_POST_CREATE, dispatch_uid="evennia_maps.on_object_post_create")
def on_object_post_create(sender, **kwargs):
    """Auto-place a newly-created exit's destination, if its source is mapped.

    `sender` here is the newly created object itself (Evennia's
    SIGNAL_OBJECT_POST_CREATE convention), not a model class.
    """
    new_object = sender
    destination = getattr(new_object, "destination", None)
    if destination is None:
        return

    source_room = new_object.location
    if source_room is None:
        return

    if _is_unmappable(destination):
        return

    try:
        from evennia_maps.models import RoomTile
        from evennia_maps.placement import place_relative

        if not RoomTile.objects.filter(room=source_room).exists():
            return
        place_relative(source_room, new_object)
    except Exception:
        logger.exception(
            "evennia_maps.listeners: failed to auto-place exit #%s from room #%s",
            new_object.id,
            source_room.id,
        )


def on_terrain_changed(sender, room, **kwargs):
    """Refresh a room's placed tile terrain snapshot when its terrain_tags change."""
    try:
        from evennia_maps.models import RoomTile
        from evennia_maps.terrain import resolve_terrain

        RoomTile.objects.filter(room_id=room.id).update(terrain=resolve_terrain(room))
    except Exception:
        logger.exception(
            "evennia_maps.listeners: failed to refresh terrain snapshot for room #%s",
            getattr(room, "id", None),
        )
