# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
PlotThread, PlotArc, and related models for evennia_plots.

Plot threads are named narrative containers linking Scenes, board Posts,
CalendarEvents, and Lore entries into a storyline. Plot arcs are higher-level
staff-only containers grouping multiple threads.

Design notes:

- plot_number / arc_number are globally auto-incrementing (never reuse) so
  players and staff can reference any thread or arc by a short, stable ID.
- description is a brief tagline (max 500 chars). Evolving narrative detail
  lives in append-only PlotUpdate blocks.
- IC PlotUpdate blocks are public (per-thread privacy rules). OOC blocks are
  restricted to participants, invited characters, and staff.
- bonus_xp_computed is filled on conclusion (0–5 XP); awarded by the XP batch
  (registered via XP_COLLECTORS in your settings).
- All ObjectDB FKs pair with a denormalized *_name CharField.
- PlotTag supports staff-defined major tags ("Magic", "Politics") and
  free-form player-created minor tags ("The Reavers", "Flamescales").

Bridge models included here (forced relocate from the hub's links layer):

- ScenePlotLink    — Scene (integer soft-ref) ↔ PlotThread
- PlotCalendarLink — PlotThread ↔ CalendarEvent (integer soft-ref)
- PlotBoardLink    — PlotThread ↔ board Post (integer soft-ref + is_ic_post)
- PlotBonusCredit  — per-(thread, character) XP-eligibility row
"""  # noqa: RUF002

from datetime import timedelta
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Max, Q
from django.utils import timezone

from evennia_links import AbstractAuthoredLink, AbstractVersion
from evennia_plots import signals as plot_signals
from evennia_plots.permissions import is_plot_staff

# ---------------------------------------------------------------------------
# PlotTag
# ---------------------------------------------------------------------------


class PlotTag(models.Model):
    """A tag applied to PlotThreads and PlotArcs.

    Major tags (is_major=True) are staff-defined and provide a canonical
    thematic taxonomy (e.g. "Magic", "Politics", "Religion"). Minor tags
    are player-created free-form labels.

    Tag creation is implicit: the create command creates the tag if it does
    not already exist. Staff can flag a tag as major.
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
    created_by_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_major", "name"]  # noqa: RUF012

    def __str__(self):
        kind = "Major" if self.is_major else "Minor"
        return f"[{kind}] {self.name}"


# ---------------------------------------------------------------------------
# PlotArc (defined before PlotThread so PlotThread can FK to it)
# ---------------------------------------------------------------------------


class PlotArc(models.Model):
    """A higher-level container grouping multiple PlotThreads into a storyline.

    Staff-only creation. Not required for player-driven thread connections
    (use ThreadLink for sequel/related links instead).

    Arc narrative detail lives in append-only PlotUpdate blocks. The
    description field is a brief tagline only.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CONCLUDED = "concluded", "Concluded"
        ARCHIVED = "archived", "Archived"

    class ArcType(models.TextChoices):
        STORY = "story", "Story"
        DOWNTIME = "downtime", "Downtime"

    arc_number = models.PositiveIntegerField(
        unique=True,
        help_text="Auto-incremented globally. Used as the human-readable arc ID.",
    )
    name = models.CharField(max_length=255, db_index=True)
    description = models.CharField(
        max_length=500,
        blank=True,
        help_text="Brief tagline. Evolving narrative detail lives in PlotUpdate blocks.",
    )
    tags = models.ManyToManyField(PlotTag, blank=True, related_name="arcs")
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    creator = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Staff member who created the arc.",
    )
    creator_name = models.CharField(max_length=255, blank=True)
    arc_type = models.CharField(
        max_length=12,
        choices=ArcType.choices,
        default=ArcType.STORY,
        db_index=True,
    )
    is_current = models.BooleanField(
        default=False,
        help_text="Exactly one arc may be current at a time (partial unique constraint).",
    )
    # Per-arc XP multiplier overrides. NULL = use type default.
    # STORY default = 1.0 for all sources; DOWNTIME default = 0.0 for all.
    _xp_mult_validators = [MinValueValidator(Decimal("0"))]  # noqa: RUF012
    xp_mult_rp_session = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=_xp_mult_validators,
        help_text="XP multiplier for RP session awards. Blank = type default.",
    )
    xp_mult_cutscene = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=_xp_mult_validators,
        help_text="XP multiplier for cutscene post awards. Blank = type default.",
    )
    xp_mult_lore = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=_xp_mult_validators,
        help_text="XP multiplier for lore contribution awards. Blank = type default.",
    )
    xp_mult_thread_bonus = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=_xp_mult_validators,
        help_text="XP multiplier for plot-thread conclusion bonus. Blank = type default.",
    )
    # Seam for a future IC-channel session collector. NULL = type default.
    xp_mult_rp_channel_session = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=_xp_mult_validators,
        help_text="XP multiplier for IC-channel session awards. Blank = type default.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    concluded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]  # noqa: RUF012
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["is_current"],
                condition=Q(is_current=True),
                name="evennia_plots_plotarc_one_current_global",
            )
        ]

    def __str__(self):
        return f"Arc #{self.arc_number}: {self.name}"

    @property
    def pauses_xp(self):
        """True when this arc type suppresses XP gain (Downtime arcs only).

        UI intent signal for banners/badges. The behavioral gate is
        get_xp_multiplier() / resolve_xp_multiplier() from evennia_plots.gating.
        """
        return self.arc_type == self.ArcType.DOWNTIME

    # ------------------------------------------------------------------
    # XP multiplier resolution
    # ------------------------------------------------------------------

    XP_SOURCES = (
        "rp_session",
        "cutscene",
        "lore",
        "thread_bonus",
        "rp_channel_session",
    )

    XP_SOURCE_LABELS = {  # noqa: RUF012
        "rp_session": "RP Session",
        "cutscene": "Cutscene",
        "lore": "Lore",
        "thread_bonus": "Thread Bonus",
        "rp_channel_session": "RP Channel Session",
    }

    TYPE_DEFAULT_MULTIPLIERS = {  # noqa: RUF012
        ArcType.STORY: {s: Decimal("1.0") for s in XP_SOURCES},
        ArcType.DOWNTIME: {s: Decimal("0.0") for s in XP_SOURCES},
    }

    def get_xp_multiplier(self, source: str) -> Decimal:
        """Return the active XP multiplier for *source*: per-arc override or type default.

        Args:
            source: One of XP_SOURCES.

        Returns:
            Decimal multiplier (1.0 = full, 0.0 = paused, 2.0 = doubled).

        Raises:
            ValueError: if *source* is not in XP_SOURCES.
        """
        if source not in self.XP_SOURCES:
            raise ValueError(f"Unknown XP source {source!r}. Valid: {', '.join(self.XP_SOURCES)}")
        override = getattr(self, f"xp_mult_{source}")
        if override is not None:
            return override
        return self.TYPE_DEFAULT_MULTIPLIERS[self.arc_type][source]

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create_arc(cls, name, creator, description="", arc_type=None):
        """Create a new PlotArc with an auto-assigned arc_number.

        Args:
            name: Arc name.
            creator: ObjectDB character instance (staff).
            description: Brief tagline (optional).
            arc_type: One of ArcType choices; defaults to STORY.

        Returns:
            The newly created PlotArc instance.
        """
        if arc_type is None:
            arc_type = cls.ArcType.STORY
        current_max = cls.objects.aggregate(max_num=Max("arc_number")).get("max_num") or 0
        arc = cls.objects.create(
            arc_number=current_max + 1,
            name=name,
            description=description,
            arc_type=arc_type,
            creator=creator,
            creator_name=creator.key if creator else "Unknown",
        )
        return arc

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def conclude(self):
        """Transition to CONCLUDED, auto-clearing is_current if set."""
        update_fields = ["status", "concluded_at"]
        self.status = self.Status.CONCLUDED
        self.concluded_at = timezone.now()
        was_current = self.is_current
        if was_current:
            self.is_current = False
            update_fields.append("is_current")
        self.save(update_fields=update_fields)
        if was_current:
            plot_signals.arc_currency_changed.send(
                sender=type(self), arc=self, became_current=False
            )

    def archive(self):
        """Transition to ARCHIVED."""
        self.status = self.Status.ARCHIVED
        self.save(update_fields=["status"])


# ---------------------------------------------------------------------------
# PlotThread
# ---------------------------------------------------------------------------


class PlotThread(models.Model):
    """A named narrative container linking Scenes, Posts, CalendarEvents, and Lore.

    Status lifecycle::

        proposed → active → concluded  (intentional wrap-up; bonus XP awarded)
                          → archived   (stale; no bonus)

    Privacy modes:

    - PUBLIC      — anyone can view and link content
    - PRIVATE     — only creator (and staff) can view and link
    - INVITE_ONLY — anyone can view; only creator and invited characters can link

    Bonus XP (computed at conclusion, max 5):

    - +3  Any linked CalendarEvent had advance_notice_met=True when linked.
    - +1  At least two linked scenes.
    - +1  At least one PlotBoardLink with is_ic_post=True.

    bonus_xp_computed is stored on conclusion; bonus_xp_awarded flips to True
    after the XP batch distributes the bonus to PlotParticipants.
    """

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        ACTIVE = "active", "Active"
        CONCLUDED = "concluded", "Concluded"
        ARCHIVED = "archived", "Archived"

    class Privacy(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private"
        INVITE_ONLY = "invite_only", "Invite-Only"

    plot_number = models.PositiveIntegerField(
        unique=True,
        help_text="Auto-incremented globally. Used as the human-readable thread ID.",
    )
    name = models.CharField(max_length=255, db_index=True)
    description = models.CharField(
        max_length=500,
        blank=True,
        help_text="Brief tagline. Evolving narrative detail lives in PlotUpdate blocks.",
    )
    tags = models.ManyToManyField(PlotTag, blank=True, related_name="threads")
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PROPOSED,
        db_index=True,
    )
    privacy = models.CharField(
        max_length=12,
        choices=Privacy.choices,
        default=Privacy.PUBLIC,
        db_index=True,
    )
    creator = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The character who created the thread.",
    )
    creator_name = models.CharField(max_length=255, blank=True)
    arc = models.ForeignKey(
        PlotArc,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="threads",
        help_text="Optional parent arc (staff-assigned).",
    )
    invited_characters = models.ManyToManyField(
        "objects.ObjectDB",
        blank=True,
        related_name="evennia_plots_invites",
        help_text="Characters explicitly invited to link content (invite_only threads).",
    )
    # Anti-favoritism audit log. JSON list of {staff, target, at} entries.
    hook_log = models.JSONField(
        default=list,
        blank=True,
        help_text="Staff-visible record of +hook calls targeting this thread.",
    )
    bonus_xp_computed = models.SmallIntegerField(
        default=0,
        help_text="Computed at conclusion (0–5). Distributed by the XP batch.",  # noqa: RUF001
    )
    bonus_xp_awarded = models.BooleanField(
        default=False,
        help_text="Flipped to True after the XP batch distributes the bonus.",
    )
    bonus_xp_flag_reason = models.CharField(
        max_length=500,
        blank=True,
        help_text="Set by anti-gaming sweep when thread was concluded too quickly.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    concluded_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]  # noqa: RUF012

    def __str__(self):
        return f"#{self.plot_number} {self.name}"

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create_thread(cls, name, creator, description="", privacy="public"):
        """Create a new PlotThread with an auto-assigned plot_number.

        Args:
            name: Thread name.
            creator: ObjectDB character instance.
            description: Brief tagline (optional).
            privacy: One of "public", "private", "invite_only".

        Returns:
            The newly created PlotThread instance.
        """
        current_max = cls.objects.aggregate(max_num=Max("plot_number")).get("max_num") or 0
        thread = cls.objects.create(
            plot_number=current_max + 1,
            name=name,
            description=description,
            privacy=privacy,
            creator=creator,
            creator_name=creator.key if creator else "Unknown",
        )
        plot_signals.plot_thread_created.send(sender=cls, thread=thread)
        return thread

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def activate(self):
        """Transition from PROPOSED to ACTIVE."""
        self.status = self.Status.ACTIVE
        self.save(update_fields=["status"])
        plot_signals.plot_thread_activated.send(sender=type(self), thread=self)

    def conclude(self, concluded_by=None):
        """Transition to CONCLUDED, compute bonus XP, and fire the signal.

        Args:
            concluded_by: ObjectDB character who concluded the thread (optional).

        Returns:
            int: The computed bonus XP (0–5).
        """  # noqa: RUF002
        bonus = self._compute_bonus_xp()
        self.bonus_xp_computed = bonus
        self.status = self.Status.CONCLUDED
        self.concluded_at = timezone.now()
        self.save(update_fields=["status", "concluded_at", "bonus_xp_computed"])
        plot_signals.plot_thread_concluded.send(sender=type(self), thread=self, bonus_xp=bonus)
        return bonus

    def archive(self):
        """Transition to ARCHIVED (no bonus)."""
        self.status = self.Status.ARCHIVED
        self.archived_at = timezone.now()
        self.save(update_fields=["status", "archived_at"])
        plot_signals.plot_thread_archived.send(sender=type(self), thread=self)

    # ------------------------------------------------------------------
    # Bonus XP
    # ------------------------------------------------------------------

    def _compute_bonus_xp(self):
        """Evaluate the three-item bonus checklist and return the total (0–5).

        Checklist:

        - +3  Any linked CalendarEvent had advance_notice_met=True.
        - +1  Thread has 2 or more linked scenes.
        - +1  Thread has at least one PlotBoardLink with is_ic_post=True.

        Returns:
            int: Total bonus XP (0–5).
        """  # noqa: RUF002
        total = 0
        if self.calendar_links.filter(advance_notice_met=True).exists():
            total += 3
        if self.scene_links.count() >= 2:
            total += 1
        if self.board_links.filter(is_ic_post=True).exists():
            total += 1
        return total

    @property
    def bonus_xp_should_award(self):
        """True when there is bonus XP to give and the arc's thread_bonus mult > 0."""
        if self.bonus_xp_computed <= 0:
            return False
        from evennia_plots.gating import resolve_xp_multiplier

        return resolve_xp_multiplier("thread_bonus", thread=self) > 0

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    def can_link(self, character):
        """Return True if *character* may link content to this thread.

        Rules:

        - Thread must be ACTIVE.
        - PUBLIC: anyone may link.
        - PRIVATE: only creator and staff.
        - INVITE_ONLY: creator, invited characters, and staff.
        """
        if self.status != self.Status.ACTIVE:
            return False
        if is_plot_staff(character):
            return True
        if self.creator_id and character.id == self.creator_id:
            return True
        if self.privacy == self.Privacy.PUBLIC:
            return True
        if self.privacy == self.Privacy.INVITE_ONLY:
            return self.invited_characters.filter(pk=character.pk).exists()
        return False

    def can_view(self, character):
        """Return True if *character* may view this thread.

        PUBLIC and INVITE_ONLY threads are visible to all.
        PRIVATE threads are visible only to creator and staff.
        """
        if self.privacy != self.Privacy.PRIVATE:
            return True
        if character is None:
            return False
        if is_plot_staff(character):
            return True
        return self.creator_id and character.id == self.creator_id

    def is_participant(self, character):
        """Return True if *character* is a participant, creator, or invited."""
        if character is None:
            return False
        if self.creator_id and character.id == self.creator_id:
            return True
        if self.invited_characters.filter(pk=character.pk).exists():
            return True
        return self.participants.filter(character=character, is_active=True).exists()

    def can_update(self, character):
        """Return True if *character* may append PlotUpdate blocks."""
        if self.status != self.Status.ACTIVE:
            return False
        return self.is_participant(character) or is_plot_staff(character)

    def edit(self, editor, name=None, description=None, privacy=None):
        """Update editable fields and fire plot_thread_edited.

        Args:
            editor: ObjectDB character making the edit.
            name: New name, or None to leave unchanged.
            description: New description, or None to leave unchanged.
            privacy: New privacy value, or None to leave unchanged.
        """
        update_fields = []
        if name is not None:
            self.name = name
            update_fields.append("name")
        if description is not None:
            self.description = description
            update_fields.append("description")
        if privacy is not None:
            self.privacy = privacy
            update_fields.append("privacy")
        if update_fields:
            self.save(update_fields=update_fields)
        plot_signals.plot_thread_edited.send(sender=type(self), thread=self, editor=editor)


# ---------------------------------------------------------------------------
# PlotParticipant
# ---------------------------------------------------------------------------


class PlotParticipant(models.Model):
    """Tracks who has participated in a PlotThread.

    Auto-created (get_or_create) by the scene_linked_to_thread signal listener
    when a Scene is linked: each SceneParticipant of the linked scene becomes
    a PlotParticipant. Players can also become participants by posting a
    PlotUpdate.

    Uniqueness: one record per (thread, character) pair.
    """

    thread = models.ForeignKey(
        PlotThread,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    character = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    character_name = models.CharField(max_length=255, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("thread", "character")]  # noqa: RUF012
        ordering = ["joined_at"]  # noqa: RUF012

    def __str__(self):
        return f"{self.character_name} → {self.thread}"


# ---------------------------------------------------------------------------
# PlotUpdate
# ---------------------------------------------------------------------------


class PlotUpdate(models.Model):
    """An append-only narrative journal block for a PlotThread or PlotArc.

    IC blocks are visible to all viewers who can see the thread.
    OOC blocks are restricted to participants, invited characters, and staff.

    block_number is sequential per thread (or per arc) and is used in edit
    commands. Editing sets edited_at; no full version history by default —
    the sequence of blocks IS the history. PlotUpdateVersion can be layered on
    for richer edit-history.
    """

    class UpdateType(models.TextChoices):
        IC = "ic", "IC"
        OOC = "ooc", "OOC"

    thread = models.ForeignKey(
        PlotThread,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="updates",
    )
    arc = models.ForeignKey(
        PlotArc,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="updates",
    )
    update_type = models.CharField(
        max_length=3,
        choices=UpdateType.choices,
        default=UpdateType.IC,
    )
    content = models.TextField()
    author = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    author_name = models.CharField(max_length=255, blank=True)
    block_number = models.PositiveSmallIntegerField(
        help_text="Sequential per thread or arc. Used in edit commands.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]  # noqa: RUF012

    def __str__(self):
        parent = f"Thread #{self.thread_id}" if self.thread_id else f"Arc #{self.arc_id}"
        return f"{parent} Block {self.block_number} [{self.update_type}]"

    def clean(self):
        from django.core.exceptions import ValidationError

        if bool(self.thread_id) == bool(self.arc_id):
            raise ValidationError("Exactly one of 'thread' or 'arc' must be set on a PlotUpdate.")

    @classmethod
    def create_update(cls, parent, author, content, update_type="ic"):
        """Append a new PlotUpdate block, auto-assigning block_number.

        Args:
            parent: A PlotThread or PlotArc instance.
            author: ObjectDB character instance.
            content: The update text.
            update_type: "ic" or "ooc".

        Returns:
            The newly created PlotUpdate instance.
        """
        if isinstance(parent, PlotThread):
            current_max = (
                cls.objects.filter(thread=parent).aggregate(m=Max("block_number")).get("m") or 0
            )
            update = cls.objects.create(
                thread=parent,
                update_type=update_type,
                content=content,
                author=author,
                author_name=author.key if author else "Unknown",
                block_number=current_max + 1,
            )
        else:
            current_max = (
                cls.objects.filter(arc=parent).aggregate(m=Max("block_number")).get("m") or 0
            )
            update = cls.objects.create(
                arc=parent,
                update_type=update_type,
                content=content,
                author=author,
                author_name=author.key if author else "Unknown",
                block_number=current_max + 1,
            )
        plot_signals.plot_update_created.send(sender=cls, update=update)
        return update


# ---------------------------------------------------------------------------
# PlotUpdateVersion
# ---------------------------------------------------------------------------


class PlotUpdateVersion(AbstractVersion):
    """Version snapshot for a PlotUpdate block.

    Stores the OLD content before each edit. The live content lives on
    PlotUpdate.content. Version numbers are sequential per parent update.
    """

    parent = models.ForeignKey(
        PlotUpdate,
        on_delete=models.CASCADE,
        related_name="versions",
    )

    class Meta(AbstractVersion.Meta):
        unique_together = [("parent", "version_number")]  # noqa: RUF012


# ---------------------------------------------------------------------------
# ThreadLink
# ---------------------------------------------------------------------------


class ThreadLink(models.Model):
    """Directional sequel or related-story connection between two PlotThreads.

    Sequel links (link_type="sequel") are unidirectional, creator-initiated,
    and immediately accepted.

    Related links (link_type="related") require acceptance from the to_thread's
    creator. On acceptance, a mirrored reverse link is created automatically.
    Staff may accept any pending related link.
    """

    class LinkType(models.TextChoices):
        SEQUEL = "sequel", "Sequel"
        RELATED = "related", "Related"

    from_thread = models.ForeignKey(
        PlotThread,
        on_delete=models.CASCADE,
        related_name="outgoing_links",
    )
    to_thread = models.ForeignKey(
        PlotThread,
        on_delete=models.CASCADE,
        related_name="incoming_links",
    )
    link_type = models.CharField(
        max_length=8,
        choices=LinkType.choices,
        default=LinkType.RELATED,
    )
    created_by = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_by_name = models.CharField(max_length=255, blank=True)
    is_accepted = models.BooleanField(
        default=False,
        help_text="True for sequel links (immediate) or accepted related links.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("from_thread", "to_thread")]  # noqa: RUF012
        ordering = ["created_at"]  # noqa: RUF012

    def __str__(self):
        status = "accepted" if self.is_accepted else "pending"
        return f"{self.from_thread} —[{self.link_type}/{status}]→ {self.to_thread}"

    def accept(self, accepted_by=None):
        """Accept a pending related link and create the mirrored reverse link.

        Args:
            accepted_by: ObjectDB character accepting the link (optional).
        """
        self.is_accepted = True
        self.save(update_fields=["is_accepted"])
        ThreadLink.objects.get_or_create(
            from_thread=self.to_thread,
            to_thread=self.from_thread,
            defaults={
                "link_type": self.LinkType.RELATED,
                "created_by": accepted_by,
                "created_by_name": accepted_by.key if accepted_by else "System",
                "is_accepted": True,
            },
        )
        plot_signals.thread_link_accepted.send(sender=type(self), link=self)


# ---------------------------------------------------------------------------
# Bridge models (relocated from the hub's links layer — forced divergence)
# ---------------------------------------------------------------------------
# These would live in a shared links/bridges layer in a monorepo, but evennia
# spoke contribs own their bridges so they install without requiring every
# sibling contrib. All cross-system FK edges are integer soft-references;
# cascade compensation is registered in PlotsConfig.ready() via
# evennia_links.connect_soft_ref_cleanup.
# ---------------------------------------------------------------------------


class ScenePlotLink(AbstractAuthoredLink):
    """Links a Scene (integer soft-ref) to a PlotThread.

    On creation fires the scene_linked_to_thread signal so that
    PlotsConfig.ready() can auto-create PlotParticipant records for all
    SceneParticipants of the linked scene.

    The scene reference is an integer soft-ref (scene_id); no DB dependency
    on the scenes app. Hard-deletion of a Scene is compensated by the
    connect_soft_ref_cleanup hook registered in PlotsConfig.ready().

    Uniqueness: one link per (scene_id, thread) pair.
    """

    scene_id = models.PositiveBigIntegerField(
        db_index=True,
        help_text="PK of the Scene linked to this plot thread.",
    )
    thread = models.ForeignKey(
        PlotThread,
        on_delete=models.CASCADE,
        related_name="scene_links",
    )

    link_fields = ("scene_id", "thread")

    class Meta(AbstractAuthoredLink.Meta):
        unique_together = [("scene_id", "thread")]  # noqa: RUF012

    def __str__(self):
        return f"Scene #{self.scene_id} ↔ PlotThread #{self.thread_id}"

    @classmethod
    def create_link(cls, scene, thread, linked_by=None):
        """Create a ScenePlotLink and fire scene_linked_to_thread.

        Accepts a Scene instance (so the signal carries the object) but stores
        only scene.pk as the integer soft-reference. Idempotent via get_or_create;
        the signal fires only on actual creation.

        Args:
            scene: Scene instance.
            thread: PlotThread instance.
            linked_by: ObjectDB character creating the link (optional).

        Returns:
            tuple: (ScenePlotLink instance, created bool)
        """
        from evennia_plots.signals import scene_linked_to_thread

        link, created = super().create_link(scene.pk, thread, linked_by=linked_by)
        if created:
            scene_linked_to_thread.send(
                sender=cls,
                thread=thread,
                scene=scene,
                linked_by=linked_by,
            )
        return link, created


class PlotCalendarLink(AbstractAuthoredLink):
    """Links a PlotThread to a CalendarEvent (integer soft-ref).

    advance_notice_met is evaluated and stored at link-creation time: True if
    the event's scheduled_time is at least 7 days after the moment of linking.
    Used by PlotThread._compute_bonus_xp() to award the +3 XP bonus.

    Uniqueness: one link per (thread, event_id) pair.
    """

    thread = models.ForeignKey(
        PlotThread,
        on_delete=models.CASCADE,
        related_name="calendar_links",
    )
    event_id = models.PositiveBigIntegerField(
        db_index=True,
        help_text="PK of the CalendarEvent linked to this plot thread.",
    )
    advance_notice_met = models.BooleanField(
        default=False,
        help_text=(
            "True if the event was scheduled 7+ days after this link was created. "
            "Evaluated at link-creation time; used for the +3 XP bonus."
        ),
    )

    link_fields = ("thread", "event_id")

    class Meta(AbstractAuthoredLink.Meta):
        unique_together = [("thread", "event_id")]  # noqa: RUF012

    def __str__(self):
        notice = " [notice met]" if self.advance_notice_met else ""
        return f"PlotThread #{self.thread_id} ↔ CalendarEvent #{self.event_id}{notice}"

    @classmethod
    def create_link(cls, thread, event, linked_by=None):
        """Create a PlotCalendarLink, computing advance_notice_met at creation time.

        Accepts a CalendarEvent instance (to read scheduled_time) but stores
        only event.pk as the integer soft-reference.

        Args:
            thread: PlotThread instance.
            event: CalendarEvent instance.
            linked_by: ObjectDB character creating the link (optional).

        Returns:
            tuple: (PlotCalendarLink instance, created bool)
        """
        advance_notice_met = (event.scheduled_time - timezone.now()) >= timedelta(days=7)
        return super().create_link(
            thread, event.pk, linked_by=linked_by, advance_notice_met=advance_notice_met
        )


class PlotBoardLink(AbstractAuthoredLink):
    """Links a PlotThread to a board Post (integer soft-ref).

    IC-board posts count toward the cutscene bonus (+1 XP) in
    PlotThread._compute_bonus_xp(). is_ic_post is captured at link-creation
    time from post.board.board_type so that the bonus check does not require
    traversing the post FK after deletion.

    Uniqueness: one link per (thread, post_id) pair.
    """

    thread = models.ForeignKey(
        PlotThread,
        on_delete=models.CASCADE,
        related_name="board_links",
    )
    post_id = models.PositiveBigIntegerField(
        db_index=True,
        help_text="PK of the board Post linked to this plot thread.",
    )
    is_ic_post = models.BooleanField(
        default=False,
        help_text=(
            "True if the linked post belonged to an IC-type board at link-creation "
            "time. Used by _compute_bonus_xp() to award the +1 cutscene bonus."
        ),
    )

    link_fields = ("thread", "post_id")

    class Meta(AbstractAuthoredLink.Meta):
        unique_together = [("thread", "post_id")]  # noqa: RUF012

    def __str__(self):
        return f"PlotThread #{self.thread_id} ↔ Post #{self.post_id}"

    @classmethod
    def create_link(cls, thread, post, linked_by=None):
        """Create a PlotBoardLink, capturing is_ic_post at creation time.

        Accepts a Post instance (to read board.board_type) but stores only
        post.pk as the integer soft-reference. Idempotent via get_or_create.

        Args:
            thread: PlotThread instance.
            post: Post instance.
            linked_by: ObjectDB character creating the link (optional).

        Returns:
            tuple: (PlotBoardLink instance, created bool)
        """
        is_ic_post = post.board.board_type == "ic"
        return super().create_link(thread, post.pk, linked_by=linked_by, is_ic_post=is_ic_post)


class PlotBonusCredit(models.Model):
    """Per-(PlotThread, character) eligibility row for plot thread bonus XP.

    The XP batch creates one row for each PlotParticipant when a concluded
    PlotThread with bonus_xp_computed > 0 is processed. The row's pk is used
    as XPLog.source_ref_id for the THREAD_BONUS award, providing idempotency
    via XPLog's (source_type, source_ref_id) constraint.

    character_id is an integer soft-reference so PlotBonusCredit has no DB
    dependency on ObjectDB beyond the thread FK.
    """

    thread = models.ForeignKey(
        PlotThread,
        on_delete=models.CASCADE,
        related_name="bonus_credits",
        help_text="The PlotThread that generated this bonus credit.",
    )
    character_id = models.PositiveIntegerField(
        db_index=True,
        help_text="ObjectDB pk of the character who receives the bonus credit.",
    )
    character_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized character name for display after deletion.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("thread", "character_id")]  # noqa: RUF012
        ordering = ["created_at"]  # noqa: RUF012

    def __str__(self):
        return f"PlotBonusCredit: {self.character_name} ← PlotThread #{self.thread_id}"
