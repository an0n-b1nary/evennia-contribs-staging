# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Scene and log entry models for evennia_scenes.

Models:
    Scene            — RP session in a room (lifecycle: open → active → closed)
    SceneParticipant — tracks a character's participation: join/leave, pose count,
                       observer/active status, invite flag
    LogEntry         — single captured pose/say/emit/ooc/dice/combat/system entry
    LogEntryVersion  — append-only edit-history table for LogEntry
"""

from django.db import models
from django.utils import timezone

from evennia_links import AbstractArchived, AbstractVersion


class Scene(AbstractArchived):
    """
    An RP session in a room.

    Lifecycle: open → active → closed. Archive state is handled by
    AbstractArchived (separate from the status lifecycle).

    A scene is created when a player uses the open command in an IC room.
    It transitions to active automatically when the first pose is recorded.
    closed pauses the scene (resumable). Web visibility is controlled by
    privacy tier, not a separate publish step.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed"

    class Privacy(models.TextChoices):
        PUBLIC = "public", "Public"
        # Anyone can view the scene on the web; only invited characters can pose.
        POSE_PRIVATE = "pose_private", "Pose-Private"
        # Only invited characters (and staff) can view or pose.
        VIEW_PRIVATE = "view_private", "View-Private"

    title = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional scene title.",
    )
    description = models.TextField(
        blank=True,
        help_text="Optional scene summary/description.",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    privacy = models.CharField(
        max_length=13,
        choices=Privacy.choices,
        default=Privacy.PUBLIC,
    )

    room = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        related_name="evennia_scenes",
        help_text="The room where this scene takes place.",
    )
    room_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized room name for display after deletion.",
    )

    creator = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        related_name="evennia_created_scenes",
        help_text="The character who opened this scene.",
    )
    creator_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized creator name for display after deletion.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when the first pose transitions status to active.",
    )
    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when the scene is closed.",
    )

    all_objects = models.Manager()

    class Meta:
        ordering = ["-created_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        title = self.title or "Untitled"
        return f"Scene #{self.pk}: {title} ({self.get_status_display()})"

    def start(self):
        """Transition from OPEN to ACTIVE on first pose."""
        if self.status == self.Status.OPEN:
            self.status = self.Status.ACTIVE
            self.started_at = timezone.now()
            self.save(update_fields=["status", "started_at"])

    def close(self, closer=None):
        """Close (pause) the scene.

        Closed PUBLIC and POSE_PRIVATE scenes become visible on the web log
        automatically — no separate publish step is needed.
        """
        if self.status in (self.Status.OPEN, self.Status.ACTIVE):
            self.status = self.Status.CLOSED
            self.ended_at = timezone.now()
            self.save(update_fields=["status", "ended_at"])

    def resume(self):
        """Resume a closed scene, transitioning back to ACTIVE."""
        if self.status == self.Status.CLOSED:
            self.status = self.Status.ACTIVE
            self.ended_at = None
            self.save(update_fields=["status", "ended_at"])


class SceneParticipant(models.Model):
    """
    Through-model tracking a character's participation in a scene.

    Created automatically when a character enters a room with an active
    scene or when they pose in one. Tracks join/leave times, pose count,
    and whether they are an active participant or observer.
    """

    class Role(models.TextChoices):
        PARTICIPANT = "participant", "Participant"
        OBSERVER = "observer", "Observer"

    scene = models.ForeignKey(
        Scene,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    character = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        # Renamed from "scene_participations" to avoid reverse-accessor clash
        # when an existing scenes app is present alongside this contrib.
        related_name="evennia_scene_participations",
    )
    character_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized character name for display after deletion.",
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when the character leaves or the scene closes.",
    )
    pose_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(
        default=True,
        help_text="False if the character has left the scene.",
    )
    role = models.CharField(
        max_length=12,
        choices=Role.choices,
        default=Role.PARTICIPANT,
    )
    is_invited = models.BooleanField(
        default=False,
        help_text=("True if explicitly invited to pose in POSE_PRIVATE or VIEW_PRIVATE scenes."),
    )

    class Meta:
        unique_together = [("scene", "character")]  # noqa: RUF012
        ordering = ["joined_at"]  # noqa: RUF012

    def __str__(self):
        status = "active" if self.is_active else "left"
        return f"{self.character_name} in Scene #{self.scene_id} ({status})"

    def leave(self):
        """Mark the participant as having left the scene."""
        self.is_active = False
        self.left_at = timezone.now()
        self.save(update_fields=["is_active", "left_at"])

    def rejoin(self):
        """Re-activate a participant who previously left."""
        self.is_active = True
        self.left_at = None
        self.save(update_fields=["is_active", "left_at"])

    def increment_pose_count(self):
        """Increment the pose count using F() for race safety."""
        from django.db.models import F

        self.pose_count = F("pose_count") + 1
        self.save(update_fields=["pose_count"])
        self.refresh_from_db(fields=["pose_count"])


