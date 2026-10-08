# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The ability catalog: validation, lookup, seeding, and turning copies into modifiers.

An ability's `effects` are effect specs for evennia_rp_rules' `build_modifier`
(`{"kind": "tag_bonus", "tags": ["@tag"], "score": 8, "per_level": 1}`). In a
template, `"@tag"` stands for the tag each copy was acquired for.

Seed format (`RP_CHARGEN_CATALOG_SEED` points at a list of these):

    {"key": "domain-expertise", "name": "Domain Expertise", "category": "domain",
     "tag_kind": "domain", "acquisition": "xp", "xp_cost": 3, "max_level": 5,
     "budget_cost": 10, "is_flaw": False, "description": "...",
     "effects": [{"kind": "tag_bonus", "tags": ["@tag"], "score": 8, "per_level": 1}]}
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from evennia_rp_chargen import conf
from evennia_rp_chargen.models import (
    TEMPLATE_TAG,
    AbilityDefinition,
    CharacterAbility,
    TagDefinition,
    fill_template,
)
from evennia_rp_rules.modifiers import EffectSpecError, build_modifier, effect_problems
from evennia_rp_rules.ruleset import get_ruleset, match_spelling

logger = logging.getLogger("evennia")

SEED_FIELDS = {
    "key",
    "name",
    "category",
    "description",
    "is_flaw",
    "acquisition",
    "xp_cost",
    "max_level",
    "budget_cost",
    "budget_cost_overrides",
    "tag_kind",
    "effects",
}


def _uses_template(value) -> bool:
    if isinstance(value, dict):
        return any(_uses_template(v) for v in value.values())
    if isinstance(value, list):
        return any(_uses_template(v) for v in value)
    return value == TEMPLATE_TAG


def definition_problems(ability: AbilityDefinition) -> list[str]:
    """Everything wrong with a catalog entry, for `clean()` and the seed command.

    A template's effects are checked with a real tag of its kind filled in, so
    the structure and any fixed tags are validated exactly as play will use them.
    """
    from evennia_rp_chargen.vocabulary import DBVocabulary

    if not isinstance(ability.effects, list):
        return [f"effects must be a list, got {type(ability.effects).__name__}"]
    problems = []
    if _uses_template(ability.effects) and not ability.tag_kind:
        problems.append(f"effects use {TEMPLATE_TAG!r}, so set tag_kind (e.g. 'domain')")
    if ability.max_level < 1:
        problems.append("max_level must be at least 1")
    if ability.is_flaw and ability.acquisition == AbilityDefinition.Acquisition.XP:
        problems.append("flaws aren't bought with XP; use 'free' or 'staff'")
    vocabulary = DBVocabulary()
    overrides = ability.budget_cost_overrides
    if not isinstance(overrides, dict):
        problems.append("budget_cost_overrides must be a dict of tag keys and nonnegative integers")
    elif overrides:
        if not ability.is_template:
            problems.append("budget_cost_overrides requires a template (tag_kind)")
        known = {tag.key for tag in vocabulary.tags(ability.tag_kind)}
        # Existing copies keep working after a tag is archived.
        known.update(
            TagDefinition.all_objects.filter(kind=ability.tag_kind).values_list("key", flat=True)
        )
        for key, cost in overrides.items():
            if key not in known:
                problems.append(f"budget_cost_overrides: unknown {ability.tag_kind} tag {key!r}")
            if type(cost) is not int or cost < 0:
                problems.append(f"budget_cost_overrides[{key!r}] must be a nonnegative integer")
    sample = None
    if ability.tag_kind:
        candidates = vocabulary.tags(ability.tag_kind)
        if candidates:
            sample = candidates[0].key
        else:
            problems.append(f"no tags of kind {ability.tag_kind!r} exist")
    ruleset = get_ruleset()
    for index, spec in enumerate(ability.effects):
        filled = fill_template(spec, sample)
        for level in sorted({1, max(ability.max_level, 1)}):
            for problem in effect_problems(
                filled, level=level, vocabulary=vocabulary, ruleset=ruleset
            ):
                problems.append(f"effects[{index}]: {problem}")
    return list(dict.fromkeys(problems))


