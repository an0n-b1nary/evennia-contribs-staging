# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Checks: one stat tested against a difficulty or an opponent.

    check = Check("test", ana, "charisma", tags={"performance"}, difficulty="A")
    result = resolve_check(check)                 # rolls; fires check_resolved
    result.outcome.label                          # "Narrow Success"
    result.entries_for("actor")                   # the breakdown Ana may see
    estimate_check(check, viewer="actor").odds    # exact odds, nothing rolled

A `Check` is frozen data. `kind` names the system asking (`"test"` for
`+test`; combat will use its own), so modifiers and listeners can tell checks
apart without importing each other. The actor and opponent are anything
`get_subject()` understands: a character, an NPC stat block, a plain dict.

Resolution runs the modifier pipeline (see `pipeline`) and hands the folded
ratings to the ruleset's resolver. Everything the result knows, the hidden
entries included, is in `as_dict()`, for a game to store with its record and
filter later with `entries_for()`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import KW_ONLY, dataclass, field
from fractions import Fraction
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from evennia_rp_rules.phases import ACTOR, PUBLIC, TARGET, VIEWERS, visible_to
from evennia_rp_rules.scales import Rating

if TYPE_CHECKING:
    from evennia_rp_rules.dice import Roller
    from evennia_rp_rules.modifiers import LedgerEntry, Note
    from evennia_rp_rules.outcomes import Odds, Outcome
    from evennia_rp_rules.resolvers import Resolution
    from evennia_rp_rules.ruleset import Ruleset, StatDef


class CheckError(ValueError):
    """A check can't be made. The message is fit to show the player."""


def _keys(values, name: str) -> frozenset[str]:
    if values is None:
        return frozenset()
    if isinstance(values, str):
        values = [values]
    keys = set()
    for value in values:
        key = getattr(value, "key", value)
        if not isinstance(key, str) or not key:
            raise ValueError(f"{name} must be keys or tag definitions, got {value!r}")
        keys.add(key)
    return frozenset(keys)


@dataclass(frozen=True, eq=False)
class Check:
    """One check, as data.

    Attributes:
        kind: The system making it (`"test"`).
        actor: Whoever makes the check (anything `get_subject()` accepts).
        stat: The actor's stat key.
        tags: Tag keys the check carries (a domain, an element).
        difficulty: A stated difficulty: a `Rating`, or text such as `"A+"`
            parsed on the stat's scale. Exactly one of `difficulty` and
            `opponent` must be given.
        opponent: Whoever opposes the check; it rolls the ruleset's opposed noise.
        opponent_stat: The opponent's stat key (default: `stat`).
        opponent_tags: Tags on the opponent's side (default: none).
        modifiers: Extra modifiers for this check alone (a challenge's twist,
            a storyteller's call). Owned by the actor unless they set `side`.
        context: Free-form facts about where and why (room, scene, challenge).
            The kernel never reads it; modifiers and listeners may.
        extra: Free-form data for a custom resolver or modifiers.
    """

    kind: str
    actor: Any
    stat: str
    _: KW_ONLY
    tags: frozenset[str] = frozenset()
    difficulty: Rating | str | None = None
    opponent: Any = None
    opponent_stat: str | None = None
    opponent_tags: frozenset[str] = frozenset()
    modifiers: tuple = ()
    context: Mapping = field(default_factory=dict)
    extra: Mapping = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.kind, str) or not self.kind:
            raise ValueError(f"kind must be non-empty text, got {self.kind!r}")
        for name in ("stat", "opponent_stat"):
            value = getattr(self, name)
            value = getattr(value, "key", value)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be a stat key, got {value!r}")
            object.__setattr__(self, name, value)
        if self.stat is None:
            raise ValueError("stat is required")
        if (self.difficulty is None) == (self.opponent is None):
            raise ValueError("give exactly one of difficulty and opponent")
        object.__setattr__(self, "tags", _keys(self.tags, "tags"))
        object.__setattr__(self, "opponent_tags", _keys(self.opponent_tags, "opponent_tags"))
        object.__setattr__(self, "modifiers", tuple(self.modifiers or ()))
        object.__setattr__(self, "context", MappingProxyType(dict(self.context or {})))
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra or {})))

    @property
    def opposed(self) -> bool:
        return self.opponent is not None

    def stat_for(self, side: str) -> str:
        return self.stat if side == ACTOR else (self.opponent_stat or self.stat)

    def tags_for(self, side: str) -> frozenset[str]:
        return self.tags if side == ACTOR else self.opponent_tags


