# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Durable fights, their append-only journal and player preferences.

A Fight row holds the engine's JSON state and is the row lock every
mechanical write takes. Each operation appends one FightEntry carrying the
state before it, so history is written once and never rewritten, and staff
rollback reads a single row. Frozen builds live once in FightBuild; stored
state and snapshots carry only their digests. Character references in the journal are plain
integers: history outlives the characters it mentions.
"""

from django.db import models


class Fight(models.Model):
    OPEN, SHELVED, ENDED = "open", "shelved", "ended"

    room = models.ForeignKey(
        "objects.ObjectDB",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rp_combat_fights",
    )
    status = models.CharField(
        max_length=8,
        choices=[(v, v.title()) for v in (OPEN, SHELVED, ENDED)],
        default=OPEN,
        db_index=True,
    )
    state = models.JSONField(default=dict)
    # Presence bookkeeping (last time each member was seen connected and
    # active). Maintenance updates it every tick, so it is kept out of the
    # journaled fight state.
    presence = models.JSONField(default=dict, blank=True)
    label = models.CharField(max_length=200, blank=True)
    unsupported_notice = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-pk",)
        constraints = (
            models.UniqueConstraint(
                fields=("room",),
                condition=models.Q(status="open"),
                name="rp_combat_one_open_fight_per_room",
            ),
        )

    def __str__(self):
        return f"Fight #{self.pk} ({self.status})"


class FightBuild(models.Model):
    """An immutable build frozen for a fight, stored once and content-addressed.

    Stored fight state and journal snapshots reference builds by digest, so
    neither repeats them. Rows are never changed or deleted while their fight
    exists, so any checkpoint's references stay valid for rollback.
    """

    fight = models.ForeignKey(Fight, on_delete=models.CASCADE, related_name="builds")
    digest = models.CharField(max_length=64)
    build = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=("fight", "digest"), name="rp_combat_build_digest"),
        )


class FightEntry(models.Model):
    fight = models.ForeignKey(Fight, on_delete=models.CASCADE, related_name="entries")
    sequence = models.PositiveIntegerField()
    operation = models.CharField(max_length=64)
    actor_id = models.IntegerField(null=True, blank=True)
    label = models.CharField(max_length=500, blank=True)
    summary = models.TextField()
    before = models.JSONField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True)
    superseded = models.BooleanField(default=False)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("fight", "sequence")
        constraints = (
            models.UniqueConstraint(fields=("fight", "sequence"), name="rp_combat_entry_sequence"),
            models.UniqueConstraint(
                fields=("fight", "operation"), name="rp_combat_entry_operation"
            ),
        )


class Tactics(models.Model):
    character = models.ForeignKey(
        "objects.ObjectDB", on_delete=models.CASCADE, related_name="rp_tactics"
    )
    key = models.SlugField(max_length=64)
    name = models.CharField(max_length=80)
    appetite = models.CharField(
        max_length=8,
        choices=[(v, v.title()) for v in ("cautious", "balanced", "bold")],
        default="balanced",
    )
    preferred_reaction = models.CharField(
        max_length=12,
        choices=[(v, v.title()) for v in ("", "evade", "resist", "overpower")],
        blank=True,
    )
    preferred_moves = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=False)
    # These are outgoing action preferences, independent of defensive appetite.
    rps_appetite = models.CharField(
        max_length=8,
        choices=[(v, v.title()) for v in ("cautious", "balanced", "bold")],
        default="balanced",
    )
    target_policy = models.CharField(max_length=20, default="random")
    action_weights = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "pk")
        constraints = (
            models.UniqueConstraint(fields=("character", "key"), name="rp_tactics_owner_key"),
            models.UniqueConstraint(
                fields=("character",), condition=models.Q(active=True), name="rp_tactics_one_active"
            ),
        )
