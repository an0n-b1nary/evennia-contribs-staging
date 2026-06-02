# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
LoreTag, LoreEntry, LoreVersion, and bridge models for evennia_lore.

Lore entries are wiki-like articles that players contribute and passively
acquire through RP. Entry numbers are globally auto-incrementing stable IDs.

Status lifecycle: DRAFT → SUBMITTED → PUBLISHED (or REJECTED). When
settings.LORE_REQUIRE_APPROVAL is False (the default), create_entry() jumps
directly to PUBLISHED.

Privacy:
    PUBLIC     — browseable and passively acquirable by all players.
    RESTRICTED — title + summary visible in the compendium; full body
                 requires a storyteller +share.

Bridge models (cross-domain, owned by evennia_lore):
    LoreAcquisition  — per-character compendium row (lore ↔ rptracker).
    PlotLoreLink     — links a LoreEntry to a PlotThread (lore ↔ plots).
    LoreSceneLink    — links a LoreEntry to a Scene (lore ↔ scenes).
    LoreRegionLink   — links a LoreEntry to a Region (lore ↔ regions).

All bridge models use integer soft-references for the partner-app side so
the bridge table has no DB dependency on the partner app. Hard-deletion of
the partner entity is compensated by connect_soft_ref_cleanup() hooks
registered in LoreConfig.ready().

Context-forced divergence from the source game: in the source game these
bridges live in a shared world/links/ package per the domain-island rule.
For the contrib they live here because evennia_lore is their consuming owner.
"""

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.db.models import Max, Q
from django.utils import timezone

from evennia_links import AbstractArchived, AbstractAuthoredLink, AbstractVersion

# Bounded retries for allocating a unique entry_number under concurrent creation.
_CREATE_ENTRY_MAX_RETRIES = 5


# ---------------------------------------------------------------------------
# LoreTag
# ---------------------------------------------------------------------------


class LoreTag(models.Model):
    """
    A tag that can be applied to LoreEntry objects.

    Major tags (is_major=True) are staff-defined thematic anchors
    (e.g. "Magic", "Politics", "History"). Minor tags are player-created
    free-form labels. Tag creation is implicit — +lore/tag creates the tag
    if it does not already exist. Staff (LORE_STAFF_LOCK) can flag a tag as major.
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Tag name. Case-insensitive uniqueness enforced at the command layer.",
    )
    is_major = models.BooleanField(
        default=False,
        help_text="Major tags are staff-defined. Minor tags are player-created.",
    )
    created_by = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Character who created the tag.",
    )
    created_by_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized creator name.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_major", "name"]  # noqa: RUF012

    def __str__(self):
        kind = "Major" if self.is_major else "Minor"
        return f"[{kind}] {self.name}"


# ---------------------------------------------------------------------------
# LoreEntry
# ---------------------------------------------------------------------------


