# SPDX-License-Identifier: BSD-3-Clause
"""Durable moderation history and admissions reservations.

Credentials and addresses live outside Jobs' saved questionnaire answers.
Released applications have no password hash or reserved name. Approved
applications are deleted; their Job and Referral remain as the audit trail.
"""

from django.db import models
from django.utils import timezone


class AdmissionsState(models.Model):
    """One writer lock and the current referral accounting period."""

    period = models.PositiveIntegerField(default=1)


class ModerationAction(models.Model):
    class Kind(models.TextChoices):
        BAN = "ban", "Permanent ban"
        SOFTBAN = "softban", "Timed ban"
        MUTE = "mute", "Mute"
        LIFT = "lift", "Lift restriction"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    account = models.ForeignKey(
        "accounts.AccountDB", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    account_name = models.CharField(max_length=255, blank=True)
    address = models.CharField(max_length=255, blank=True)
    address_is_pattern = models.BooleanField(default=False)
    stock_key = models.CharField(max_length=64, blank=True, db_index=True)
    actor = models.ForeignKey(
        "accounts.AccountDB", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_name = models.CharField(max_length=255)
    reason = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True, db_index=True)
    lifted_at = models.DateTimeField(null=True, blank=True)
    lifts = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="lift_records"
    )

    class Meta:
        ordering = ["created_at", "pk"]  # noqa: RUF012


class StaffNote(models.Model):
    account = models.ForeignKey(
        "accounts.AccountDB", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    account_name = models.CharField(max_length=255)
    actor = models.ForeignKey(
        "accounts.AccountDB", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_name = models.CharField(max_length=255)
    text = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "pk"]  # noqa: RUF012


class ReferralCode(models.Model):
    owner = models.ForeignKey(
        "accounts.AccountDB", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    owner_name = models.CharField(max_length=255, default="")
    digest = models.CharField(max_length=64, unique=True)
    period = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    # A display copy lets the owner retrieve their own outstanding invitation.
    code = models.CharField(max_length=64)


class Application(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DECLINED = "declined", "Declined"
        LAPSED = "lapsed", "Lapsed"

    job = models.OneToOneField(
        "evennia_jobs.Job", on_delete=models.PROTECT, related_name="admission"
    )
    account_name = models.CharField(max_length=255)
    reserved_name = models.CharField(max_length=255, null=True, unique=True)
    password_hash = models.CharField(max_length=255)
    address = models.GenericIPAddressField(null=True, blank=True)
    code = models.OneToOneField(
        ReferralCode, null=True, on_delete=models.PROTECT, related_name="application"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    share_decline_reason = models.BooleanField(default=False)


class Referral(models.Model):
    account = models.OneToOneField(
        "accounts.AccountDB", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    account_name = models.CharField(max_length=255)
    referrer = models.ForeignKey(
        "accounts.AccountDB", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    referrer_name = models.CharField(max_length=255, blank=True)
    period = models.PositiveIntegerField()
    submission_id = models.PositiveIntegerField(null=True, unique=True)
    created_at = models.DateTimeField(default=timezone.now)


class RetiredSeat(models.Model):
    account = models.OneToOneField("accounts.AccountDB", on_delete=models.CASCADE, related_name="+")
    retired_by = models.ForeignKey(
        "accounts.AccountDB", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    retired_at = models.DateTimeField(default=timezone.now)


class Notice(models.Model):
    account = models.ForeignKey("accounts.AccountDB", on_delete=models.CASCADE, related_name="+")
    text = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    delivered_at = models.DateTimeField(null=True, blank=True)


class ApplicationThrottle(models.Model):
    """Short-lived keyed address digest; never stores the connection address."""

    key = models.CharField(max_length=64, unique=True)
    attempts = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField()
