# ruff: noqa: RUF012
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Durable identity, permissions and appearances; no fight state or partner FKs."""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class NPCBlueprint(models.Model):
    class Kind(models.TextChoices):
        TEMPLATE = "template", "Template"
        UNIQUE = "unique", "Unique"

    name = models.CharField(max_length=200, unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    description = models.TextField(blank=True)
    short_desc = models.CharField(max_length=200, blank=True)
    creator = models.ForeignKey(
        "objects.ObjectDB", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    creator_name = models.CharField(max_length=200)
    stat_block = models.JSONField(default=dict)
    abilities = models.JSONField(default=list)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [models.UniqueConstraint(Lower("name"), name="npcs_name_casefold")]

    def __str__(self):
        return self.name


class NPCPermission(models.Model):
    class Level(models.TextChoices):
        OWNER = "owner", "Owner"
        PLAYER = "player", "Player"

    blueprint = models.ForeignKey(
        NPCBlueprint, on_delete=models.CASCADE, related_name="permissions"
    )
    holder = models.ForeignKey(
        "objects.ObjectDB", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    holder_name = models.CharField(max_length=200)
    level = models.CharField(max_length=10, choices=Level.choices)
    granted_at = models.DateTimeField(auto_now_add=True)
    last_played = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["blueprint", "holder"], name="npcs_permission_holder"),
            models.UniqueConstraint(
                fields=["blueprint"], condition=Q(level="owner"), name="npcs_one_owner"
            ),
        ]


class NPCPermissionRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"
        AUTO_APPROVED = "auto_approved", "Auto-approved"

    blueprint = models.ForeignKey(NPCBlueprint, on_delete=models.CASCADE, related_name="requests")
    requester = models.ForeignKey(
        "objects.ObjectDB", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    requester_name = models.CharField(max_length=200)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["blueprint", "requester"],
                condition=Q(status="pending"),
                name="npcs_pending_request",
            )
        ]


class NPCSpawnRecord(models.Model):
    blueprint = models.ForeignKey(NPCBlueprint, on_delete=models.PROTECT, related_name="spawns")
    spawned_object = models.OneToOneField(
        "objects.ObjectDB", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    spawned_object_name = models.CharField(max_length=200)
    spawner = models.ForeignKey(
        "objects.ObjectDB", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    spawner_name = models.CharField(max_length=200)
    controller = models.OneToOneField(
        "objects.ObjectDB", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    controller_name = models.CharField(max_length=200, blank=True)
    room_id_snapshot = models.PositiveIntegerField(null=True)
    spawned_at = models.DateTimeField(auto_now_add=True)
    last_active_at = models.DateTimeField()
    despawned_at = models.DateTimeField(null=True, blank=True)
    # Non-null only for unique blueprints. This DB constraint prevents two
    # concurrent unique spawns even where select_for_update is unavailable.
    unique_blueprint = models.OneToOneField(
        NPCBlueprint, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-spawned_at", "-pk"]


class NPCSceneAppearance(models.Model):
    spawn = models.ForeignKey(NPCSpawnRecord, on_delete=models.CASCADE, related_name="scenes")
    scene_id = models.PositiveIntegerField()
    # Titles and private scene contents are deliberately not copied.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["spawn", "scene_id"], name="npcs_spawn_scene")
        ]


class PlotNPCLink(models.Model):
    blueprint = models.ForeignKey(NPCBlueprint, on_delete=models.CASCADE, related_name="plot_links")
    thread_id = models.PositiveIntegerField()
    linked_by_id_snapshot = models.PositiveIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["blueprint", "thread_id"], name="npcs_blueprint_thread")
        ]


class NPCCombatProfile(models.Model):
    """Durable action-policy configuration, dark until the host opts in.

    The combat contrib interprets these values. This package never resolves
    attacks, starts fights, or schedules automatic actions.
    """

    blueprint = models.OneToOneField(
        NPCBlueprint, on_delete=models.CASCADE, related_name="combat_profile"
    )
    target_policy = models.CharField(max_length=100, default="random")
    action_weights = models.JSONField(default=dict)
    special_moves = models.JSONField(default=list)
    reaction_policy = models.JSONField(default=dict)
    boss_check_schedule = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)
