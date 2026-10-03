# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Models for evennia_rp_chargen.

CharacterBuild — one row per character with a sheet: where it is in its life
                 (draft, finalized, approved) and who reviewed it. The ratings
                 themselves live in an Attribute on the character (see
                 `stats.StatHandler`); this row exists so staff can list and
                 filter sheets with a query.
"""

from __future__ import annotations

from django.db import models


class CharacterBuild(models.Model):
    """A character's sheet: its status and review trail.

    Lifecycle: draft -> finalized (-> approved, when approval is required).
    Staff can reopen a finalized or approved sheet back to draft.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        FINALIZED = "finalized", "Finalized"
        APPROVED = "approved", "Approved"

    character = models.OneToOneField(
        "objects.ObjectDB",
        on_delete=models.CASCADE,
        related_name="rp_build",
        help_text="The character this sheet belongs to.",
    )
    character_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized character name for staff listings.",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    allocation_spent = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Allocation points spent, for allocations that count points.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "accounts.AccountDB",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Staff account that last approved or reopened the sheet.",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "character build"
        ordering = ["character_name"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"{self.character_name or self.character_id} ({self.get_status_display()})"

    @property
    def is_draft(self) -> bool:
        return self.status == self.Status.DRAFT

    @property
    def is_playable(self) -> bool:
        """Whether the sheet may be used in checks."""
        from evennia_rp_chargen.conf import require_approval

        if require_approval():
            return self.status == self.Status.APPROVED
        return self.status in (self.Status.FINALIZED, self.Status.APPROVED)
