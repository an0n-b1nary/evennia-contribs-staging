# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""What wearing an item asks of its wearer's build, in evennia_rp_chargen's terms.

A requirement is one of:

    pips      at least `count` + pips on a stat        "Strength +2", "Strength ++"
    weakness  at least `count` weakness on a stat      "Resolve -1", "Resolve -"
    ability   an ability equipped (with its tag)       "ability Proficiency: Blades"
    flaw      a flaw held (with its tag)               "flaw Reckless"

Requirements are stored by key (stat, ability and tag keys), never by name, so
renaming something in the ruleset or catalog doesn't orphan them.

Each requirement is in one of four states for a character:

    met        satisfied
    unmet      not satisfied; the item can't be worn
    unattuned  an ability requirement the character doesn't own: the item can
               still be worn, with a notice, and it has no mechanical effect
    unknown    names something the ruleset or catalog no longer has
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

PIPS = "pips"
WEAKNESS = "weakness"
ABILITY = "ability"
FLAW = "flaw"
KINDS = (PIPS, WEAKNESS, ABILITY, FLAW)

MET = "met"
UNMET = "unmet"
UNATTUNED = "unattuned"
UNKNOWN = "unknown"

USAGE = "Give a requirement like: <stat> +2, <stat> -1, ability <name>[: <tag>], or flaw <name>."

_STAT_TEXT = re.compile(r"^(?P<stat>.+?)\s*(?P<marks>\++|-+|[+-]\s*\d+)$")


class RequirementError(ValueError):
    """A requirement can't be parsed or resolved. The message is fit to show the player."""


@dataclass(frozen=True)
class Requirement:
    kind: str
    stat: str = ""
    count: int = 0
    ability: str = ""
    tag: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in ("", 0, None)}

    @classmethod
    def from_dict(cls, data: dict) -> Requirement:
        return cls(
            kind=data.get("kind", ""),
            stat=data.get("stat", ""),
            count=int(data.get("count", 0)),
            ability=data.get("ability", ""),
            tag=data.get("tag"),
        )

    @property
    def on_stat(self) -> bool:
        return self.kind in (PIPS, WEAKNESS)

    def matches_ability(self, ability_key: str, tag_key: str | None) -> bool:
        return self.kind in (ABILITY, FLAW) and (self.ability, self.tag) == (ability_key, tag_key)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse(text: str) -> Requirement:
    """Player text to a `Requirement`, resolved against the ruleset and catalog."""
    text = (text or "").strip()
    word, _, rest = text.partition(" ")
    if word.lower() in (ABILITY, FLAW):
        return _parse_ability(word.lower(), rest)
    match = _STAT_TEXT.match(text)
    if not match:
        raise RequirementError(USAGE)
    from evennia_rp_chargen.pips import PipPolicy

    from evennia_rp_rules.ruleset import get_ruleset

    try:
        stat = get_ruleset().find_stat(match["stat"])
    except LookupError as exc:
        raise RequirementError(str(exc)) from None
    marks = match["marks"].replace(" ", "")
    sign = marks[0]
    count = len(marks) if set(marks) == {sign} else int(marks[1:])
    if count < 1:
        raise RequirementError("A requirement needs at least one pip.")
    policy = PipPolicy.from_settings()
    limit = policy.edge_limit(stat.scale) if sign == "+" else policy.weakness_limit(stat.scale)
    if count > limit:
        raise RequirementError(
            f"{stat.name} can't carry {count} of those, so nobody could wear it."
        )
    return Requirement(PIPS if sign == "+" else WEAKNESS, stat=stat.key, count=count)


