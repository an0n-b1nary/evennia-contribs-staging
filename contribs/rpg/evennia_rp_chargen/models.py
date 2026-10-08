# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Models for evennia_rp_chargen.

CharacterBuild — one row per character with a sheet: where it is in its life
                 (draft, finalized, approved) and who reviewed it. The ratings
                 themselves live in an Attribute on the character (see
                 `stats.StatHandler`); this row exists so staff can list and
                 filter sheets with a query. It also holds the starting
                 allowance, spent before any XP.
TagDefinition — a tag (domain, element, ...) in the runtime vocabulary. The
                 ruleset's tags are the seed; staff add more without a deploy.
AbilityDefinition — a catalog entry: an ability or a flaw, its costs, and its
                 effects as data. A *template* (`tag_kind` set) is acquired once
                 per tag: one "Domain Expertise" row covers every domain.
CharacterAbility — a character's copy of an ability: its tag, level, and
                 whether it's equipped.
AbilityTransaction — the audit trail of every acquisition, upgrade, grant,
                 revoke and refund, and how each was paid for.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from evennia_links import AbstractArchived

TEMPLATE_TAG = "@tag"


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
    starting_allowance = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="This sheet's starting allowance; empty means RP_CHARGEN_STARTING_ALLOWANCE.",
    )
    allowance_spent = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal(0))

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

    @property
    def allowance_total(self) -> Decimal:
        from evennia_rp_chargen.conf import starting_allowance

        if self.starting_allowance is None:
            return starting_allowance()
        return self.starting_allowance

    @property
    def allowance_left(self) -> Decimal:
        return max(self.allowance_total - self.allowance_spent, Decimal(0))


class TagDefinition(AbstractArchived):
    """A tag in the runtime vocabulary. Keys never change; archive instead of deleting."""

    key = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    kind = models.SlugField(max_length=32, default="domain", db_index=True)
    aliases = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "name"]  # noqa: RUF012

    def __str__(self) -> str:
        return self.name

    def as_tagdef(self):
        from evennia_rp_rules.ruleset import TagDef

        return TagDef(self.key, self.name, self.kind, tuple(self.aliases or ()), self.description)


class AbilityDefinition(AbstractArchived):
    """A catalog entry. Archive one to retire it: characters keep their copies."""

    class Acquisition(models.TextChoices):
        XP = "xp", "Bought with XP"
        STAFF = "staff", "Staff grant only"
        FREE = "free", "Free, self-service"

    key = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    category = models.SlugField(max_length=32, blank=True, db_index=True)
    description = models.TextField(blank=True)
    is_flaw = models.BooleanField(default=False)
    acquisition = models.CharField(
        max_length=8, choices=Acquisition.choices, default=Acquisition.XP
    )
    xp_cost = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal(0))
    max_level = models.PositiveSmallIntegerField(default=1)
    budget_cost = models.PositiveIntegerField(
        default=0, help_text="Loadout budget used while equipped."
    )
    budget_cost_overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text="Template tag keys mapped to loadout costs; other tags use budget_cost.",
    )
    tag_kind = models.SlugField(
        max_length=32,
        blank=True,
        help_text="Template: each copy names a tag of this kind, written '@tag' in effects.",
    )
    effects = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]  # noqa: RUF012

    def __str__(self) -> str:
        return self.name

    @property
    def is_template(self) -> bool:
        return bool(self.tag_kind)

    def spellings(self) -> tuple[str, ...]:
        return (self.key, self.name)

    def display_name(self, tag=None) -> str:
        return f"{self.name}: {tag.name}" if tag is not None else self.name

    def budget_cost_for(self, tag=None) -> int:
        """Resolve the current catalog cost; flaws always use zero budget."""
        if self.is_flaw:
            return 0
        key = tag.key if tag is not None else None
        return self.budget_cost_overrides.get(key, self.budget_cost)

    def effects_for(self, tag=None) -> list:
        """The effect specs with the template tag filled in."""
        key = tag.key if tag is not None else None
        return [fill_template(spec, key) for spec in self.effects or ()]

    def clean(self):
        from evennia_rp_chargen.catalog import definition_problems

        problems = definition_problems(self)
        if problems:
            raise ValidationError(problems)


def fill_template(value, tag_key):
    """`value` with every `"@tag"` replaced by `tag_key` (left alone if None)."""
    if isinstance(value, dict):
        return {k: fill_template(v, tag_key) for k, v in value.items()}
    if isinstance(value, list):
        return [fill_template(v, tag_key) for v in value]
    if value == TEMPLATE_TAG and tag_key is not None:
        return tag_key
    return value


class CharacterAbility(models.Model):
    """A character's copy of an ability (or flaw), for one tag if it's a template."""

    character = models.ForeignKey(
        "objects.ObjectDB", on_delete=models.CASCADE, related_name="rp_abilities"
    )
    ability = models.ForeignKey(AbilityDefinition, on_delete=models.PROTECT, related_name="+")
    tag = models.ForeignKey(
        TagDefinition, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    level = models.PositiveSmallIntegerField(default=1)
    equipped = models.BooleanField(default=False)
    acquired_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "character abilities"
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["character", "ability", "tag"],
                condition=Q(tag__isnull=False),
                name="rp_chargen_one_copy_per_tag",
            ),
            models.UniqueConstraint(
                fields=["character", "ability"],
                condition=Q(tag__isnull=True),
                name="rp_chargen_one_copy",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.level})"

    @property
    def display_name(self) -> str:
        return self.ability.display_name(self.tag)

    @property
    def budget_cost(self) -> int:
        return self.ability.budget_cost_for(self.tag)

    @property
    def modifier_key(self) -> str:
        return f"{self.ability.key}:{self.tag.key}" if self.tag_id else self.ability.key


class AbilityTransaction(models.Model):
    """One entry in the audit trail. Never edited after it's written."""

    class Kind(models.TextChoices):
        ACQUIRE = "acquire", "Acquired"
        UPGRADE = "upgrade", "Upgraded"
        GRANT = "grant", "Granted by staff"
        REVOKE = "revoke", "Revoked by staff"
        FLAW_ADD = "flaw_add", "Flaw taken"
        FLAW_REMOVE = "flaw_remove", "Flaw removed"
        ALLOWANCE = "allowance", "Allowance set"

    character_id = models.PositiveIntegerField(db_index=True)
    character_name = models.CharField(max_length=255, blank=True)
    ability = models.ForeignKey(
        AbilityDefinition, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    ability_name = models.CharField(max_length=255, blank=True)
    tag_key = models.CharField(max_length=64, blank=True)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    level_from = models.PositiveSmallIntegerField(default=0)
    level_to = models.PositiveSmallIntegerField(default=0)
    allowance_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal(0),
        help_text="Starting allowance spent (negative: refunded).",
    )
    xp_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal(0),
        help_text="XP spent through the ledger (negative: refunded).",
    )
    ledger_ref = models.CharField(max_length=64, blank=True)
    actor = models.ForeignKey(
        "accounts.AccountDB", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]  # noqa: RUF012

    def __str__(self) -> str:
        return f"{self.character_name}: {self.get_kind_display()} {self.ability_name}"
