# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class NicheDefinition(models.Model):
    key = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    behaviours = models.JSONField(default=list)
    input_categories = models.JSONField(default=list)
    unlock_money = models.PositiveBigIntegerField(default=100)
    unlock_resources = models.JSONField(default=dict)
    archived = models.BooleanField(default=False)

    class Meta:
        ordering: ClassVar = ["key"]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exclude(key=self.key).exists():
            raise ValidationError("Niche keys are permanent; archive the old definition instead.")
        return super().save(*args, **kwargs)


class Workshop(models.Model):
    character = models.OneToOneField("objects.ObjectDB", on_delete=models.CASCADE)
    invested_money = models.PositiveBigIntegerField(default=0)
    last_craft = models.DateTimeField(null=True, blank=True)


class NicheUnlock(models.Model):
    workshop = models.ForeignKey(Workshop, on_delete=models.CASCADE, related_name="unlocks")
    niche = models.ForeignKey(NicheDefinition, on_delete=models.PROTECT)
    position = models.PositiveIntegerField()
    money_paid = models.PositiveBigIntegerField(default=0)
    resources_paid = models.JSONField(default=dict)
    unlocked_at = models.DateTimeField(auto_now_add=True)
    abandoned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["workshop", "niche"],
                condition=Q(abandoned_at__isnull=True),
                name="crafting_one_active_niche",
            )
        ]


class WorkshopInvestment(models.Model):
    workshop = models.ForeignKey(Workshop, on_delete=models.CASCADE, related_name="investments")
    resource_key = models.SlugField(max_length=80)
    quantity = models.PositiveBigIntegerField()

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["workshop", "resource_key"],
                name="crafting_one_investment",
            )
        ]


class CraftRecord(models.Model):
    # Soft references preserve verified provenance after a maker or item is gone.
    crafter_id = models.PositiveBigIntegerField(db_index=True)
    crafter_name = models.CharField(max_length=255)
    crafter_accounts = models.JSONField(default=list)
    niche = models.ForeignKey(NicheDefinition, on_delete=models.PROTECT)
    niche_name = models.CharField(max_length=120)
    behaviour = models.SlugField(max_length=80)
    # Behaviour is the lifecycle on new records; verbs carry their own prose.
    verbs = models.JSONField(default=list)
    contributors = models.JSONField(default=list)
    item_id = models.PositiveBigIntegerField(unique=True)
    resources_spent = models.JSONField(default=dict)
    money_spent = models.PositiveBigIntegerField(default=0)
    furnishing_weeks = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    prose = models.JSONField(default=dict)
    hallmark = models.TextField()
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar = ["pk"]

    @property
    def lifecycle(self):
        return "carried" if self.behaviour == "readable" else self.behaviour

    @property
    def verb_data(self):
        if self.behaviour == "readable":
            return [
                {
                    "key": "readable",
                    "niche": self.niche.key,
                    "configuration": self.prose["configuration"],
                }
            ]
        return self.verbs

    @property
    def contributor_data(self):
        return self.contributors or [
            {
                "key": self.niche.key,
                "name": self.niche_name,
                "behaviours": [self.behaviour],
            }
        ]

    @property
    def behaviour_keys(self):
        return [self.lifecycle, *(entry["key"] for entry in self.verb_data)]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Craft records are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Craft records are append-only.")


class EventUse(models.Model):
    """One lifetime use per item; soft identities survive consumption."""

    craft = models.OneToOneField(CraftRecord, on_delete=models.PROTECT)
    actor_id = models.PositiveBigIntegerField()
    actor_name = models.CharField(max_length=255)
    room_id = models.PositiveBigIntegerField()
    destinations = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True)


class EventRoomLimit(models.Model):
    room_id = models.PositiveBigIntegerField(unique=True)
    last_used = models.DateTimeField(null=True)


class FixtureInstallation(models.Model):
    """Placement history; host ownership is always resolved through Links."""

    craft = models.ForeignKey(CraftRecord, on_delete=models.PROTECT)
    room_id = models.PositiveBigIntegerField(db_index=True)
    installer_id = models.PositiveBigIntegerField()
    active = models.BooleanField(default=True)
    installed_at = models.DateTimeField(auto_now_add=True)
    removed_at = models.DateTimeField(null=True)
    last_emitted = models.DateTimeField(null=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["craft"], condition=Q(active=True), name="crafting_one_active_install"
            )
        ]


class RoomLayer(models.Model):
    craft = models.ForeignKey(CraftRecord, on_delete=models.PROTECT)
    room_id = models.PositiveBigIntegerField(db_index=True)
    actor_id = models.PositiveBigIntegerField()
    scene_id = models.PositiveBigIntegerField(null=True)
    expires_at = models.DateTimeField()
    cleared_at = models.DateTimeField(null=True)
    last_emitted = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ActivationUse(models.Model):
    craft = models.ForeignKey(CraftRecord, on_delete=models.PROTECT)
    actor_id = models.PositiveBigIntegerField()
    room_id = models.PositiveBigIntegerField()
    mode = models.SlugField(max_length=40)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
