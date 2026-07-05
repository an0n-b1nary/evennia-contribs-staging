# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Event Calendar models for evennia_calendar.

Models:
- EventTag: reusable thematic tags (e.g. "Arcane", "Military"). Staff-managed
  canonical list prevents name drift. Many-to-many on CalendarEvent.
- EventCluster: groups 2+ CalendarEvents for ranked-choice RSVP. Example use
  case: 3 parallel staff scenes (battle/stealth/decoy) for one plot night
  where players rank their scene preferences and the lottery distributes them.
- CalendarEvent: a scheduled event with title, description, UTC time, creator,
  cap, emphasis, is_staff_event flag, optional tags, and optional cluster.
- ClusterRSVP: a player's ranked-choice ticket for an EventCluster. One per
  (cluster, character). Status tracks draw outcome.
- ClusterRSVPPreference: through-model holding a player's ordered event
  preferences within a ClusterRSVP (rank 1 = most desired).
- RSVP: a player's concrete attendance record for a single CalendarEvent.
  Status tracks the full RSVP pipeline (open / capped / lottery flows).
  For clustered events, created by the lottery and linked back to the
  ClusterRSVP ticket that produced it.
- PriorityToken: lottery consolation guarantee. Issued to players excluded from
  a staff event lottery. Guarantees their rank-1 placement in the next staff
  event (or cluster) they enter. Two scopes: EVENT and CLUSTER_RANK1. Never
  expire. One redeemable per event/draw.
- EventExclusion: optional mutual-exclusion pair for standalone events.
  Redundant within a cluster (seating is one-per-player by construction) but
  useful for events in different clusters or cross-cluster scenarios.
- SceneCalendarLink: cross-domain bridge (owned here) linking a CalendarEvent
  to a Scene via a scene_id integer soft-reference (lore ↔ scenes).

ObjectDB FK convention: ForeignKey("objects.ObjectDB",
on_delete=SET_NULL, null=True) + denormalized *_name CharField. Prevents
display breakage if the referenced character is later deleted.

No AbstractArchived (use is_cancelled — events have a point in time).
No AbstractVersion (descriptions are not version-tracked at this layer).
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from evennia_links import AbstractAuthoredLink

# ---------------------------------------------------------------------------
# EventTag
# ---------------------------------------------------------------------------


class EventTag(models.Model):
    """
    Reusable thematic tag for classifying event narrative content.

    Tags are orthogonal to emphasis: a "Military" event may have Combat
    *or* Social emphasis depending on whether it is a battle or a parade.

    Staff-managed canonical list: creating, renaming, and merging tags is
    a staff-only action (+calendar/tag) to prevent freeform drift.
    """

    name = models.CharField(max_length=60, unique=True)
    description = models.TextField(
        blank=True,
        help_text="Optional explanation of when to apply this tag.",
    )

    class Meta:
        ordering = ["name"]  # noqa: RUF012

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# EventCluster
# ---------------------------------------------------------------------------