class LoreEntry(AbstractArchived):
    """
    A wiki-like article in the in-game lore compendium.

    Status lifecycle:
        DRAFT      — work-in-progress; author-only visible.
        SUBMITTED  — queued for staff review (when LORE_REQUIRE_APPROVAL=True).
        PUBLISHED  — live; acquirable by players.
        REJECTED   — soft-archived; hidden from default listings.

    Privacy:
        PUBLIC     — full body visible to all who have acquired it.
        RESTRICTED — title + summary visible as a stub; full body requires +share.

    entry_number is globally auto-incrementing and never reused.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        PUBLISHED = "published", "Published"
        REJECTED = "rejected", "Rejected"

    class Privacy(models.TextChoices):
        PUBLIC = "public", "Public"
        RESTRICTED = "restricted", "Restricted"

    entry_number = models.PositiveIntegerField(
        unique=True,
        help_text="Auto-incremented globally. Used as the human-readable entry ID.",
    )
    title = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Entry title. Unique among PUBLISHED entries (partial unique constraint).",
    )
    body = models.TextField(
        blank=True,
        help_text="Full article body.",
    )
    summary = models.CharField(
        max_length=500,
        blank=True,
        help_text="Short teaser shown in listings and as the hint for RESTRICTED entries.",
    )

    author = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Character who authored the entry.",
    )
    author_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized author name for display after deletion.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    privacy = models.CharField(
        max_length=12,
        choices=Privacy.choices,
        default=Privacy.PUBLIC,
        db_index=True,
    )

    is_flagged = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True when a player has flagged this entry for staff review.",
    )
    flag_reason = models.CharField(max_length=500, blank=True)
    flagged_by = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Character who flagged the entry.",
    )
    flagged_by_name = models.CharField(max_length=255, blank=True)
    reviewed_by = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Staff member who approved or rejected the entry.",
    )
    reviewed_by_name = models.CharField(max_length=255, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    tags = models.ManyToManyField(
        LoreTag,
        blank=True,
        related_name="entries",
    )
    # region associations are in LoreRegionLink (integer soft-ref bridge)
    rooms = models.ManyToManyField(
        "objects.ObjectDB",
        blank=True,
        related_name="+",
        help_text="Specific rooms this lore entry is associated with.",
    )
    objects_tagged = models.ManyToManyField(
        "objects.ObjectDB",
        blank=True,
        related_name="+",
        help_text="In-game items or equipment associated with this lore entry.",
    )

    class Meta:
        ordering = ["-created_at"]  # noqa: RUF012
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["title"],
                condition=Q(status="published"),
                name="evennia_lore_title_published_unique",
            )
        ]

    def __str__(self):
        return f"#{self.entry_number} {self.title}"

    @classmethod
    def create_entry(cls, title, author, body="", summary="", privacy=None):
        """
        Create a new LoreEntry, atomically assigning the next entry_number.

        Status defaults to PUBLISHED when LORE_REQUIRE_APPROVAL is False
        (the default); otherwise SUBMITTED. Fires lore_entry_created and
        (when published immediately) lore_entry_published.

        Retries up to _CREATE_ENTRY_MAX_RETRIES times on unique-number collision
        (race condition on entry_number); raises IntegrityError if exhausted.
        """
        from evennia_lore import signals as lore_signals

        if privacy is None:
            privacy = cls.Privacy.PUBLIC

        require_approval = getattr(settings, "LORE_REQUIRE_APPROVAL", False)
        status = cls.Status.SUBMITTED if require_approval else cls.Status.PUBLISHED
        author_name = author.key if author else "Unknown"

        for _attempt in range(_CREATE_ENTRY_MAX_RETRIES):
            current_max = cls.all_objects.aggregate(max_num=Max("entry_number")).get("max_num") or 0
            try:
                with transaction.atomic():
                    entry = cls.objects.create(
                        entry_number=current_max + 1,
                        title=title,
                        body=body,
                        summary=summary,
                        privacy=privacy,
                        status=status,
                        author=author,
                        author_name=author_name,
                    )
            except IntegrityError:
                continue
            else:
                lore_signals.lore_entry_created.send(sender=cls, entry=entry)
                if status == cls.Status.PUBLISHED:
                    lore_signals.lore_entry_published.send(sender=cls, entry=entry)
                return entry

        raise IntegrityError(
            f"Could not allocate a unique entry_number after "
            f"{_CREATE_ENTRY_MAX_RETRIES} attempts."
        )

    def publish(self, reviewed_by=None):
        """Transition SUBMITTED → PUBLISHED and fire lore_entry_published."""
        from evennia_lore import signals as lore_signals

        self.status = self.Status.PUBLISHED
        self.reviewed_by = reviewed_by
        self.reviewed_by_name = reviewed_by.key if reviewed_by else ""
        self.reviewed_at = timezone.now()
        self.save(update_fields=["status", "reviewed_by", "reviewed_by_name", "reviewed_at"])
        lore_signals.lore_entry_published.send(sender=type(self), entry=self)

    def reject(self, reviewed_by=None, editor=None):
        """Transition SUBMITTED → REJECTED and soft-archive the entry."""
        self.status = self.Status.REJECTED
        self.reviewed_by = reviewed_by
        self.reviewed_by_name = reviewed_by.key if reviewed_by else ""
        self.reviewed_at = timezone.now()
        self.save(update_fields=["status", "reviewed_by", "reviewed_by_name", "reviewed_at"])
        self.archive(editor=editor or reviewed_by)

    def flag(self, flagged_by, reason=""):
        """Set is_flagged=True with an optional reason."""
        self.is_flagged = True
        self.flag_reason = reason
        self.flagged_by = flagged_by
        self.flagged_by_name = flagged_by.key if flagged_by else ""
        self.save(update_fields=["is_flagged", "flag_reason", "flagged_by", "flagged_by_name"])

    def unflag(self):
        """Clear the flag."""
        self.is_flagged = False
        self.flag_reason = ""
        self.flagged_by = None
        self.flagged_by_name = ""
        self.save(update_fields=["is_flagged", "flag_reason", "flagged_by", "flagged_by_name"])

    def edit_body(self, new_body, editor):
        """Snapshot current body as a LoreVersion then apply new content."""
        from evennia_lore import signals as lore_signals

        LoreVersion.create_version(parent=self, content=self.body, editor=editor)
        self.body = new_body
        self.save(update_fields=["body", "updated_at"])
        lore_signals.lore_entry_edited.send(sender=type(self), entry=self, editor=editor)

    def is_accessible_to(self, character):
        """
        Return True if character may read the full body of this entry.

        PUBLIC entries: always readable if PUBLISHED.
        RESTRICTED entries: requires a LoreAcquisition row for character.
        """
        if self.status != self.Status.PUBLISHED:
            return False
        if self.privacy == self.Privacy.PUBLIC:
            return True
        if character is None:
            return False
        return LoreAcquisition.objects.filter(entry=self, character=character).exists()

    def is_in_passive_pool(self):
        """Return True if this entry is eligible for passive trickle acquisition."""
        return (
            self.status == self.Status.PUBLISHED
            and self.privacy == self.Privacy.PUBLIC
            and not self.is_archived
        )


# ---------------------------------------------------------------------------
# LoreVersion
# ---------------------------------------------------------------------------


class LoreVersion(AbstractVersion):
    """
    Version snapshot for a LoreEntry body.

    Stores the OLD body before each edit. The live body lives on LoreEntry.body.
    Version numbers are sequential per parent entry.
    """

    parent = models.ForeignKey(
        LoreEntry,
        on_delete=models.CASCADE,
        related_name="versions",
    )

    class Meta(AbstractVersion.Meta):
        unique_together = [("parent", "version_number")]  # noqa: RUF012


# ---------------------------------------------------------------------------
# Bridge models (owned by evennia_lore per the contrib bridge-ownership rule)
# ---------------------------------------------------------------------------


class LoreAcquisition(models.Model):
    """
    Per-character compendium row: one row per (entry, character) pair.

    Tracks how and when a character acquired a lore entry.

    session_id is nullable — only set for PASSIVE acquisitions. Integer
    soft-reference: no FK constraint on rptracker.RPSession.
    shared_by is nullable — only set for SHARED acquisitions.

    Acquisition rows are permanent historical records — session deletion
    leaves session_id as a stale integer (harmless; informational only).
    """

    class Source(models.TextChoices):
        PASSIVE = "passive", "Passive"
        SHARED = "shared", "Shared"
        STORYTELLER = "storyteller", "Storyteller"
        SEED = "seed", "Seed"

    entry = models.ForeignKey(
        LoreEntry,
        on_delete=models.CASCADE,
        related_name="acquisitions",
        help_text="The lore entry that was acquired.",
    )
    character = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.CASCADE,
        related_name="+",
        help_text="The character who acquired the entry.",
    )
    character_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized character name.",
    )
    acquired_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
    )
    source = models.CharField(
        max_length=12,
        choices=Source.choices,
        default=Source.PASSIVE,
        db_index=True,
    )
    session_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "PK of the RPSession that triggered this acquisition (PASSIVE only). "
            "Integer soft-reference — no DB cascade on session deletion."
        ),
    )
    shared_by = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Character who shared this entry via +share (SHARED only).",
    )
    shared_by_name = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = [("entry", "character")]  # noqa: RUF012
        ordering = ["-acquired_at"]  # noqa: RUF012

    def __str__(self):
        return f"{self.character_name} acquired LoreEntry #{self.entry_id} [{self.source}]"


class PlotLoreLink(AbstractAuthoredLink):
    """
    Links a LoreEntry to a PlotThread (integer soft-reference).

    thread_id is the PK of the PlotThread — no FK constraint on the plots app.
    Hard-deletion of a PlotThread is compensated by connect_soft_ref_cleanup()
    registered in LoreConfig.ready() when the plots app is present.
    """

    thread_id = models.PositiveBigIntegerField(
        db_index=True,
        help_text="PK of the PlotThread linked to this lore entry.",
    )
    entry = models.ForeignKey(
        LoreEntry,
        on_delete=models.CASCADE,
        related_name="plot_links",
        help_text="The lore entry linked to this plot thread.",
    )

    link_fields = ("thread_id", "entry")

    class Meta(AbstractAuthoredLink.Meta):
        unique_together = [("thread_id", "entry")]  # noqa: RUF012

    def __str__(self):
        return f"PlotThread #{self.thread_id} ↔ LoreEntry #{self.entry_id}"


class LoreSceneLink(AbstractAuthoredLink):
    """
    Links a LoreEntry to a Scene (integer soft-reference).

    scene_id is the PK of the Scene — no FK constraint on the scenes app.
    Hard-deletion of a Scene is compensated by connect_soft_ref_cleanup()
    registered in LoreConfig.ready() when the scenes app is present.
    """

    entry = models.ForeignKey(
        LoreEntry,
        on_delete=models.CASCADE,
        related_name="scene_links",
        help_text="The lore entry linked to this scene.",
    )
    scene_id = models.PositiveBigIntegerField(
        db_index=True,
        help_text="PK of the Scene linked to this lore entry.",
    )

    link_fields = ("entry", "scene_id")

    class Meta(AbstractAuthoredLink.Meta):
        unique_together = [("entry", "scene_id")]  # noqa: RUF012

    def __str__(self):
        return f"LoreEntry #{self.entry_id} ↔ Scene #{self.scene_id}"


class LoreRegionLink(AbstractAuthoredLink):
    """
    Links a LoreEntry to a Region (integer soft-reference).

    region_id is the PK of the Region — no FK constraint on the regions app.
    Replaces the former LoreEntry.regions ManyToManyField.
    Hard-deletion of a Region is compensated by connect_soft_ref_cleanup()
    registered in LoreConfig.ready() when the regions app is present.
    """

    entry = models.ForeignKey(
        LoreEntry,
        on_delete=models.CASCADE,
        related_name="region_links",
        help_text="The lore entry associated with this region.",
    )
    region_id = models.PositiveBigIntegerField(
        db_index=True,
        help_text="PK of the Region associated with this lore entry.",
    )

    link_fields = ("entry", "region_id")

    class Meta(AbstractAuthoredLink.Meta):
        unique_together = [("entry", "region_id")]  # noqa: RUF012

    def __str__(self):
        return f"LoreEntry #{self.entry_id} ↔ Region #{self.region_id}"
