# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Modifiers and effect kinds.

A **modifier** is anything that bends a check: an ability's bonus, a flaw, a
storyteller's situational penalty, later a combat stance or rider. It says
when it fires (`hooks()`), whether it applies to a given check (`applies()`),
who may see it (`visibility`), and what it does (`apply()`):

    class Modifier(Protocol):
        key: str            # stable id, recorded in the ledger
        label: str          # what a breakdown shows
        source: str         # where it came from ("ability", "challenge", ...)
        scope: str          # free-form family ("ability", "stance", "rider", ...)
        visibility: str     # OPEN, HIDDEN or SECRET (see `phases`)
        priority: int       # breakdown order only; never changes a number
        def hooks(self) -> set[str]: ...
        def applies(self, ctx) -> bool: ...
        def apply(self, phase, ctx) -> None: ...

`apply()` doesn't change anything directly. It calls `ctx.add(score=...,
rung=...)`, which records a ledger entry, and the pipeline folds the entries by
summing them. Sums don't care about order, so neither does the pipeline: the
same modifiers give the same numbers whatever order the providers return them
in. Entries sharing a `stack` name don't stack; only the strongest counts.

**Effect kinds** are modifiers built from data, so a catalog row can carry
`{"kind": "tag_bonus", "tags": ["performance"], "score": 8, "per_level": 1}`
and `build_modifier(spec, level=2)` turns it into a working modifier. The
built-in kinds are `score_bonus`, `tag_bonus` and `rung_shift`; a game adds its
own through `settings.RP_RULES_EFFECT_KINDS = {"kind": "dotted.path.Class"}`,
where the class has a `from_spec(spec, *, level, **meta)` classmethod that
raises `EffectSpecError` on bad data.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from evennia_rp_rules._config import resolve_dotted, setting
from evennia_rp_rules._numbers import fmt, to_fraction
from evennia_rp_rules.phases import BUILD, OPEN, PHASES, VISIBILITIES

if TYPE_CHECKING:
    from evennia_rp_rules.pipeline import ResolutionContext


@runtime_checkable
class Modifier(Protocol):
    """What the pipeline needs from a modifier. Subclass `BaseModifier` for defaults."""

    key: str
    label: str
    source: str
    scope: str
    visibility: str
    priority: int

    def hooks(self) -> set[str]: ...

    def applies(self, ctx: ResolutionContext) -> bool: ...

    def apply(self, phase: str, ctx: ResolutionContext) -> None: ...


class BaseModifier:
    """Defaults for a modifier: fires at BUILD, always applies, does nothing.

    Attributes:
        side: For a modifier that doesn't come from a subject (a provider's, or
            one passed on the `Check`), the side that owns it. `None` means the
            actor. A subject's own modifiers are always owned by its side.
    """

    key = "modifier"
    label = ""
    source = ""
    scope = ""
    visibility = OPEN
    priority = 0
    side: str | None = None
    stack: str | None = None
    tags: frozenset[str] = frozenset()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.key}>"

    def hooks(self) -> set[str]:
        return {BUILD}

    def applies(self, ctx: ResolutionContext) -> bool:
        return True

    def apply(self, phase: str, ctx: ResolutionContext) -> None:
        return None


@dataclass(frozen=True)
class LedgerEntry:
    """One itemised contribution to a check.

    Attributes:
        key, label, source, scope, priority: Copied from the modifier.
        owner: The side that owns the modifier (decides who may see it).
        side: The side the entry changes (usually the owner's own).
        phase: When it was added.
        score: Flat score added to `side`.
        rung: Rungs `side`'s rating moves (pips kept, clamped at the ends).
        visibility: Who may see it (see `phases.visible_to`).
        stack: Entries sharing a non-empty stack name don't stack.
        applied: False when a stronger entry in the same stack won.
        reason: Why it wasn't applied.
    """

    key: str
    label: str
    owner: str
    side: str
    phase: str
    score: Fraction = Fraction(0)
    rung: int = 0
    visibility: str = OPEN
    source: str = ""
    scope: str = ""
    priority: int = 0
    stack: str | None = None
    applied: bool = True
    reason: str = ""

    def sort_key(self) -> tuple:
        """Breakdown order: by phase, then priority, then names. Never affects numbers."""
        phase = PHASES.index(self.phase) if self.phase in PHASES else len(PHASES)
        return (
            phase,
            self.priority,
            self.owner,
            self.side,
            self.key,
            self.label,
            -self.rung,
            -self.score,
        )

    def describe(self) -> str:
        """`"Expertise: Performance +8"`, `"Flaw: Shy -2"`, `"Blessed: +1 rung"`."""
        parts = []
        if self.score:
            parts.append(fmt(self.score, signed=True))
        if self.rung:
            steps = abs(self.rung)
            parts.append(f"{'+' if self.rung > 0 else '-'}{steps} rung{'s' if steps != 1 else ''}")
        text = f"{self.label or self.key} {' '.join(parts) or '0'}"
        return text if self.applied else f"{text} (not applied: {self.reason})"

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "owner": self.owner,
            "side": self.side,
            "phase": self.phase,
            "score": str(self.score),
            "rung": self.rung,
            "visibility": self.visibility,
            "source": self.source,
            "scope": self.scope,
            "stack": self.stack,
            "applied": self.applied,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Note:
    """Free text a modifier attaches to a check ("The crowd roars!")."""

    key: str
    text: str
    owner: str
    phase: str
    visibility: str = OPEN

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "text": self.text,
            "owner": self.owner,
            "phase": self.phase,
            "visibility": self.visibility,
        }


# ---------------------------------------------------------------------------
# Effect kinds
# ---------------------------------------------------------------------------


class EffectSpecError(ValueError):
    """An effect spec is invalid.

    Attributes:
        messages: One line per problem.
    """

    def __init__(self, messages: list[str]):
        self.messages = list(messages)
        super().__init__("; ".join(self.messages))


OWN = "own"
OPPOSING = "opposing"
TAG_MATCHES = (OWN, OPPOSING)

_COMMON_FIELDS = {"kind", "key", "label", "visibility", "priority", "stack", "check_kinds"}


class _SpecReader:
    """Collects every problem in an effect spec before raising."""

    def __init__(self, spec, allowed: frozenset[str], kind: str):
        self.problems: list[str] = []
        self.kind = kind
        if not isinstance(spec, Mapping):
            raise EffectSpecError([f"{kind}: expected a mapping, got {type(spec).__name__}"])
        self.spec = spec
        unknown = set(spec) - allowed - _COMMON_FIELDS
        if unknown:
            self.problems.append(f"{kind}: unknown fields {sorted(unknown)}")

    def number(self, name: str, default=None, *, required=False) -> Fraction | None:
        if name not in self.spec:
            if required:
                self.problems.append(f"{self.kind}: missing {name!r}")
            return None if default is None else to_fraction(default)
        try:
            return to_fraction(self.spec[name])
        except (TypeError, ValueError, ZeroDivisionError):
            self.problems.append(f"{self.kind}: {name!r} must be a number, got {self.spec[name]!r}")
            return None

    def integer(self, name: str, *, required=False) -> int | None:
        value = self.spec.get(name)
        if value is None:
            if required:
                self.problems.append(f"{self.kind}: missing {name!r}")
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            self.problems.append(f"{self.kind}: {name!r} must be a whole number, got {value!r}")
            return None
        return value

    def choice(self, name: str, choices: tuple[str, ...], default: str) -> str:
        value = self.spec.get(name, default)
        if value not in choices:
            self.problems.append(
                f"{self.kind}: {name!r} must be one of {list(choices)}, got {value!r}"
            )
            return default
        return value

    def keys(self, name: str, *, required=False) -> frozenset[str]:
        value = self.spec.get(name)
        if value is None:
            if required:
                self.problems.append(f"{self.kind}: missing {name!r}")
            return frozenset()
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list | tuple | set | frozenset) or not all(
            isinstance(item, str) and item for item in value
        ):
            self.problems.append(f"{self.kind}: {name!r} must be a list of keys, got {value!r}")
            return frozenset()
        if required and not value:
            self.problems.append(f"{self.kind}: {name!r} must not be empty")
        return frozenset(value)

    def meta(self, *, key, label, source, scope, visibility) -> dict:
        spec = self.spec
        visibility = spec.get("visibility", visibility or OPEN)
        if visibility not in VISIBILITIES:
            self.problems.append(
                f"{self.kind}: visibility must be one of {list(VISIBILITIES)}, got {visibility!r}"
            )
        priority = spec.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            self.problems.append(f"{self.kind}: 'priority' must be a whole number")
        stack = spec.get("stack")
        if stack is not None and (not isinstance(stack, str) or not stack):
            self.problems.append(f"{self.kind}: 'stack' must be a non-empty name")
        for name in ("key", "label"):
            if name in spec and (not isinstance(spec[name], str) or not spec[name].strip()):
                self.problems.append(f"{self.kind}: {name!r} must be non-empty text")
        return {
            "key": key or spec.get("key") or self.kind,
            "label": spec.get("label") or label or "",
            "source": source,
            "scope": scope,
            "visibility": visibility,
            "priority": priority,
            "stack": stack,
            "check_kinds": self.keys("check_kinds"),
        }

    def finish(self) -> None:
        if self.problems:
            raise EffectSpecError(self.problems)


def _level(level, kind: str) -> int:
    if not isinstance(level, int) or isinstance(level, bool) or level < 1:
        raise EffectSpecError(
            [f"{kind}: level must be a whole number of at least 1, got {level!r}"]
        )
    return level


class _FilteredModifier(BaseModifier):
    """A data-built modifier with optional check-kind, stat and tag filters."""

    kind = ""

    def __init__(
        self,
        *,
        key: str,
        label: str = "",
        source: str = "",
        scope: str = "",
        visibility: str = OPEN,
        priority: int = 0,
        stack: str | None = None,
        check_kinds=(),
        stats=(),
        tags=(),
        match: str = OWN,
    ):
        self.key = key
        self.label = label or key
        self.source = source
        self.scope = scope
        self.visibility = visibility
        self.priority = priority
        self.stack = stack
        self.check_kinds = frozenset(check_kinds)
        self.stats = frozenset(stats)
        self.tags = frozenset(tags)
        if match not in TAG_MATCHES:
            raise ValueError(f"match must be one of {list(TAG_MATCHES)}, got {match!r}")
        self.match = match

    def applies(self, ctx: ResolutionContext) -> bool:
        if self.check_kinds and ctx.check.kind not in self.check_kinds:
            return False
        if self.stats and ctx.stat.key not in self.stats:
            return False
        if not self.tags:
            return True
        # OWN: the owner's own check carries the tag (Expertise). OPPOSING: the
        # other side's does, so the owner is resisting it (Resistance).
        tags = ctx.tags if self.match == OWN else ctx.check.tags_for(ctx.other_side)
        return bool(self.tags & tags)


class ScoreBonus(_FilteredModifier):
    """A flat score bonus (or, negative, a penalty) on the owner's side.

    Spec: `{"kind": "score_bonus", "score": 2}`, optionally with `per_level`
    (added for each level above the first) and filters `stats`, `tags` and
    `check_kinds` (all must pass; `tags` passes on any shared tag). `match`
    says whose tags count: `"own"` (the default, the owner's own check) or
    `"opposing"` (the other side's, for resisting what's aimed at the owner).
    """

    kind = "score_bonus"
    _fields = frozenset({"score", "per_level", "stats", "tags", "match"})

    def __init__(self, score, *, per_level=0, level: int = 1, **meta):
        super().__init__(**meta)
        self.level = level
        self.amount = to_fraction(score) + to_fraction(per_level) * (level - 1)

    @classmethod
    def from_spec(
        cls, spec, *, level=1, key=None, label=None, source="", scope="", visibility=None
    ):
        reader = _SpecReader(spec, cls._fields, cls.kind)
        level = _level(level, cls.kind)
        score = reader.number("score", required=True)
        per_level = reader.number("per_level", 0)
        stats = reader.keys("stats")
        tags = reader.keys("tags", required=cls is TagBonus)
        match = reader.choice("match", TAG_MATCHES, OWN)
        meta = reader.meta(key=key, label=label, source=source, scope=scope, visibility=visibility)
        reader.finish()
        return cls(
            score, per_level=per_level, level=level, stats=stats, tags=tags, match=match, **meta
        )

    def apply(self, phase: str, ctx: ResolutionContext) -> None:
        ctx.add(score=self.amount, stack=self.stack)


class TagBonus(ScoreBonus):
    """A score bonus on checks sharing one of its `tags`: Domain Expertise.

    Spec: `{"kind": "tag_bonus", "tags": ["performance"], "score": 8,
    "per_level": 1}`. At level 3 that's +10 on any check tagged Performance.
    It's a bonus, not a pip, so it may carry a rating past the next rung.
    With `"match": "opposing"` it applies when the *other* side's check
    carries the tag instead: Domain Resistance.
    """

    kind = "tag_bonus"

    def __init__(self, score, *, tags, **kwargs):
        if not tags:
            raise ValueError("TagBonus needs at least one tag")
        super().__init__(score, tags=tags, **kwargs)


class RungShift(_FilteredModifier):
    """Moves the owner's rating up (or down) whole rungs, keeping its pips.

    Spec: `{"kind": "rung_shift", "steps": 1}` with the same optional filters as
    `score_bonus`. Shifts clamp at the ends of the scale.
    """

    kind = "rung_shift"
    _fields = frozenset({"steps", "stats", "tags", "match"})

    def __init__(self, steps: int, **meta):
        super().__init__(**meta)
        self.steps = steps

    @classmethod
    def from_spec(
        cls, spec, *, level=1, key=None, label=None, source="", scope="", visibility=None
    ):
        reader = _SpecReader(spec, cls._fields, cls.kind)
        _level(level, cls.kind)
        steps = reader.integer("steps", required=True)
        stats = reader.keys("stats")
        tags = reader.keys("tags")
        match = reader.choice("match", TAG_MATCHES, OWN)
        meta = reader.meta(key=key, label=label, source=source, scope=scope, visibility=visibility)
        reader.finish()
        return cls(steps, stats=stats, tags=tags, match=match, **meta)

    def apply(self, phase: str, ctx: ResolutionContext) -> None:
        ctx.add(rung=self.steps, stack=self.stack)


BUILTIN_EFFECT_KINDS = {
    ScoreBonus.kind: ScoreBonus,
    TagBonus.kind: TagBonus,
    RungShift.kind: RungShift,
}


def effect_kinds() -> dict[str, type]:
    """Built-in effect kinds plus `settings.RP_RULES_EFFECT_KINDS`.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If a configured kind
            can't be imported or has no `from_spec`.
    """
    kinds = dict(BUILTIN_EFFECT_KINDS)
    for name, path in (setting("RP_RULES_EFFECT_KINDS") or {}).items():
        try:
            cls = resolve_dotted(path)
        except (ImportError, AttributeError) as exc:
            from django.core.exceptions import ImproperlyConfigured

            raise ImproperlyConfigured(
                f"RP_RULES_EFFECT_KINDS[{name!r}]: can't import {path!r}: {exc}"
            ) from exc
        if not callable(getattr(cls, "from_spec", None)):
            from django.core.exceptions import ImproperlyConfigured

            raise ImproperlyConfigured(
                f"RP_RULES_EFFECT_KINDS[{name!r}]: {path!r} has no from_spec() classmethod"
            )
        kinds[name] = cls
    return kinds


def build_modifier(
    spec: Mapping,
    *,
    level: int = 1,
    key: str | None = None,
    label: str | None = None,
    source: str = "",
    scope: str = "",
    visibility: str | None = None,
):
    """Build a modifier from an effect spec.

    Args:
        spec: `{"kind": ..., ...}`; see each kind for its fields. Every kind
            also takes `key`, `label`, `visibility`, `priority`, `stack` and
            `check_kinds`.
        level: The owning ability's level (1 for the base level).
        key, label, source, scope, visibility: Defaults from whatever owns the
            effect (an ability's key and name, say). `key` overrides the spec;
            the spec's own `label` and `visibility` override these.

    Raises:
        EffectSpecError: Unknown kind, or invalid fields for that kind.
    """
    if not isinstance(spec, Mapping):
        raise EffectSpecError([f"an effect must be a mapping, got {type(spec).__name__}"])
    kind = spec.get("kind")
    kinds = effect_kinds()
    if kind not in kinds:
        raise EffectSpecError([f"unknown effect kind {kind!r}; known kinds: {sorted(kinds)}"])
    return kinds[kind].from_spec(
        spec,
        level=level,
        key=key,
        label=label,
        source=source,
        scope=scope,
        visibility=visibility,
    )


def effect_problems(spec, *, level: int = 1, vocabulary=None, ruleset=None) -> list[str]:
    """Every problem with an effect spec, without raising.

    With `vocabulary`, tags the effect names must exist in it; with `ruleset`,
    stats it names must exist there. A catalog's `clean()` uses this.
    """
    try:
        modifier = build_modifier(spec, level=level)
    except EffectSpecError as exc:
        return exc.messages
    problems = []
    if vocabulary is not None:
        for tag in sorted(getattr(modifier, "tags", ()) or ()):
            if vocabulary.get(tag) is None:
                problems.append(f"unknown tag {tag!r}")
    if ruleset is not None:
        for stat in sorted(getattr(modifier, "stats", ()) or ()):
            if stat not in ruleset.stats:
                problems.append(f"unknown stat {stat!r}")
    return problems


__all__ = [
    "BUILTIN_EFFECT_KINDS",
    "BaseModifier",
    "EffectSpecError",
    "LedgerEntry",
    "Modifier",
    "Note",
    "RungShift",
    "ScoreBonus",
    "TagBonus",
    "build_modifier",
    "effect_kinds",
    "effect_problems",
]
