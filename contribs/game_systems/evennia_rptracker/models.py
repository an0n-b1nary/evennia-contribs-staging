# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
RPTracker models.

Models:
- RPSession: a detected stretch of continuous RP activity by a single
  character. Activates after the configured pose count threshold in an IC
  room with at least 1 other actively posing character. Ends after the
  idle timeout, on disconnect, or via manual +activity/end. Status lifecycle:
  pending -> active -> completed (or flagged).
- RPSessionPartner: through-model tracking which other characters were
  present and actively posing during an RPSession, with per-partner
  pose counts.
- RPSessionSceneLink: integer soft-reference bridge linking an RPSession
  to a scene that was active in the same room. Created automatically
  by the rp_activity_recorded signal listener when RPTRACKER_SCENES_APP_LABEL
  is installed. scene_id stores the scene's pk as a plain integer — no FK
  dependency on the scene app.
"""

from django.db import models
from django.utils import timezone

from evennia_links import AbstractLink


class RPSession(models.Model):
    """
    A detected stretch of RP activity by a single character.

    Lifecycle: pending -> active -> completed (or flagged).

    A session begins tracking on the character's first qualifying pose in
    an IC room. It activates (status=ACTIVE) after the configured number of
    poses when at least one other character has been posing nearby. It ends
    after the idle timeout, on disconnect, or via +activity/end. Flagged
    sessions are excluded from XP until staff review.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        FLAGGED = "flagged", "Flagged"

    character = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        help_text="The character whose RP activity this session tracks.",
    )
    character_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized character name for display after deletion.",
    )
    room = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        help_text="The IC room where this session started.",
    )
    room_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized room name for display after deletion.",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    started_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When tracking began (pending state).",
    )
    activated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the session became ACTIVE (activation threshold met).",
    )
    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the session was completed or flagged.",
    )
    pose_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of poses recorded during this session.",
    )
    ended_manually = models.BooleanField(
        default=False,
        help_text=(
            "True if the player explicitly ended this session. "
            "Too many manual ends in a day triggers an auto-flag."
        ),
    )
    xp_awarded = models.BooleanField(
        default=False,
        help_text="True once the XP batch has processed this session.",
    )
    xp_week = models.CharField(
        max_length=10,
        blank=True,
        help_text="ISO week string (e.g. '2026-W14') when XP was awarded.",
    )
    flag_reason = models.TextField(
        blank=True,
        help_text="Staff or auto-generated reason for flagging this session.",
    )
    flagged_by = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Staff character who flagged this session, or None for auto-flags.",
    )
    flagged_by_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized name for the flagging staff member.",
    )
    flagged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["character", "status"]),
            models.Index(fields=["status", "started_at"]),
        ]

    def __str__(self):
        return f"RPSession #{self.pk}: {self.character_name} " f"({self.get_status_display()})"

    def duration_seconds(self):
        """Return session duration in seconds.

        Uses activated_at as the start point (pending time before activation
        is not meaningful for XP).
        """
        start = self.activated_at or self.started_at
        end = self.ended_at or timezone.now()
        return max(0, int((end - start).total_seconds()))

    def duration_display(self):
        """Return a human-readable duration string (e.g. '1h 23m')."""
        seconds = self.duration_seconds()
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def is_xp_eligible(self):
        """Return True if this session qualifies for XP.

        Default criteria (override in a subclass or your XP collector):
        - Status is COMPLETED
        - Duration >= 30 minutes (1800 seconds)
        - Has at least 1 partner recorded
        - xp_awarded is False
        """
        if self.status != self.Status.COMPLETED:
            return False
        if self.duration_seconds() < 1800:
            return False
        if not self.partners.exists():
            return False
        return not self.xp_awarded

    def activate(self, room):
        """Transition PENDING -> ACTIVE."""
        if self.status == self.Status.PENDING:
            self.status = self.Status.ACTIVE
            self.activated_at = timezone.now()
            if room and not self.room_id:
                self.room = room
                self.room_name = room.key
            self.save(update_fields=["status", "activated_at", "room_id", "room_name"])

    def complete(self, manual=False):
        """Transition ACTIVE -> COMPLETED."""
        if self.status in (self.Status.PENDING, self.Status.ACTIVE):
            self.status = self.Status.COMPLETED
            self.ended_at = timezone.now()
            self.ended_manually = manual
            self.save(update_fields=["status", "ended_at", "ended_manually"])

    def flag(self, reason, flagged_by=None):
        """Flag this session for staff review.

        Args:
            reason: Description of why the session is flagged.
            flagged_by: Optional ObjectDB staff character. None = auto-flag.
        """
        if self.status in (self.Status.ACTIVE, self.Status.COMPLETED):
            self.status = self.Status.FLAGGED
            self.flag_reason = reason
            self.flagged_by = flagged_by
            self.flagged_by_name = flagged_by.key if flagged_by else "auto"
            self.flagged_at = timezone.now()
            if not self.ended_at:
                self.ended_at = timezone.now()
            self.save(
                update_fields=[
                    "status",
                    "flag_reason",
                    "flagged_by",
                    "flagged_by_name",
                    "flagged_at",
                    "ended_at",
                ]
            )

    def unflag(self):
        """Remove a flag, restoring the session to COMPLETED."""
        if self.status == self.Status.FLAGGED:
            self.status = self.Status.COMPLETED
            self.flag_reason = ""
            self.flagged_by = None
            self.flagged_by_name = ""
            self.flagged_at = None
            self.save(
                update_fields=[
                    "status",
                    "flag_reason",
                    "flagged_by",
                    "flagged_by_name",
                    "flagged_at",
                ]
            )


