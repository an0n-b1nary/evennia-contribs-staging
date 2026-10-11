# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Durable player preferences. Fight progress belongs to a Script, not a table."""

from django.db import models


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
