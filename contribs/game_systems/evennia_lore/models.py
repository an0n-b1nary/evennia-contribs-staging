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

Layers (see evennia_lore.layers):
    body       — the IC content. May be false: rumors and legends can be.
    ooc_notes  — the OOC layer, with accuracy. Never false.
    kind       — Fact, Rumor or Legend by default (LORE_KINDS).
    affirmation — a visible staff mark that the entry is canon *as described*,
                 pinned to a digest of what was affirmed. Separate from
                 publication, which LORE_REQUIRE_APPROVAL still governs.
    sealed_notes — staff-only notes that unseal into ooc_notes later.

Bridge models (cross-domain, owned by evennia_lore):
    LoreAcquisition      — per-character compendium row (lore ↔ rptracker).
    PlotLoreLink         — links a LoreEntry to a PlotThread (lore ↔ plots).
    LoreSceneLink        — links a LoreEntry to a Scene (lore ↔ scenes).
    LoreRegionLink       — links a LoreEntry to a Region (lore ↔ regions).
    LoreInspirationCredit — per-(LoreSceneLink, character) XP eligibility row.

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
from evennia_lore import layers
from evennia_lore.layers import LoreLayerError

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

    class Accuracy(models.TextChoices):
        ACCURATE = layers.ACCURATE, "Accurate"
        INACCURATE = layers.INACCURATE, "Inaccurate"
        PARTLY = layers.PARTLY, "Partly accurate"
        OPEN = layers.OPEN, "Open"

    class Affirmation(models.TextChoices):
        NONE = "none", "None"
        REQUESTED = "requested", "Affirmation requested"
        AFFIRMED = "affirmed", "Affirmed by staff"
        DECLINED = "declined", "Affirmation declined"

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

    kind = models.CharField(
        max_length=24,
        default="fact",
        db_index=True,
        help_text="How the world treats the content: a key from LORE_KINDS.",
    )
    ooc_notes = models.TextField(
        blank=True,
        help_text="What players should know about the IC content. Never false.",
    )
    accuracy = models.CharField(
        max_length=12,
        choices=Accuracy.choices,
        default=Accuracy.ACCURATE,
        help_text="Whether the IC content is true. Fact kinds are always accurate.",
    )
    affirmation = models.CharField(
        max_length=12,
        choices=Affirmation.choices,
        default=Affirmation.NONE,
        db_index=True,
        help_text="Staff affirmation of the entry as described. Declines show only to the author.",
    )
    affirmed_version = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Highest LoreVersion number when affirmed. The affirmed body is kept as "
            "the next version once the body is edited."
        ),
    )
    affirmed_digest = models.CharField(
        max_length=64,
        blank=True,
        help_text="Digest of the title, summary, body, kind, accuracy and OOC notes affirmed.",
    )
    affirmed_by_name = models.CharField(max_length=255, blank=True)
    affirmed_at = models.DateTimeField(null=True, blank=True)
    affirmation_note = models.CharField(
        max_length=500,
        blank=True,
        help_text="Staff note to the author on a decline. Shown to the author and staff only.",
    )
    sealed_notes = models.TextField(
        blank=True,
        help_text="Staff-only OOC notes. Unsealing appends them to the OOC notes.",
    )

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
    def create_entry(
        cls,
        title,
        author,
        body="",
        summary="",
        privacy=None,
        kind=None,
        accuracy=None,
        ooc_notes="",
    ):
        """
        Create a new LoreEntry, atomically assigning the next entry_number.

        Status defaults to PUBLISHED when LORE_REQUIRE_APPROVAL is False
        (the default); otherwise SUBMITTED. Fires lore_entry_created and
        (when published immediately) lore_entry_published.

        ``kind`` defaults to LORE_DEFAULT_KIND. ``accuracy`` defaults to
        accurate for an always-accurate kind (a Fact) and to open otherwise,
        so an author who never says whether a rumor is true isn't recorded as
        saying it is. The combination must pass ``layers.validate``
        (LoreLayerError if not).

        Retries up to _CREATE_ENTRY_MAX_RETRIES times on unique-number collision
        (race condition on entry_number); raises IntegrityError if exhausted.
        """
        from evennia_lore import signals as lore_signals

        if privacy is None:
            privacy = cls.Privacy.PUBLIC
        kind = kind or layers.default_kind()
        accuracy = accuracy or layers.default_accuracy(kind)
        layers.validate(kind, accuracy, ooc_notes)

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
                        kind=kind,
                        accuracy=accuracy,
                        ooc_notes=ooc_notes,
                    )
            except IntegrityError:
                continue
            else:
                lore_signals.lore_entry_created.send(sender=cls, entry=entry)
                if status == cls.Status.PUBLISHED:
                    lore_signals.lore_entry_published.send(sender=cls, entry=entry)
                return entry

        raise IntegrityError(
            f"Could not allocate a unique entry_number after {_CREATE_ENTRY_MAX_RETRIES} attempts."
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

    # ------------------------------------------------------------------
    # Layers: kind, accuracy and OOC notes
    # ------------------------------------------------------------------

    @property
    def kind_label(self):
        """The kind's display label (LORE_KINDS)."""
        return layers.kind_label(self.kind)

    @property
    def has_sealed_notes(self):
        return bool(self.sealed_notes.strip())

    def update_layers(self, *, kind=None, accuracy=None, ooc_notes=None):
        """Change the kind, accuracy and/or OOC notes together.

        The result must pass ``layers.validate``; otherwise LoreLayerError is
        raised and nothing changes. A kind the game has since removed may stay
        on an entry, but nobody can choose it again.

        Choosing an always-accurate kind (a Fact) for an ``open`` entry settles
        it as accurate, since that is what the choice says. An ``inaccurate``
        or ``partly`` entry is refused instead: that would contradict its notes.

        Returns:
            bool: True if anything changed.
        """
        new_kind = self.kind if kind is None else kind
        new_accuracy = self.accuracy if accuracy is None else accuracy
        if (
            accuracy is None
            and new_kind in layers.accurate_kinds()
            and new_accuracy == self.Accuracy.OPEN
        ):
            new_accuracy = self.Accuracy.ACCURATE
        new_notes = self.ooc_notes if ooc_notes is None else ooc_notes
        layers.validate(
            new_kind,
            new_accuracy,
            new_notes,
            self.sealed_notes,
            check_kind=new_kind != self.kind,
        )
        changed = []
        for name, value in (
            ("kind", new_kind),
            ("accuracy", new_accuracy),
            ("ooc_notes", new_notes),
        ):
            if getattr(self, name) != value:
                setattr(self, name, value)
                changed.append(name)
        if changed:
            self.save(update_fields=[*changed, "updated_at"])
        return bool(changed)

    # ------------------------------------------------------------------
    # Affirmation: a visible staff mark, separate from publication
    # ------------------------------------------------------------------

    @property
    def layer_digest(self):
        """Digest of everything an affirmation vouches for (see layers.digest)."""
        return layers.digest(
            self.title, self.summary, self.body, self.kind, self.accuracy, self.ooc_notes
        )

    @property
    def edited_since_affirmation(self):
        """True when an affirmed entry has changed since staff affirmed it."""
        return (
            self.affirmation == self.Affirmation.AFFIRMED
            and self.affirmed_digest != self.layer_digest
        )

    def affirmation_label(self, show_decline=False):
        """Return the affirmation badge text a viewer sees, or "" for none.

        A decline is shown only with ``show_decline`` (the author and staff):
        everyone else sees no badge, as if nobody had asked.
        """
        if self.affirmation == self.Affirmation.AFFIRMED:
            if self.edited_since_affirmation:
                return "Affirmed by staff, edited since"
            return "Affirmed by staff"
        if self.affirmation == self.Affirmation.REQUESTED:
            return "Affirmation requested"
        if self.affirmation == self.Affirmation.DECLINED and show_decline:
            return "Affirmation declined"
        return ""

    def public_affirmation(self):
        """The affirmation state as anyone but the author and staff may see it."""
        if self.affirmation == self.Affirmation.DECLINED:
            return self.Affirmation.NONE
        return self.affirmation

    def _require_published(self):
        if self.status != self.Status.PUBLISHED:
            raise LoreLayerError(f"#{self.entry_number} isn't published, so it can't be affirmed.")

    def request_affirmation(self, requested_by=None):
        """Ask staff to affirm this entry as described.

        Files the request through LORE_STAFF_REVIEW_HOOK when set; either way
        it waits in ``+lore/queue``. Re-requesting is allowed after a decline,
        or after an edit to an affirmed entry.
        """
        from evennia_lore import signals as lore_signals
        from evennia_lore.notices import file_staff_review

        self._require_published()
        if self.affirmation == self.Affirmation.REQUESTED:
            raise LoreLayerError(f"Affirmation of #{self.entry_number} is already requested.")
        if self.affirmation == self.Affirmation.AFFIRMED and not self.edited_since_affirmation:
            raise LoreLayerError(f"#{self.entry_number} is already affirmed.")
        self.affirmation = self.Affirmation.REQUESTED
        self.affirmation_note = ""
        self.save(update_fields=["affirmation", "affirmation_note"])
        lore_signals.lore_affirmation_changed.send(
            sender=type(self), entry=self, state=self.affirmation, by=requested_by
        )
        who = requested_by.key if requested_by else "Someone"
        file_staff_review(
            f"Lore affirmation requested: #{self.entry_number} {self.title}",
            (
                f"{who} asked staff to affirm lore entry #{self.entry_number} "
                f"'{self.title}' ({self.kind_label}, accuracy: "
                f"{layers.accuracy_label(self.accuracy)}).\n\n"
                "Affirming says the entry is canon as described, OOC notes included. "
                "It never makes a rumor's IC claim true.\n\n"
                f"Affirm with +lore/affirm #{self.entry_number}, or decline with "
                f"+lore/decline #{self.entry_number}=<note to the author>."
            ),
        )

    def affirm(self, affirmed_by=None, notify=True):
        """Affirm the entry as it stands now, and tell its author.

        ``notify=False`` skips the author's notice, for seeded content that
        no one actually decided on.
        """
        from evennia_lore import signals as lore_signals
        from evennia_lore.notices import notify as send_notice

        self._require_published()
        self.affirmation = self.Affirmation.AFFIRMED
        self.affirmed_version = (
            self.versions.aggregate(max_num=Max("version_number")).get("max_num") or 0
        )
        self.affirmed_digest = self.layer_digest
        self.affirmed_by_name = affirmed_by.key if affirmed_by else ""
        self.affirmed_at = timezone.now()
        self.affirmation_note = ""
        self.save(
            update_fields=[
                "affirmation",
                "affirmed_version",
                "affirmed_digest",
                "affirmed_by_name",
                "affirmed_at",
                "affirmation_note",
            ]
        )
        lore_signals.lore_affirmation_changed.send(
            sender=type(self), entry=self, state=self.affirmation, by=affirmed_by
        )
        if notify and self.author_id and self.author != affirmed_by:
            send_notice(
                self.author,
                f"|y[Lore]|n Staff affirmed your lore entry |w{self.title}|n "
                f"(#{self.entry_number}).",
                entry=self,
            )

    def decline(self, declined_by=None, note=""):
        """Decline to affirm the entry, with a note only its author (and staff) see."""
        from evennia_lore import signals as lore_signals
        from evennia_lore.notices import notify

        self._require_published()
        note = (note or "").strip()
        if not note:
            raise LoreLayerError("Say why, so the author knows what would change your mind.")
        self.affirmation = self.Affirmation.DECLINED
        self.affirmation_note = note[:500]
        self.affirmed_version = None
        self.affirmed_digest = ""
        self.affirmed_by_name = declined_by.key if declined_by else ""
        self.affirmed_at = timezone.now()
        self.save(
            update_fields=[
                "affirmation",
                "affirmation_note",
                "affirmed_version",
                "affirmed_digest",
                "affirmed_by_name",
                "affirmed_at",
            ]
        )
        lore_signals.lore_affirmation_changed.send(
            sender=type(self), entry=self, state=self.affirmation, by=declined_by
        )
        if self.author_id and self.author != declined_by:
            notify(
                self.author,
                f"|y[Lore]|n Staff declined to affirm |w{self.title}|n "
                f"(#{self.entry_number}): {self.affirmation_note}",
                entry=self,
            )

    # ------------------------------------------------------------------
    # Sealed notes: OOC truths staff keep until the story settles them
    # ------------------------------------------------------------------

    def seal(self, notes):
        """Replace the sealed notes. Accuracy must already be open.

        Empty *notes* removes the seal without publishing anything.
        """
        notes = (notes or "").strip()
        if notes:
            layers.validate(self.kind, self.accuracy, self.ooc_notes, notes, check_kind=False)
        self.sealed_notes = notes
        self.save(update_fields=["sealed_notes", "updated_at"])

    def unseal(self, accuracy, unsealed_by=None):
        """Publish the sealed notes and settle the accuracy in one step.

        The sealed notes are appended to the OOC notes and the accuracy set to
        *accuracy*. Holders are told (now, or at their next login), and
        ``lore_unsealed`` fires. An entry affirmed and unedited before stays
        affirmed: the unseal is itself a staff action.

        Returns:
            int: How many holders were notified.
        """
        from evennia_lore import signals as lore_signals
        from evennia_lore.notices import notify

        if not self.has_sealed_notes:
            raise LoreLayerError(f"#{self.entry_number} has no sealed notes.")
        sealed = self.sealed_notes.strip()
        current = self.ooc_notes.rstrip()
        notes = f"{current}\n\n{sealed}" if current else sealed
        layers.validate(self.kind, accuracy, notes, "", check_kind=False)

        keep_affirmation = (
            self.affirmation == self.Affirmation.AFFIRMED and not self.edited_since_affirmation
        )
        self.ooc_notes = notes
        self.accuracy = accuracy
        self.sealed_notes = ""
        fields = ["ooc_notes", "accuracy", "sealed_notes", "updated_at"]
        if keep_affirmation:
            self.affirmed_digest = self.layer_digest
            fields.append("affirmed_digest")
        self.save(update_fields=fields)

        lore_signals.lore_unsealed.send(sender=type(self), entry=self, by=unsealed_by)
        message = (
            f"|y[Lore]|n New light on |w{self.title}|n (#{self.entry_number}): "
            f"its OOC notes have been unsealed. Use |w+lore/read #{self.entry_number}|n."
        )
        holders = 0
        for acquisition in self.acquisitions.select_related("character"):
            notify(acquisition.character, message, entry=self)
            holders += 1
        return holders

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


class LoreInspirationCredit(models.Model):
    """
    Per-(LoreSceneLink, character) eligibility row for lore inspiration XP.

    Created (get_or_created) by collect_lore_inspiration() in
    evennia_lore.integrations.xp when the weekly XP batch runs. One row
    per (link, character_id) pair — its pk is used as source_ref_id so
    XPLog's (source_type, source_ref_id) unique constraint guarantees
    idempotency across batch re-runs even without a flag field on LoreSceneLink.

    character_name is denormalized for display after character deletion.
    """

    link = models.ForeignKey(
        LoreSceneLink,
        on_delete=models.CASCADE,
        related_name="inspiration_credits",
        help_text="The LoreSceneLink that generated this credit.",
    )
    character_id = models.PositiveIntegerField(
        db_index=True,
        help_text="ObjectDB pk of the character who receives the inspiration credit.",
    )
    character_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized character name for display after deletion.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("link", "character_id")]  # noqa: RUF012
        ordering = ["created_at"]  # noqa: RUF012

    def __str__(self):
        return f"LoreInspirationCredit: {self.character_name} ← LoreSceneLink #{self.link_id}"


class LoreNotice(models.Model):
    """
    An OOC lore notice kept for a character who was offline when it was sent.

    Created by ``evennia_lore.notices.notify`` and delivered (then deleted)
    the next time the character is puppeted. Unseal notices to holders and
    affirmation decisions to authors use it.
    """

    character = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.CASCADE,
        related_name="+",
        help_text="The character the notice is for.",
    )
    entry = models.ForeignKey(
        LoreEntry,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notices",
        help_text="The entry the notice is about, if any.",
    )
    message = models.TextField(help_text="The notice, formatted for the game.")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]  # noqa: RUF012

    def __str__(self):
        return f"LoreNotice for #{self.character_id} ({self.created_at:%Y-%m-%d})"
