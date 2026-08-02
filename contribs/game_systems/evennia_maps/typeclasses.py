# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Room mixin for evennia_maps.

A contrib cannot patch the game's own Room typeclass, and Evennia ships no
attribute-change signal, so keeping a placed tile's terrain snapshot in
sync requires a mixin — the same shape as evennia_posing's
PosingRoomMixin and evennia_social's SocialRoomMixin. Mix it in ahead of
your other room mixins/ObjectParent::

    from evennia_maps.typeclasses import MapsRoomMixin

    class Room(MapsRoomMixin, ObjectParent, DefaultRoom):
        ...

Without the mixin the map still works — a room can be placed with +map
and reached via layout the same as any other — but nothing calls
set_terrain(), so RoomTile.terrain stays "" (or stale) until a builder
runs +map/check and fixes it by hand.
"""

from evennia.typeclasses.attributes import AttributeProperty


class MapsRoomMixin:
    """Room mixin providing a terrain-tag set and change notification."""

    # -- Terrain tags: a set of strings, e.g. {"forest", "hills"} --
    terrain_tags = AttributeProperty(default=None, autocreate=False)

    def has_terrain(self, *tags):
        """Check if this room has all the specified terrain tags.

        Args:
            *tags: One or more terrain tag strings to check for.

        Returns:
            bool: True if terrain_tags is set and contains all given tags.

        Example:
            room.terrain_tags = {"forest", "hills"}
            room.has_terrain("forest")           # True
            room.has_terrain("forest", "hills")  # True
            room.has_terrain("water")            # False
        """
        if not self.terrain_tags or not tags:
            return False
        return all(tag in self.terrain_tags for tag in tags)

    def set_terrain(self, tags):
        """Replace this room's terrain_tags and notify evennia_maps.

        Fires evennia_maps.signals.terrain_changed so a placed tile's
        denormalized terrain snapshot (RoomTile.terrain) stays in sync —
        callers should use this rather than assigning terrain_tags
        directly.

        Args:
            tags (set): New terrain tag set, e.g. {"forest", "hills"}.
        """
        self.terrain_tags = set(tags) if tags else None

        from evennia_maps.signals import terrain_changed

        terrain_changed.send(sender=self.__class__, room=self)