class EventCluster(models.Model):
    """
    A named group of related CalendarEvents using ranked-choice RSVP.

    Example: 3 parallel staff scenes (Battle / Stealth / Decoy) for one
    plot night. Players RSVP with a ranked preference list; the lottery
    distributes them by preference subject to per-event capacity.

    Lifecycle:
    1. Staff create the cluster and add events (is_locked=False).
    2. Staff lock it once all events are added and RSVPs are open
       (+calendar/cluster/lock). Locks prevent membership changes and arm
       the scheduler to run the draw at lottery_draw_time.
    3. The scheduler runs run_cluster_lottery() which seats players by rank.
    4. Players confirm their concrete RSVP on the assigned member event.

    Validation:
    - All member events must share the same is_staff_event flag. Mixed
      clusters (some staff, some player events) break the anti-favoritism
      invite rule, so clean() rejects them.
    """

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    creator = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The character who created this cluster.",
    )
    creator_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized creator name for display after deletion.",
    )

    is_locked = models.BooleanField(
        default=False,
        help_text=(
            "Once True, no events can be added/removed. The cluster lottery "
            "draw is armed and will run at the earliest member event's 72h "
            "draw window."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]  # noqa: RUF012

    def __str__(self):
        return f"Cluster: {self.title}"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def draw_time(self):
        """
        Earliest lottery_draw_time across member events, or None if no events.

        This is when the scheduler should run run_cluster_lottery().
        """
        events = self.events.filter(is_cancelled=False)
        times = [e.lottery_draw_time for e in events if e.lottery_draw_time]
        return min(times) if times else None

    @property
    def has_run(self):
        """True if any member event has lottery_drawn_at set."""
        return self.events.filter(lottery_drawn_at__isnull=False).exists()

    @property
    def rsvp_count(self):
        """Total ClusterRSVP entries (pending + resolved)."""
        return self.cluster_rsvps.count()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def clean(self):
        """
        Validate cluster invariants.

        1. All member events must share ``is_staff_event`` state. Mixed
           clusters break the anti-favoritism guarantee: if some events
           are staff events and others are player events, the invite-block
           for staff accounts cannot be applied uniformly.
        2. All member events must share the same ``scheduled_time``. The
           ranked-choice lottery assumes parallelism (one seat per player
           across the cluster), and ``has_run`` is boolean — it cannot
           represent "some drew, some didn't."
        """
        event_qs = (
            self.events.filter(is_cancelled=False) if self.pk else CalendarEvent.objects.none()
        )
        staff_flags = set(event_qs.values_list("is_staff_event", flat=True))
        if len(staff_flags) > 1:
            raise ValidationError(
                "All events in a cluster must share the same is_staff_event "
                "flag. Mixed staff/player-event clusters are not allowed."
            )
        scheduled_times = set(event_qs.values_list("scheduled_time", flat=True))
        if len(scheduled_times) > 1:
            raise ValidationError(
                "All events in a cluster must share the same scheduled_time. "
                "The ranked-choice lottery assumes parallel events."
            )


# ---------------------------------------------------------------------------
# CalendarEvent
# ---------------------------------------------------------------------------


class CalendarEvent(models.Model):
    """
    A single scheduled event.

    Events have an emphasis category describing mechanical focus (Combat,
    Skill, Social, Freeform) and optional thematic tags (e.g. 'Arcane',
    'Military'). The two axes are independent: a Military event may be
    Combat emphasis (a battlefield) or Social (a parade).

    RSVP modes are determined by participant_cap + is_staff_event:
    - Open: no cap, any RSVP → CONFIRMED immediately.
    - Capped (player event): FCFS up to cap, then WAITLISTED. Host can
      pre-invite (player events only — staff events block this).
    - Lottery (is_staff_event=True): RSVPs enter a random pool drawn 72h
      before scheduled_time. Priority token holders seated first.

    cluster (FK EventCluster nullable): when set, this event is part of a
    grouped ranked-choice draw. Standalone RSVP is blocked; players must
    use +rsvp/cluster on the parent cluster.

    lottery_drawn_at: set when the lottery draw fires. Also serves as an
    idempotency guard (the scheduler no-ops if this is set).
    is_cancelled: soft-cancel; cancelled events are excluded from listings.
    """

    class Emphasis(models.TextChoices):
        COMBAT = "combat", "Combat"
        SKILL = "skill", "Skill"
        SOCIAL = "social", "Social"
        FREEFORM = "freeform", "Freeform"

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    scheduled_time = models.DateTimeField(
        db_index=True,
        help_text="Event start time, stored in UTC.",
    )

    creator = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The character who scheduled this event.",
    )
    creator_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized creator name for display after deletion.",
    )

    participant_cap = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum confirmed attendees. Null = unlimited (open mode).",
    )
    emphasis = models.CharField(
        max_length=10,
        choices=Emphasis.choices,
        default=Emphasis.FREEFORM,
    )
    is_staff_event = models.BooleanField(
        default=False,
        help_text=(
            "If True, uses lottery RSVP mode. Staff characters cannot "
            "pre-invite participants (anti-favoritism enforcement)."
        ),
    )

    tags = models.ManyToManyField(
        EventTag,
        blank=True,
        related_name="events",
    )

    cluster = models.ForeignKey(
        EventCluster,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
        help_text=(
            "If set, this event is part of a ranked-choice cluster. "
            "Direct RSVP is blocked; players use +rsvp/cluster."
        ),
    )

    lottery_drawn_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Set when the lottery draw runs (72h before scheduled_time). "
            "Used as an idempotency guard — scheduler no-ops if set."
        ),
    )
    is_cancelled = models.BooleanField(
        default=False,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_time"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["scheduled_time", "is_cancelled"]),
            models.Index(fields=["is_staff_event", "is_cancelled"]),
        ]

    def __str__(self):
        return f"[Event #{self.pk}] {self.title} @ {self.scheduled_time.strftime('%Y-%m-%d %H:%M')} UTC"

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def is_past(self):
        """True if scheduled_time is in the past."""
        return self.scheduled_time < timezone.now()

    @property
    def lottery_draw_time(self):
        """72 hours before scheduled_time — when the lottery draw should fire.

        Returns None for non-staff events and uncapped open events.
        """
        if not self.is_staff_event:
            return None
        from datetime import timedelta

        return self.scheduled_time - timedelta(hours=72)

    @property
    def confirmation_deadline(self):
        """48 hours before scheduled_time — when unconfirmed selections expire."""
        from datetime import timedelta

        return self.scheduled_time - timedelta(hours=48)

    @property
    def is_clustered(self):
        """True if this event belongs to an EventCluster."""
        return self.cluster_id is not None

    @property
    def seats_remaining(self):
        """
        Remaining confirmed seats, or None for unlimited (no cap) events.

        Counts CONFIRMED RSVPs only. WAITLISTED and LOTTERY_SELECTED rows
        do not consume seats until confirmed.
        """
        if self.participant_cap is None:
            return None
        confirmed = self.rsvps.filter(status=RSVP.Status.CONFIRMED).count()
        return max(0, self.participant_cap - confirmed)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create_event(cls, creator, title, scheduled_time, **kwargs):
        """
        Create a new CalendarEvent with required fields.

        Args:
            creator: ObjectDB (Character) instance, or None.
            title: str — short event title.
            scheduled_time: datetime (UTC) — when the event is scheduled.
            **kwargs: optional fields (description, emphasis, participant_cap,
                is_staff_event, cluster).

        Returns:
            The newly created CalendarEvent instance.
        """
        return cls.objects.create(
            creator=creator,
            creator_name=creator.key if creator else "",
            title=title,
            scheduled_time=scheduled_time,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def cancel(self, cancelled_by=None):
        """Soft-cancel this event."""
        self.is_cancelled = True
        self.save(update_fields=["is_cancelled", "updated_at"])


# ---------------------------------------------------------------------------
# ClusterRSVP + ClusterRSVPPreference
# ---------------------------------------------------------------------------


class ClusterRSVP(models.Model):
    """
    A player's ranked-choice ticket for an EventCluster.

    One ClusterRSVP per (cluster, character). Status tracks the draw outcome:
    - PENDING: player has submitted preferences; draw has not run yet.
    - SEATED: player was assigned to a member event; a concrete RSVP was
      created on that event.
    - UNSEATED: draw ran but no ranked event had room; player gets a
      CLUSTER_RANK1 priority token.

    Preferences are stored in ClusterRSVPPreference through-model rows,
    ordered by rank (1 = most preferred). Players may omit events they
    don't want — omitted events are not available as overflow destinations.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SEATED = "seated", "Seated"
        UNSEATED = "unseated", "Unseated"

    cluster = models.ForeignKey(
        EventCluster,
        on_delete=models.CASCADE,
        related_name="cluster_rsvps",
    )
    character = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    character_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized character name for display after deletion.",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("cluster", "character")]  # noqa: RUF012
        ordering = ["created_at"]  # noqa: RUF012

    def __str__(self):
        return (
            f"ClusterRSVP: {self.character_name} → {self.cluster.title} "
            f"[{self.get_status_display()}]"
        )

    def get_ordered_preferences(self):
        """Return ClusterRSVPPreference rows ordered by rank (ascending)."""
        return self.preferences.select_related("event").order_by("rank")


class ClusterRSVPPreference(models.Model):
    """
    A single ranked event preference within a ClusterRSVP.

    Rank 1 = most preferred. Players submit an ordered list; the lottery
    seats them in the highest-ranked event that has capacity.

    Players may omit events — an omitted event is treated as "I would
    rather be unseated than attend this one."
    """

    cluster_rsvp = models.ForeignKey(
        ClusterRSVP,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    event = models.ForeignKey(
        CalendarEvent,
        on_delete=models.CASCADE,
        related_name="+",
    )
    rank = models.PositiveSmallIntegerField(
        help_text="1 = most preferred. Must be unique per ClusterRSVP.",
    )

    class Meta:
        unique_together = [  # noqa: RUF012
            ("cluster_rsvp", "event"),
            ("cluster_rsvp", "rank"),
        ]
        ordering = ["rank"]  # noqa: RUF012

    def __str__(self):
        return f"#{self.rank}: {self.event.title} " f"(for {self.cluster_rsvp.character_name})"


# ---------------------------------------------------------------------------
# RSVP
# ---------------------------------------------------------------------------


class RSVP(models.Model):
    """
    A player's concrete attendance record for a single CalendarEvent.

    Status pipeline by mode:

    Open (no cap):
        RSVP → CONFIRMED

    Capped player event:
        RSVP → CONFIRMED (if under cap)
        RSVP → WAITLISTED (if at cap) → CONFIRMED (when slot opens)
        Host invite: → INVITED → CONFIRMED (on accept, 24h deadline)
                                → RELEASED (on timeout)

    Staff event lottery (is_staff_event=True):
        RSVP → LOTTERY_ENTERED → LOTTERY_SELECTED (72h draw) → CONFIRMED
        Unconfirmed selections (48h mark): → RELEASED

    Clustered event: same as lottery, but RSVP is created by the scheduler
    (run_cluster_lottery) rather than directly by the player. The
    cluster_rsvp FK links back to the ClusterRSVP ticket.

    waitlist_position: ordering key for WAITLISTED RSVPs. Lower = higher
    priority. Set on creation; updated when slots open.
    """

    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        WAITLISTED = "waitlisted", "Waitlisted"
        INVITED = "invited", "Invited"
        LOTTERY_ENTERED = "lottery_entered", "Lottery Entered"
        LOTTERY_SELECTED = "lottery_selected", "Lottery Selected"
        RELEASED = "released", "Released"

    event = models.ForeignKey(
        CalendarEvent,
        on_delete=models.CASCADE,
        related_name="rsvps",
    )
    character = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    character_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized character name for display after deletion.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.LOTTERY_ENTERED,
        db_index=True,
    )
    waitlist_position = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Ordering for WAITLISTED RSVPs. Lower = higher priority.",
    )
    cluster_rsvp = models.ForeignKey(
        ClusterRSVP,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="concrete_rsvps",
        help_text=(
            "For clustered events: back-link to the ClusterRSVP ticket "
            "that produced this concrete RSVP row."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("event", "character")]  # noqa: RUF012
        ordering = ["event", "created_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["event", "status"]),
        ]

    def __str__(self):
        return f"RSVP: {self.character_name} → {self.event.title} " f"[{self.get_status_display()}]"

    def confirm(self):
        """Confirm this RSVP (INVITED or LOTTERY_SELECTED → CONFIRMED)."""
        self.status = self.Status.CONFIRMED
        self.waitlist_position = None
        self.save(update_fields=["status", "waitlist_position", "updated_at"])

    def release(self):
        """Release this RSVP (timeout or cancellation)."""
        self.status = self.Status.RELEASED
        self.save(update_fields=["status", "updated_at"])


# ---------------------------------------------------------------------------
# PriorityToken
# ---------------------------------------------------------------------------


class PriorityToken(models.Model):
    """
    Lottery consolation guarantee.

    Issued to players who entered a staff event lottery but were not selected,
    or who were seated in a lower-ranked cluster event than their rank-1.

    Two scopes:
    - EVENT: guarantees a seat in the next staff event the holder RSVPs for.
      One redeemable per event; redeeming pre-seats the holder before the
      random draw.
    - CLUSTER_RANK1: guarantees rank-1 placement in the specific source
      cluster. Redeemed at draw time, not at RSVP time.

    Tokens never expire (no time-gating). A player holding multiple tokens
    can redeem one per event/draw — hoarding creates sequential guarantees,
    not simultaneous ones.

    source_event / source_cluster: where the token came from.
    redeemed_event / redeemed_cluster: where the token was used.
    redeemed_at: set when the token is consumed.
    """

    class Scope(models.TextChoices):
        EVENT = "event", "Event"
        CLUSTER_RANK1 = "cluster_rank1", "Cluster Rank-1"

    character = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    character_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized character name for display after deletion.",
    )

    scope = models.CharField(
        max_length=15,
        choices=Scope.choices,
        default=Scope.EVENT,
    )

    source_event = models.ForeignKey(
        CalendarEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tokens_issued",
        help_text="The staff event that issued this token (standalone lottery).",
    )
    source_cluster = models.ForeignKey(
        EventCluster,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tokens_issued",
        help_text="The cluster that issued this token (cluster lottery).",
    )

    redeemed_event = models.ForeignKey(
        CalendarEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tokens_redeemed",
        help_text="The event where this token was consumed.",
    )
    redeemed_cluster = models.ForeignKey(
        EventCluster,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tokens_redeemed",
        help_text="The cluster where this token was consumed.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    redeemed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when the token is consumed at draw time.",
    )

    class Meta:
        ordering = ["created_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["character", "redeemed_at"]),
        ]

    def __str__(self):
        status = "redeemed" if self.is_redeemed else "unredeemed"
        return (
            f"PriorityToken [{self.get_scope_display()}] for " f"{self.character_name} ({status})"
        )

    @property
    def is_redeemed(self):
        """True if this token has been consumed."""
        return self.redeemed_at is not None


# ---------------------------------------------------------------------------
# EventExclusion
# ---------------------------------------------------------------------------


class EventExclusion(models.Model):
    """
    Mutual exclusion pair for two CalendarEvents.

    A player who is confirmed (or waitlisted/in lottery) for event_a cannot
    also RSVP for event_b, and vice versa. Checked at RSVP time; does not
    retroactively remove existing RSVPs.

    Optional: most events will never use this. Intended for situations like
    two simultaneous events for opposing sides of a conflict, where
    distributing players across events improves the experience.

    Canonical ordering: lower PK stored as event_a to prevent duplicate
    reversed pairs. Enforced in save().

    Note: explicit exclusions are redundant inside a cluster (seating is
    one-per-player by construction) but remain useful for events in
    different clusters or standalone cross-cluster scenarios.
    """

    event_a = models.ForeignKey(
        CalendarEvent,
        on_delete=models.CASCADE,
        related_name="exclusions_as_a",
    )
    event_b = models.ForeignKey(
        CalendarEvent,
        on_delete=models.CASCADE,
        related_name="exclusions_as_b",
    )
    created_by = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    creator_name = models.CharField(
        max_length=255,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("event_a", "event_b")]  # noqa: RUF012

    def __str__(self):
        return f"Exclusion: [{self.event_a_id}] ⊕ [{self.event_b_id}]"

    def save(self, *args, **kwargs):
        """Enforce canonical ordering: lower PK is always event_a."""
        if self.event_a_id and self.event_b_id and self.event_a_id > self.event_b_id:
            self.event_a_id, self.event_b_id = self.event_b_id, self.event_a_id
        super().save(*args, **kwargs)

    @classmethod
    def are_exclusive(cls, event_a, event_b):
        """
        Return True if the two events are declared mutually exclusive.

        Checks both orderings (a < b and b < a) safely.
        """
        low, high = sorted([event_a.pk, event_b.pk])
        return cls.objects.filter(event_a_id=low, event_b_id=high).exists()

    @classmethod
    def get_exclusions_for(cls, event):
        """
        Return a queryset of CalendarEvents that are mutually exclusive with
        the given event.
        """
        excluded_ids = set()
        excluded_ids.update(cls.objects.filter(event_a=event).values_list("event_b_id", flat=True))
        excluded_ids.update(cls.objects.filter(event_b=event).values_list("event_a_id", flat=True))
        return CalendarEvent.objects.filter(pk__in=excluded_ids)


# ---------------------------------------------------------------------------
# Bridge: CalendarEvent ↔ Scene
# ---------------------------------------------------------------------------


class SceneCalendarLink(AbstractAuthoredLink):
    """
    Links a CalendarEvent to a Scene (integer soft-reference).

    Used to associate RP scenes with the calendar event they belong to.
    Created manually by event organisers or scene owners.

    The scene reference is stored as an integer soft-ref (scene_id) rather
    than a FK to the scenes app. Hard-deletion of a Scene is compensated by
    the connect_soft_ref_cleanup() hook in CalendarConfig.ready() when the
    scenes app is present.

    Uniqueness: one link per (event, scene_id) pair.
    """

    event = models.ForeignKey(
        CalendarEvent,
        on_delete=models.CASCADE,
        related_name="scene_links",
        help_text="The calendar event associated with this scene.",
    )
    scene_id = models.PositiveBigIntegerField(
        db_index=True,
        help_text="PK of the Scene associated with this calendar event.",
    )

    link_fields = ("event", "scene_id")

    class Meta(AbstractAuthoredLink.Meta):
        unique_together = [("event", "scene_id")]  # noqa: RUF012

    def __str__(self):
        return f"CalendarEvent #{self.event_id} ↔ Scene #{self.scene_id}"