def _parse_ability(kind: str, text: str) -> Requirement:
    from evennia_rp_chargen.catalog import find_ability, split_ability_text
    from evennia_rp_chargen.vocabulary import DBVocabulary

    name, tag_text = split_ability_text(text)
    if not name:
        raise RequirementError(USAGE)
    try:
        ability = find_ability(name)
    except LookupError as exc:
        raise RequirementError(str(exc)) from None
    if kind == ABILITY and ability.is_flaw:
        raise RequirementError(f"{ability.name} is a flaw; require it with: flaw {ability.name}")
    if kind == FLAW and not ability.is_flaw:
        raise RequirementError(
            f"{ability.name} isn't a flaw; require it with: ability {ability.name}"
        )
    tag = None
    if ability.is_template:
        if not tag_text:
            raise RequirementError(
                f"Which {ability.tag_kind}? For example: {kind} {ability.name}: <{ability.tag_kind}>"
            )
        try:
            tag = DBVocabulary().find(tag_text, kind=ability.tag_kind).key
        except LookupError as exc:
            raise RequirementError(str(exc)) from None
    elif tag_text:
        raise RequirementError(f"{ability.name} isn't chosen per {ability.tag_kind or 'tag'}.")
    return Requirement(kind, ability=ability.key, tag=tag)


# ---------------------------------------------------------------------------
# Describing
# ---------------------------------------------------------------------------


def _ability_name(req: Requirement) -> str | None:
    from evennia_rp_chargen.models import AbilityDefinition
    from evennia_rp_chargen.vocabulary import DBVocabulary

    ability = AbilityDefinition.all_objects.filter(key=req.ability).first()
    if ability is None:
        return None
    if req.tag is None:
        return ability.display_name()
    tag = DBVocabulary().get(req.tag)
    return ability.display_name(tag) if tag is not None else None


def describe(req: Requirement) -> str:
    """`"Strength ++"`, `"Proficiency: Blades equipped"`, `"the flaw Reckless"`."""
    if req.on_stat:
        from evennia_rp_rules.ruleset import get_ruleset

        stat = get_ruleset().stats.get(req.stat)
        if stat is None:
            return f"an unknown stat ({req.stat})"
        return f"{stat.name} {('+' if req.kind == PIPS else '-') * req.count}"
    name = _ability_name(req)
    if name is None:
        label = f"{req.ability}: {req.tag}" if req.tag else req.ability
        return f"an unknown {req.kind} ({label})"
    return f"{name} equipped" if req.kind == ABILITY else f"the flaw {name}"


# ---------------------------------------------------------------------------
# Evaluating
# ---------------------------------------------------------------------------


def rating_meets(req: Requirement, rating) -> bool:
    """Whether a stat `rating` (None: unset) satisfies a pips or weakness requirement."""
    if rating is None:
        return False
    have = rating.edge if req.kind == PIPS else rating.weakness
    return have >= req.count


def status(character, req: Requirement) -> str:
    """`MET`, `UNMET`, `UNATTUNED` or `UNKNOWN` for `character` right now."""
    if req.on_stat:
        from evennia_rp_chargen.stats import StatHandler

        from evennia_rp_rules.ruleset import get_ruleset

        ruleset = get_ruleset()
        if req.stat not in ruleset.stats:
            return UNKNOWN
        return MET if rating_meets(req, StatHandler(character, ruleset).get(req.stat)) else UNMET
    if req.kind not in (ABILITY, FLAW) or _ability_name(req) is None:
        return UNKNOWN
    from evennia_rp_chargen.models import CharacterAbility

    copies = CharacterAbility.objects.filter(character_id=character.id, ability__key=req.ability)
    copies = copies.filter(tag__key=req.tag) if req.tag else copies.filter(tag__isnull=True)
    copy = copies.first()
    if copy is None:
        return UNATTUNED if req.kind == ABILITY else UNMET
    return MET if req.kind == FLAW or copy.equipped else UNMET


__all__ = [
    "ABILITY",
    "FLAW",
    "KINDS",
    "MET",
    "PIPS",
    "UNATTUNED",
    "UNKNOWN",
    "UNMET",
    "WEAKNESS",
    "Requirement",
    "RequirementError",
    "describe",
    "parse",
    "rating_meets",
    "status",
]
