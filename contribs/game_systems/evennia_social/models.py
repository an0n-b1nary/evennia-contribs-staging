# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Source-owned delivery bookkeeping for character page alerts."""

from django.db import models


class PageDelivery(models.Model):
    class Origin(models.TextChoices):
        OFFLINE = "offline"
        LEGACY = "legacy"
        LIVE = "live"

    class State(models.TextChoices):
        PENDING = "pending"
        CLAIMED = "claimed"
        INBOX = "inbox"
        FALLBACK = "fallback"
        SUPPRESSED = "suppressed"
        UNCERTAIN = "uncertain"

    character = models.ForeignKey("objects.ObjectDB", on_delete=models.CASCADE)
    message = models.ForeignKey("comms.Msg", on_delete=models.CASCADE)
    actor_kind = models.CharField(max_length=9, blank=True)
    actor_id = models.PositiveBigIntegerField(null=True)
    occurred_at = models.DateTimeField()
    origin = models.CharField(max_length=7, choices=Origin.choices)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    suppressed_owners = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("character", "message"), name="social_page_character_message"
            ),
        )
        indexes = (
            models.Index(fields=("character", "state", "message"), name="social_page_pending"),
        )


class PageProgress(models.Model):
    character = models.OneToOneField("objects.ObjectDB", on_delete=models.CASCADE)
    legacy_position = models.PositiveBigIntegerField(default=0)
    retry_position = models.PositiveBigIntegerField(default=0)
