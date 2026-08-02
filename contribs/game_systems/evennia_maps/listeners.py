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

- on_terrain_changed (evennia_maps.signals.terrain_changed): refreshes a
  placed tile's denormalized terrain snapshot. A game using
  MapsRoomMixin gets this via Room.set_terrain(); a game that doesn't
  can still send the signal by hand if it manages terrain some other way.
"""

import logging

from django.dispatch import receiver
from evennia.server.signals import SIGNAL_OBJECT_POST_CREATE

logger = logging.getLogger("evennia")


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
