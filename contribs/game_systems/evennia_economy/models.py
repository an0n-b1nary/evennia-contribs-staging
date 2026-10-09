# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from typing import ClassVar

from django.db import models
from django.db.models import Q


class Purse(models.Model):
    character = models.OneToOneField("objects.ObjectDB", on_delete=models.CASCADE)
    balance = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(condition=Q(balance__gte=0), name="economy_nonnegative_balance")
        ]


class LedgerEntry(models.Model):
    """Service-owned journal, retaining identity snapshots after object deletion."""

    kind = models.CharField(max_length=24, db_index=True)
    from_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    to_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    from_name = models.CharField(max_length=255, blank=True)
    to_name = models.CharField(max_length=255, blank=True)
    from_accounts = models.JSONField(default=list)
    to_accounts = models.JSONField(default=list)
    amount = models.PositiveBigIntegerField(default=0)
    fee = models.PositiveBigIntegerField(default=0)
    fee_kind = models.CharField(max_length=24, blank=True)
    assets = models.JSONField(default=list)
    exchange_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    listing_id = models.PositiveBigIntegerField(null=True, blank=True)
    by_id = models.PositiveBigIntegerField(null=True, blank=True)
    note = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering: ClassVar = ["pk"]


class Offer(models.Model):
    giver = models.ForeignKey(
        "objects.ObjectDB", on_delete=models.CASCADE, related_name="economy_offers_sent"
    )
    recipient = models.ForeignKey(
        "objects.ObjectDB", on_delete=models.CASCADE, related_name="economy_offers_received"
    )
    room = models.ForeignKey(
        "objects.ObjectDB", on_delete=models.CASCADE, related_name="economy_offers_here"
    )
    give = models.JSONField(default=list)
    want = models.JSONField(default=list)
    secret = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16,
        default="open",
        choices=[(s, s.title()) for s in ("open", "accepted", "expired", "cancelled")],
        db_index=True,
    )
    created = models.DateTimeField(auto_now_add=True)
    expires = models.DateTimeField(db_index=True)


class UBIPayment(models.Model):
    character = models.ForeignKey("objects.ObjectDB", on_delete=models.CASCADE)
    week = models.CharField(max_length=80)
    amount = models.PositiveBigIntegerField()
    details = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["character", "week"], name="economy_one_ubi_period")
        ]


class StipendPayment(models.Model):
    character = models.ForeignKey("objects.ObjectDB", on_delete=models.CASCADE)
    kind = models.CharField(max_length=16, choices=[("starting", "Starting"), ("reveal", "Reveal")])
    amount = models.PositiveBigIntegerField()
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["character", "kind"], name="economy_one_stipend")
        ]


class ReviewFlag(models.Model):
    first_entry = models.ForeignKey(
        LedgerEntry, on_delete=models.PROTECT, related_name="first_flags"
    )
    second_entry = models.ForeignKey(
        LedgerEntry, on_delete=models.PROTECT, related_name="second_flags"
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    created = models.DateTimeField(auto_now_add=True)
    reviewed = models.BooleanField(default=False)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["first_entry", "second_entry"], name="economy_one_roundtrip_flag"
            )
        ]
