# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
XP models for evennia_xp.

XPLog    — immutable per-award ledger row. Uniqueness on (source_type, source_ref_id)
           for non-MANUAL_GRANT sources provides idempotency across batch re-runs.
           MANUAL_GRANT entries are exempt from uniqueness; their source_ref_id is
           set to the row's own pk immediately after creation.

CharacterXP — aggregate totals per character. One row per character, autocreated on
              first award. Updated atomically alongside XPLog inserts via F() expressions.

All character references use plain integer character_id fields (no ObjectDB FK) so
this app can be installed without any other Evennia model dependency.
"""

from decimal import Decimal

from django.db import models


class XPLog(models.Model):
    """
    Immutable record of a single XP award to a character.

    Uniqueness on (source_type, source_ref_id) for all non-MANUAL_GRANT
    sources provides idempotency: calling record_xp() twice for the same
    upstream item is a safe no-op (returns None the second time).

    MANUAL_GRANT entries are excluded from the unique constraint; their
    source_ref_id is set to the row's own pk immediately after creation.
    """

    class SourceType(models.TextChoices):
        RP_SESSION = "rp_session", "RP Session"
        LORE_AUTHORED = "lore_authored", "Lore Authored"
        LORE_INSPIRATION = "lore_inspiration", "Lore Inspiration"
        CUTSCENE = "cutscene", "Cutscene"
        THREAD_BONUS = "thread_bonus", "Thread Bonus"
        ARC_BONUS = "arc_bonus", "Arc Bonus"
        MANUAL_GRANT = "manual_grant", "Manual Grant"
        RP_CHANNEL_SESSION = "rp_channel_session", "RP Channel Session"

    character_id = models.PositiveIntegerField(
        db_index=True,
        help_text="ObjectDB pk of the character who received this XP.",
    )
    character_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized character name for display after object deletion.",
    )
    amount = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="XP awarded (Decimal to support 0.5 inspiration amounts).",
    )
    source_type = models.CharField(
        max_length=22,
        choices=SourceType.choices,
        db_index=True,
        help_text="Category of activity that earned this XP.",
    )
    source_ref_id = models.PositiveIntegerField(
        db_index=True,
        help_text=(
            "PK of the upstream item (RPSession, LoreEntry, Post, etc.). "
            "Set to own pk for MANUAL_GRANT entries."
        ),
    )
    week = models.CharField(
        max_length=10,
        blank=True,
        db_index=True,
        help_text="ISO week when this XP was awarded, e.g. '2026-W18'.",
    )
    reason = models.CharField(
        max_length=500,
        blank=True,
        help_text="Optional human-readable description (required for MANUAL_GRANT).",
    )
    multiplier_applied = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.0"),
        help_text="The XP multiplier that was active when this row was written.",
    )
    awarded_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this XP row was written.",
    )
    granted_by_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="ObjectDB pk of the staff member who issued a MANUAL_GRANT.",
    )
    granted_by_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized staff name for display after deletion.",
    )

    class Meta:
        ordering = ["-awarded_at"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["character_id", "week"]),
        ]
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["source_type", "source_ref_id"],
                condition=~models.Q(source_type="manual_grant"),
                name="evennia_xp_xplog_non_manual_source_unique",
            ),
        ]

    def __str__(self):
        return (
            f"XPLog #{self.pk}: {self.character_name} "
            f"+{self.amount} XP [{self.source_type}] week={self.week}"
        )


class CharacterXP(models.Model):
    """
    Aggregate XP totals for a single character.

    One row per character, autocreated on first XP award. Updated atomically
    alongside XPLog inserts via F() expressions.
    """

    character_id = models.PositiveIntegerField(
        unique=True,
        help_text="ObjectDB pk of the character. One row per character.",
    )
    character_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized character name for display after object deletion.",
    )
    total_earned = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Lifetime XP earned (sum of all XPLog rows for this character).",
    )
    total_spent = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Lifetime XP spent on abilities/upgrades.",
    )
    current_balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Spendable XP remaining: total_earned - total_spent.",
    )
    last_payout_week = models.CharField(
        max_length=10,
        blank=True,
        help_text="ISO week of the most recent batch that awarded XP to this character.",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Last time this row was updated.",
    )

    class Meta:
        ordering = ["-total_earned"]  # noqa: RUF012
        verbose_name = "Character XP"
        verbose_name_plural = "Character XP"

    def __str__(self):
        return f"CharacterXP: {self.character_name} " f"({self.current_balance} XP balance)"
