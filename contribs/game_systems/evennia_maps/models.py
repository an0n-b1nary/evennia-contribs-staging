# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Map geometry models for evennia_maps.

A MapPlane is a 2D coordinate space (an overworld surface, an underground
layer, a city interior). Planes that stack vertically 1:1 share a zstack
label with an integer elevation (e.g. sky=+1, surface=0, underground=-1);
standalone/interior planes leave zstack blank. A RoomTile places a single
room at (x, y) on one plane.

evennia-regions (a separate contrib) is a purely semantic room grouping —
it has no geometry. A room's presence on the map is entirely independent
of its region membership; the two are joined only at the web/API layer
via an integer soft-ref, added in a later phase of this extraction.

Ported from the source game's world/maps/models.py, substituting
world.utils.archiving.AbstractArchived for evennia_links.AbstractArchived
(the same abstract fields, now shared infrastructure).
"""

from django.db import models
from django.db.models import Q, UniqueConstraint

from evennia_links import AbstractArchived


class MapPlane(AbstractArchived):
    """
    A single 2D coordinate space that a set of RoomTiles are placed on.

    Planes sharing a non-blank zstack are vertically stacked layers of the
    same footprint (e.g. an "overworld" zstack at elevation -1/0/+1 for
    underground/surface/sky); u/d exits within a zstack move to the same
    (x, y) on the adjacent-elevation plane. A blank zstack ("") marks a
    standalone plane (a city interior reached through a portal) that is
    not part of any vertical stack — many such planes may coexist at
    elevation 0 without colliding, since the uniqueness constraint below
    only applies to non-blank zstacks.
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique plane name.",
    )
    zstack = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Vertical stack label shared by aligned planes. Blank = standalone/interior.",
    )
    elevation = models.IntegerField(
        default=0,
        help_text="Layer position within the zstack (meaningful only when zstack is set).",
    )
    description = models.CharField(
        max_length=1000,
        blank=True,
        help_text="Brief description shown on the web map.",
    )
    created_by = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Character who created the plane.",
    )
    created_by_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized creator name for display after deletion.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]  # noqa: RUF012
        constraints = [  # noqa: RUF012
            UniqueConstraint(
                fields=["zstack", "elevation"],
                condition=~Q(zstack=""),
                name="evennia_maps_one_plane_per_elevation",
            ),
        ]

    def __str__(self):
        return self.name


class RoomTile(models.Model):
    """
    Places a single room at (x, y) on a MapPlane.

    A room lives at exactly one place (unique_together on ("room",)); a
    coordinate cell holds exactly one room (unique_together on
    ("plane", "x", "y")). A room reachable at two different coordinates
    (a non-Euclidean topology conflict) is the condition +map/check and
    +map/reflow report — the DB constraint is what makes that condition
    detectable rather than a silent overwrite.

    room is a real FK to ObjectDB (CASCADE) — ObjectDB is always present
    for a placed room, so no soft-ref is needed for this edge.
    """

    plane = models.ForeignKey(
        MapPlane,
        on_delete=models.CASCADE,
        related_name="tiles",
        help_text="The plane this tile is placed on.",
    )
    room = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.CASCADE,
        related_name="+",
        help_text="The room placed at this tile. A room may hold only one tile.",
    )
    x = models.IntegerField()
    y = models.IntegerField()
    pinned = models.BooleanField(
        default=False,
        help_text="Pinned tiles are never moved by auto-placement or +map/reflow.",
    )
    terrain = models.CharField(
        max_length=64,
        blank=True,
        help_text="Denormalized base terrain (resolved from the room's terrain_tags set).",
    )
    room_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized room name for display after deletion.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("plane", "x", "y"), ("room",)]  # noqa: RUF012
        indexes = [models.Index(fields=["plane", "x", "y"])]  # noqa: RUF012

    def __str__(self):
        room_label = self.room_name or f"Room #{self.room_id}"
        return f"{room_label} @ {self.plane.name}({self.x},{self.y})"