class LogEntry(models.Model):
    """
    A single captured entry within a scene log.

    Each pose, say, emit, OOC comment, dice roll, combat action, or
    system message in a scene is recorded as a LogEntry. Entries can
    be soft-deleted and edited with version history.
    """

    class LogType(models.TextChoices):
        POSE = "pose", "Pose"
        EMIT = "emit", "Emit"
        SAY = "say", "Say"
        OOC = "ooc", "OOC"
        # Reserved for web-viewer OOC: stored separately so room owners can mute
        # the peanut gallery without affecting in-room OOC.
        WEB_OOC = "web_ooc", "Web OOC"
        DICE = "dice", "Dice"
        COMBAT = "combat", "Combat"
        SYSTEM = "system", "System"

    scene = models.ForeignKey(
        Scene,
        on_delete=models.CASCADE,
        related_name="log_entries",
    )
    author = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        help_text="The character who created this entry.",
    )
    author_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized author name for display after deletion.",
    )
    content = models.TextField(
        help_text="The full pose/say/emit/ooc/system text.",
    )
    log_type = models.CharField(
        max_length=10,
        choices=LogType.choices,
        default=LogType.POSE,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    is_deleted = models.BooleanField(
        default=False,
        help_text="Soft-delete flag for individual entries.",
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Explicit ordering within a scene.",
    )

    class Meta:
        ordering = ["order", "created_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["scene", "created_at"]),
        ]

    def __str__(self):
        return f"LogEntry #{self.pk} ({self.get_log_type_display()}) by {self.author_name}"

    def soft_delete(self):
        """Soft-delete this entry."""
        self.is_deleted = True
        self.save(update_fields=["is_deleted"])

    @classmethod
    def create_entry(cls, scene, author, content, log_type="pose"):
        """
        Create a new log entry in the scene.

        Handles auto-incrementing order, transitioning the scene from
        OPEN to ACTIVE on the first entry, auto-registering the author
        as a participant, and incrementing the participant's pose count.

        Args:
            scene: The Scene instance.
            author: The ObjectDB instance (Character), or None for system entries.
            content: The text content of the entry.
            log_type: One of the LogType choices.

        Returns:
            The newly created LogEntry instance.
        """
        current_max = (
            cls.objects.filter(scene=scene)
            .aggregate(max_order=models.Max("order"))
            .get("max_order")
        ) or 0

        entry = cls.objects.create(
            scene=scene,
            author=author,
            author_name=author.key if author else "System",
            content=content,
            log_type=log_type,
            order=current_max + 1,
        )

        # Transition scene OPEN -> ACTIVE on first non-system, non-web-ooc entry.
        if log_type not in (cls.LogType.SYSTEM, cls.LogType.WEB_OOC):
            scene.start()

        # Auto-register author as participant and increment pose count.
        # WEB_OOC authors are not room participants — skip registration.
        if author and log_type not in (cls.LogType.SYSTEM, cls.LogType.WEB_OOC):
            participant, _created = SceneParticipant.objects.get_or_create(
                scene=scene,
                character=author,
                defaults={"character_name": author.key},
            )
            if not participant.is_active:
                participant.rejoin()
            participant.increment_pose_count()

        # Fire signal for cross-system listeners.
        from evennia_scenes.signals import log_entry_created

        log_entry_created.send(sender=cls, entry=entry, scene=scene)

        return entry


class LogEntryVersion(AbstractVersion):
    """Edit history for scene log entries."""

    parent = models.ForeignKey(
        LogEntry,
        on_delete=models.CASCADE,
        related_name="versions",
    )

    class Meta(AbstractVersion.Meta):
        unique_together = [("parent", "version_number")]  # noqa: RUF012
