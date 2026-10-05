# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Persistent room challenges and private resolution audit records."""

from django.db import models
from django.utils import timezone

from evennia_links import AbstractArchived


def object_ref(**kwargs):
    return models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        **kwargs,
    )


class RoomSequence(models.Model):
    """An atomic counter; numbers are never reused after closing or archiving."""

    room = models.OneToOneField("objects.ObjectDB", on_delete=models.CASCADE, related_name="+")
    number = models.PositiveIntegerField(default=0)


class Challenge(AbstractArchived):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    room = object_ref()
    room_name = models.CharField(max_length=255)
    number = models.PositiveIntegerField()
    scene_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    set_by = object_ref()
    set_by_name = models.CharField(max_length=255)
    difficulty = models.CharField(max_length=100)
    description = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    stat_key = models.CharField(max_length=100, null=True, blank=True)
    # An opaque vocabulary key, never an FK into optional chargen.
    tag = models.CharField(max_length=100, null=True, blank=True)
    once = models.BooleanField(default=False)
    last_activity = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_reason = models.CharField(max_length=100, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    edited_by = object_ref()

    class Meta:
        ordering = ("number",)
        constraints = (
            models.UniqueConstraint(fields=("room", "number"), name="rp_contest_room_number"),
        )


class CheckRecord(models.Model):
    character = object_ref()
    actor_name = models.CharField(max_length=255)
    room = object_ref()
    room_name = models.CharField(max_length=255)
    scene_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    challenge = models.ForeignKey(
        Challenge, on_delete=models.SET_NULL, null=True, related_name="attempts"
    )
    attempt_no = models.PositiveIntegerField(default=1)
    stat = models.CharField(max_length=100)
    tag = models.CharField(max_length=100, null=True, blank=True)
    rating_display = models.CharField(max_length=100)
    difficulty = models.CharField(max_length=100)
    outcome_key = models.CharField(max_length=100)
    outcome_degree = models.SmallIntegerField()
    is_success = models.BooleanField()
    comment = models.TextField(blank=True)
    alternative = models.BooleanField(default=False)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = object_ref()
    void_reason = models.TextField(blank=True)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("created_at", "pk")
        constraints = (
            models.UniqueConstraint(
                fields=("challenge", "character", "attempt_no"),
                name="rp_contest_actor_attempt",
            ),
        )

    @property
    def voided(self):
        return self.voided_at is not None
