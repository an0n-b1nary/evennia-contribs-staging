# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Stable catalogue keys, atomic counters and an append-only service ledger."""

from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class ResourceDefinition(models.Model):
    key = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    category = models.SlugField(max_length=80)
    terrains = models.JSONField(default=list, blank=True)
    weight = models.PositiveIntegerField(default=1)
    in_trickle = models.BooleanField(default=True)
    basic = models.BooleanField(default=False)
    archived = models.BooleanField(default=False)

    class Meta:
        ordering: ClassVar = ["category", "key"]
        constraints: ClassVar = [
            models.CheckConstraint(condition=Q(weight__gt=0), name="resources_positive_weight")
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exclude(key=self.key).exists():
            raise ValidationError(
                "Resource keys are permanent; archive the old definition instead."
            )
        return super().save(*args, **kwargs)


class ResourceHolding(models.Model):
    character = models.ForeignKey("objects.ObjectDB", on_delete=models.CASCADE)
    resource = models.ForeignKey(ResourceDefinition, on_delete=models.PROTECT)
    quantity = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["character", "resource"], name="resources_one_holding"),
            models.CheckConstraint(
                condition=Q(quantity__gte=0), name="resources_nonnegative_holding"
            ),
        ]


class ResourceGrant(models.Model):
    # Null resource, zero quantity: one batch receipt, including an empty/full batch.
    character = models.ForeignKey("objects.ObjectDB", on_delete=models.CASCADE)
    resource = models.ForeignKey(
        ResourceDefinition, null=True, blank=True, on_delete=models.PROTECT
    )
    quantity = models.BigIntegerField()
    source = models.CharField(
        max_length=16,
        choices=[(key, key.title()) for key in ("trickle", "payout", "exchange", "craft", "staff")],
    )
    week = models.CharField(max_length=80, blank=True, db_index=True)
    session_id = models.PositiveBigIntegerField(null=True, blank=True)
    thread_id = models.PositiveBigIntegerField(null=True, blank=True)
    exchange_id = models.PositiveBigIntegerField(null=True, blank=True)
    by_id = models.PositiveBigIntegerField(null=True, blank=True)
    note = models.TextField(blank=True)
    details = models.JSONField(default=dict, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar = ["pk"]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["character", "week"],
                condition=Q(source="trickle", resource__isnull=True),
                name="resources_one_batch_receipt",
            ),
            models.CheckConstraint(
                condition=Q(resource__isnull=False) | Q(source="trickle", quantity=0),
                name="resources_receipt_or_resource",
            ),
        ]


class PlotThreadResourcePayout(models.Model):
    """A proposed per-participant budget. Editing requires fresh staff approval."""

    thread_id = models.PositiveBigIntegerField(db_index=True)
    resource = models.ForeignKey(ResourceDefinition, on_delete=models.PROTECT)
    quantity = models.PositiveBigIntegerField()
    set_by_id = models.PositiveBigIntegerField()
    approved_by_id = models.PositiveBigIntegerField(null=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["thread_id", "resource"], name="resources_plot_budget"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="resources_positive_payout"),
        ]


class PlotPayoutRun(models.Model):
    """Frozen conclusion award; no historical backfill or mutable membership."""

    thread_id = models.PositiveBigIntegerField(unique=True)
    plot_name = models.CharField(max_length=255)
    amounts = models.JSONField(default=dict)
    recipients = models.JSONField(default=list)
    approvals = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True)


class PlotPayoutReceipt(models.Model):
    run = models.ForeignKey(PlotPayoutRun, on_delete=models.PROTECT, related_name="receipts")
    character_id = models.PositiveBigIntegerField()
    character_name = models.CharField(max_length=255)
    paid_at = models.DateTimeField(null=True)
    notified_at = models.DateTimeField(null=True)
    skipped = models.BooleanField(default=False)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["run", "character_id"], name="resources_plot_receipt"),
        ]
