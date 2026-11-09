# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Recipient locks, recheckable constituents and content-free routing receipts."""

import secrets
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.db.models import Q


def public_ref():
    """Generate a non-sequential public token."""
    return secrets.token_hex(6)


class Recipient(models.Model):
    """One lock row for account ownership or shared playable-character ownership."""

    account = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE
    )
    character = models.OneToOneField(
        "objects.ObjectDB", null=True, blank=True, on_delete=models.CASCADE
    )
    revision = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=(
                    Q(account__isnull=False, character__isnull=True)
                    | Q(account__isnull=True, character__isnull=False)
                ),
                name="notices_one_owner",
            )
        ]

    @property
    def identity(self):
        """Canonical ownership tuple."""
        return ("account", self.account_id) if self.account_id else ("character", self.character_id)


class Notice(models.Model):
    """Public alert envelope; compacted envelopes keep every constituent."""

    public_ref = models.CharField(max_length=12, unique=True, default=public_ref, editable=False)
    recipient = models.ForeignKey(Recipient, on_delete=models.CASCADE, related_name="notices")
    source = models.CharField(max_length=64)
    replacement_key = models.CharField(max_length=255, null=True, blank=True)
    is_compacted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=("recipient", "source", "replacement_key"),
                condition=Q(
                    retired_at__isnull=True, is_compacted=False, replacement_key__isnull=False
                ),
                name="notices_active_slot",
            )
        ]
        indexes: ClassVar = [models.Index(fields=("recipient", "retired_at", "source"))]


class NoticeEvent(models.Model):
    """Recheckable source data with independent acknowledgement and history clocks."""

    notice = models.ForeignKey(Notice, related_name="events", on_delete=models.CASCADE)
    event_id = models.CharField(max_length=255)
    occurred_at = models.DateTimeField()
    replacement_key = models.CharField(max_length=255, null=True, blank=True)
    subject = models.JSONField(null=True, blank=True)
    actors = models.JSONField(default=list)
    payload = models.JSONField(default=dict)
    action_kind = models.CharField(max_length=32, null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    cleared_at = models.DateTimeField(null=True, blank=True)
    inactive_at = models.DateTimeField(null=True, blank=True)
    inactive_reason = models.CharField(max_length=32, blank=True, default="")
    hint_attempted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes: ClassVar = [models.Index(fields=("notice", "inactive_at", "read_at"))]


class DeliveryReceipt(models.Model):
    """Indefinite content-free identity prevents replay after payload pruning."""

    recipient = models.ForeignKey(Recipient, on_delete=models.CASCADE, related_name="receipts")
    source = models.CharField(max_length=64)
    event_id = models.CharField(max_length=255)
    transfer_id = models.CharField(max_length=255, null=True, blank=True)
    fingerprint = models.CharField(max_length=64)
    disposition = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)
    stored_event = models.ForeignKey(NoticeEvent, null=True, on_delete=models.SET_NULL)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=("recipient", "source", "event_id"), name="notices_event_receipt"
            ),
            models.UniqueConstraint(
                fields=("recipient", "source", "transfer_id"),
                condition=Q(transfer_id__isnull=False),
                name="notices_transfer_receipt",
            ),
        ]


class SourcePreference(models.Model):
    """One account-wide choice per source; off never discards a sought-seat decision."""

    account = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    source = models.CharField(max_length=64)
    mode = models.CharField(
        max_length=16, choices=[(x, x) for x in ("immediate", "summary", "off")]
    )

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(fields=("account", "source"), name="notices_preference")
        ]


class ViewerSuppression(models.Model):
    """Content-free per-account suppression of a canonically character-owned event."""

    receipt = models.ForeignKey(
        DeliveryReceipt, on_delete=models.CASCADE, related_name="viewer_suppressions"
    )
    account = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reason = models.CharField(max_length=16)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=("receipt", "account"), name="notices_viewer_suppression"
            )
        ]
