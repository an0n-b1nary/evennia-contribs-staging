# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Region model for evennia_regions.

A Region is a named geographic area grouping one or more rooms. Rooms belong
to regions via RegionMembership (this file), which allows many-to-many
membership with an is_primary flag marking the single deterministic answer
for scalar consumers (e.g. a lore passive-trickle engine keyed by region).

Region depth is flat in v1 — no parent hierarchy. A parent self-FK can be
added in a single migration later if multi-level regions become necessary.
"""

from django.db import models
from django.db.models import Q, UniqueConstraint

from evennia_links import AbstractArchived, AbstractAuthoredLink


class Region(AbstractArchived):
    """
    A named geographic area grouping one or more rooms.

    Soft-archiving (via AbstractArchived) lets staff hide regions from active
    listings without deleting historical data keyed off them.
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique region name. Case-insensitive uniqueness enforced at the command layer.",
    )
    description = models.CharField(
        max_length=1000,
        blank=True,
        help_text="Brief description shown in region listings and the web compendium (max 1000 chars).",
    )
    created_by = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Character who created the region.",
    )
    created_by_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized creator name for display after deletion.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]  # noqa: RUF012

    def __str__(self):
        return self.name

    def member_count(self):
        """Return the number of rooms currently assigned to this region."""
        return self.memberships.count()

    @classmethod
    def create_region(cls, name, creator, description=""):
        """
        Create a new Region and fire the region_created signal.

        Args:
            name (str): Region name. Caller must check uniqueness (case-insensitive)
                        at the command layer before calling.
            creator: ObjectDB character, or None for system creation.
            description (str): Optional description, max 1000 chars.

        Returns:
            Region: The newly created instance.
        """
        from evennia_regions import signals as region_signals

        region = cls.objects.create(
            name=name,
            description=description,
            created_by=creator,
            created_by_name=creator.key if creator else "",
        )
        region_signals.region_created.send(sender=cls, region=region, creator=creator)
        return region


# ---------------------------------------------------------------------------
# Bridge: Room (ObjectDB) <-> Region
# ---------------------------------------------------------------------------


class RegionMembership(AbstractAuthoredLink):
    """
    Links a room (ObjectDB) to a Region.

    A room may belong to several regions at once (many-to-many) — e.g. a
    room can be both in a kingdom and a fief and a magical overlay region.
    At most one membership per room may be flagged is_primary (enforced by
    a partial unique constraint below); this is the single deterministic
    answer for scalar consumers that need exactly one region per room
    rather than the full membership set.

    room_name is denormalized for display in region listings after the
    object is deleted or renamed.
    """

    region = models.ForeignKey(
        Region,
        on_delete=models.CASCADE,
        related_name="memberships",
        help_text="The region this room belongs to.",
    )
    room = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.CASCADE,
        related_name="+",
        help_text="The room. A room may belong to multiple regions.",
    )
    room_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized room name for display after deletion.",
    )
    is_primary = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this is the room's primary region for scalar readers.",
    )

    link_fields = ("region", "room")

    class Meta(AbstractAuthoredLink.Meta):
        constraints = [  # noqa: RUF012
            UniqueConstraint(
                fields=["room"],
                condition=Q(is_primary=True),
                name="evennia_regions_one_primary_per_room",
            ),
        ]

    def __str__(self):
        room_label = self.room_name or f"Room #{self.room_id}"
        return f"{room_label} -> {self.region}"

    @classmethod
    def primary_for(cls, room_id):
        """
        Return the primary RegionMembership for a room, or None.

        Falls back to the earliest membership when none is flagged
        is_primary — the single source of truth for scalar region_id
        readers.

        Ordering puts the flagged primary first, then the earliest
        membership; pk breaks ties because two rows created in the same
        transaction can share a created_at timestamp.
        """
        return (
            cls.objects.filter(room_id=room_id).order_by("-is_primary", "created_at", "pk").first()
        )