class RPSessionPartner(models.Model):
    """
    Through-model recording a character who was an active RP partner
    during an RPSession.

    A partner is a character who was present in the same IC room and had
    recently posed (last_pose_time within RPTRACKER_PARTNER_ACTIVE_WINDOW)
    when the owning character was posing.

    pose_count is an approximation: it counts how many times the partner
    was detected as actively posing when the session owner posed. It is
    not a precise count of the partner's own poses.
    """

    session = models.ForeignKey(
        RPSession,
        on_delete=models.CASCADE,
        related_name="partners",
    )
    partner = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )
    partner_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized partner name for display after deletion.",
    )
    pose_count = models.PositiveIntegerField(
        default=0,
        help_text="Approximate count of times this partner was detected as active.",
    )

    class Meta:
        unique_together = [("session", "partner")]  # noqa: RUF012
        ordering = ["-pose_count"]  # noqa: RUF012

    def __str__(self):
        return f"Partner {self.partner_name} in RPSession #{self.session_id}"


class RPSessionSceneLink(AbstractLink):
    """
    Integer soft-reference bridge linking an RPSession to a scene.

    Created automatically by the rp_activity_recorded listener when
    RPTRACKER_SCENES_APP_LABEL is installed and the room has an
    active_scene_id attribute set.

    scene_id stores the scene's pk as a plain integer (no FK), so this
    table has no DB dependency on the scene app. Cleanup on scene deletion
    is handled by connect_soft_ref_cleanup() registered in apps.ready().
    """

    session = models.ForeignKey(
        RPSession,
        on_delete=models.CASCADE,
        related_name="scene_links",
        help_text="The RPSession that overlapped with this scene.",
    )
    scene_id = models.PositiveBigIntegerField(
        db_index=True,
        help_text="PK of the Scene that was active in the room during the session.",
    )

    link_fields = ("session", "scene_id")

    class Meta(AbstractLink.Meta):
        unique_together = [("session", "scene_id")]  # noqa: RUF012

    def __str__(self):
        return f"RPSession #{self.session_id} ↔ Scene #{self.scene_id}"