class _Breakdown:
    """What results and estimates share: base and effective ratings and a ledger."""

    check: Check
    ruleset_version: str
    ruleset_digest: str
    stats: Mapping[str, StatDef]
    ratings: Mapping[str, Rating]
    effective: Mapping[str, Rating]
    bonuses: Mapping[str, Fraction]
    ledger: tuple[LedgerEntry, ...]
    notes: tuple[Note, ...]

    @property
    def actor_rating(self) -> Rating:
        """The actor's rating before modifiers."""
        return self.ratings[ACTOR]

    @property
    def target_rating(self) -> Rating:
        """The difficulty or opponent's rating before modifiers."""
        return self.ratings[TARGET]

    def score(self, side: str) -> Fraction:
        """Effective score: shifted rating plus every applied bonus."""
        return self.effective[side].score() + self.bonuses[side]

    def entries_for(self, viewer: str = PUBLIC) -> list[LedgerEntry]:
        """The ledger entries `viewer` (`"staff"`, `"actor"`, `"target"`, `"public"`) may see."""
        _check_viewer(viewer)
        return [e for e in self.ledger if visible_to(e.visibility, e.owner, viewer)]

    def notes_for(self, viewer: str = PUBLIC) -> list[Note]:
        _check_viewer(viewer)
        return [n for n in self.notes if visible_to(n.visibility, n.owner, viewer)]

    def _sides_dict(self) -> dict:
        return {
            side: {
                "stat": self.stats[side].key,
                "rating": self.ratings[side].display(),
                "effective": self.effective[side].display(),
                "bonus": str(self.bonuses[side]),
                "score": str(self.score(side)),
            }
            for side in (ACTOR, TARGET)
        }

    def _base_dict(self) -> dict:
        return {
            "kind": self.check.kind,
            "tags": sorted(self.check.tags),
            "opponent_tags": sorted(self.check.opponent_tags),
            "opposed": self.check.opposed,
            "ruleset": {"version": self.ruleset_version, "digest": self.ruleset_digest},
            "sides": self._sides_dict(),
            "ledger": [entry.as_dict() for entry in self.ledger],
            "notes": [note.as_dict() for note in self.notes],
        }


def _check_viewer(viewer: str) -> None:
    if viewer not in VIEWERS:
        raise ValueError(f"viewer must be one of {list(VIEWERS)}, got {viewer!r}")


@dataclass(frozen=True, eq=False)
class CheckResult(_Breakdown):
    """A resolved check.

    Attributes:
        check: The input.
        ruleset_version, ruleset_digest: Which rules produced it.
        stats: `{side: StatDef}`.
        ratings: `{side: Rating}` before modifiers.
        effective: `{side: Rating}` after rung shifts.
        bonuses: `{side: Fraction}`, the applied flat bonuses.
        ledger: Every entry, hidden ones included, in breakdown order.
        notes: Every note, hidden ones included.
        resolution: The resolver's output (roll, margin, outcome).
    """

    check: Check
    ruleset_version: str
    ruleset_digest: str
    stats: Mapping[str, StatDef]
    ratings: Mapping[str, Rating]
    effective: Mapping[str, Rating]
    bonuses: Mapping[str, Fraction]
    ledger: tuple[LedgerEntry, ...]
    notes: tuple[Note, ...]
    resolution: Resolution

    @property
    def outcome(self) -> Outcome:
        return self.resolution.outcome

    @property
    def is_success(self) -> bool:
        return self.resolution.outcome.is_success

    def as_dict(self) -> dict:
        """JSON-safe record of everything, for staff review and audit."""
        data = self._base_dict()
        data["resolution"] = self.resolution.as_dict()
        data["outcome"] = {
            "key": self.outcome.key,
            "label": self.outcome.label,
            "degree": self.outcome.degree,
            "success": self.outcome.is_success,
        }
        return data


@dataclass(frozen=True, eq=False)
class CheckEstimate(_Breakdown):
    """Exact odds for a check from one viewer's perspective. Nothing is rolled.

    Modifiers the viewer may not see are left out entirely, so an estimate is
    exactly as good as what the viewer knows.
    """

    check: Check
    ruleset_version: str
    ruleset_digest: str
    stats: Mapping[str, StatDef]
    ratings: Mapping[str, Rating]
    effective: Mapping[str, Rating]
    bonuses: Mapping[str, Fraction]
    ledger: tuple[LedgerEntry, ...]
    notes: tuple[Note, ...]
    odds: Odds
    viewer: str

    def as_dict(self) -> dict:
        data = self._base_dict()
        data["viewer"] = self.viewer
        data["odds"] = {key: str(p) for key, p in self.odds.items()}
        return data


def resolve_check(
    check: Check,
    *,
    roller: Roller | None = None,
    ruleset: Ruleset | None = None,
    send_signal: bool = True,
) -> CheckResult:
    """Run the pipeline, roll, and fire `check_resolved`.

    Args:
        check: What to resolve.
        roller: Dice to roll with; `settings.RP_RULES_ROLLER` (a dotted path
            to a zero-argument factory) or a fresh `RandomRoller` by default.
        ruleset: Defaults to `get_ruleset()`.
        send_signal: Set False for a dry run nobody should hear about.

    Raises:
        CheckError: Unknown stat, a side without stats or without that stat,
            or a difficulty that doesn't parse.
    """
    from evennia_rp_rules.pipeline import run_check

    result = run_check(check, roller=roller, ruleset=ruleset)
    if send_signal:
        from evennia_rp_rules.signals import check_resolved

        check_resolved.send(sender=Check, check=check, result=result)
    return result


def estimate_check(
    check: Check, *, viewer: str = PUBLIC, ruleset: Ruleset | None = None
) -> CheckEstimate:
    """Exact odds for `check`, counting only modifiers `viewer` may see.

    Runs BUILD and PRE_RESOLVE but not ON_OUTCOME, rolls nothing and fires no
    signal. `viewer` is `"actor"` for "what are my chances?", `"target"` for
    an opponent weighing a reaction, `"staff"` for the true odds.

    Raises:
        CheckError: As `resolve_check`.
    """
    from evennia_rp_rules.pipeline import run_estimate

    _check_viewer(viewer)
    return run_estimate(check, viewer=viewer, ruleset=ruleset)


def tag_keys(tags: Iterable) -> frozenset[str]:
    """Normalise tag keys or `TagDef`s to a frozenset of keys."""
    return _keys(tags, "tags")


__all__ = [
    "Check",
    "CheckError",
    "CheckEstimate",
    "CheckResult",
    "estimate_check",
    "resolve_check",
    "tag_keys",
]