def find_ability(text: str, *, include_archived: bool = False) -> AbilityDefinition:
    """Resolve player input to a catalog entry (exact key or name, else a unique prefix).

    Raises:
        LookupError: Player-readable "unknown" or "ambiguous" message.
    """
    manager = AbilityDefinition.all_objects if include_archived else AbilityDefinition.objects
    return match_spelling(list(manager.all()), text, "ability")


def split_ability_text(text: str, rhs: str | None = None) -> tuple[str, str | None]:
    """`"Domain Expertise: Performance"` (or lhs/rhs of `=`) into ability and tag text."""
    if rhs is not None and rhs.strip():
        return text.strip(), rhs.strip()
    name, sep, tag = text.partition(":")
    return name.strip(), (tag.strip() or None) if sep else None


def modifiers_for(character) -> list:
    """Modifiers from every equipped ability and flaw the character owns."""
    modifiers = []
    owned = CharacterAbility.objects.filter(character_id=character.id, equipped=True)
    for copy in owned.select_related("ability", "tag"):
        ability = copy.ability
        for spec in ability.effects_for(copy.tag):
            try:
                modifiers.append(
                    build_modifier(
                        spec,
                        level=copy.level,
                        key=copy.modifier_key,
                        label=copy.display_name,
                        source="flaw" if ability.is_flaw else "ability",
                        scope="ability",
                    )
                )
            except EffectSpecError as exc:
                logger.warning("rp_chargen: %s's %s has a bad effect: %s", character, copy, exc)
    return modifiers


def seed_entries() -> list[dict]:
    """The catalog seed named by `RP_CHARGEN_CATALOG_SEED` (empty if unset)."""
    path = conf.get("RP_CHARGEN_CATALOG_SEED")
    if not path:
        return []
    from evennia_links import resolve_dotted

    entries = resolve_dotted(path)
    return list(entries() if callable(entries) else entries)


def seed_catalog(*, update: bool = False, entries: list[dict] | None = None) -> dict:
    """Create missing tags (from the ruleset) and abilities (from the seed).

    Idempotent. With `update`, existing rows are overwritten from the seed too.

    Returns:
        Counts: `{"tags_created", "tags_updated", "created", "updated", "unchanged"}`.

    Raises:
        ValueError: An entry is malformed; nothing is written.
    """
    from django.db import transaction

    counts = dict.fromkeys(("tags_created", "tags_updated", "created", "updated", "unchanged"), 0)
    entries = seed_entries() if entries is None else entries
    with transaction.atomic():
        for tag in get_ruleset().tags.values():
            row, created = TagDefinition.all_objects.get_or_create(
                key=tag.key,
                defaults={
                    "name": tag.name,
                    "kind": tag.kind,
                    "aliases": list(tag.aliases),
                    "description": tag.description,
                },
            )
            if created:
                counts["tags_created"] += 1
            elif update:
                row.name, row.kind = tag.name, tag.kind
                row.aliases, row.description = list(tag.aliases), tag.description
                row.save()
                counts["tags_updated"] += 1
        for index, entry in enumerate(entries):
            fields = _seed_fields(entry, index)
            row = AbilityDefinition.all_objects.filter(key=fields["key"]).first()
            if row is not None and not update:
                counts["unchanged"] += 1
                continue
            row = row or AbilityDefinition(key=fields["key"])
            created = row.pk is None
            for name, value in fields.items():
                setattr(row, name, value)
            problems = definition_problems(row)
            if problems:
                raise ValueError(f"catalog seed {fields['key']!r}: {'; '.join(problems)}")
            row.save()
            counts["created" if created else "updated"] += 1
    return counts


def _seed_fields(entry, index: int) -> dict:
    if not isinstance(entry, dict) or "key" not in entry or "name" not in entry:
        raise ValueError(f"catalog seed [{index}] needs at least 'key' and 'name'")
    unknown = set(entry) - SEED_FIELDS
    if unknown:
        raise ValueError(f"catalog seed {entry['key']!r}: unknown fields {sorted(unknown)}")
    fields = dict(entry)
    if "xp_cost" in fields:
        try:
            fields["xp_cost"] = Decimal(str(fields["xp_cost"]))
        except InvalidOperation as exc:
            raise ValueError(f"catalog seed {entry['key']!r}: bad xp_cost") from exc
    return fields


__all__ = [
    "definition_problems",
    "find_ability",
    "modifiers_for",
    "seed_catalog",
    "seed_entries",
    "split_ability_text",
]
