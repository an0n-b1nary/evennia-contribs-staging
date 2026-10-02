# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Resolvers: turn a contest into an outcome.

A `Contest` is the resolver's whole input: an actor's rating against a target
rating (a stated difficulty, or an opponent's rating for opposed checks), plus
flat score bonuses that modifiers have already folded in. Resolvers know
nothing about characters, commands, or sessions, so they're callable from a
unit test with two bare ratings, and `+test` and a future combat system share
them without importing each other.

`GradedResolver` is the reference implementation:

    margin  = (actor score + actor bonus) - (target score + target bonus) + noise
    outcome = the first band (best first) whose `min` the margin reaches

where the scores come from the ratings' scale (rung score plus piecewise pip
value) and the noise is a dice expression centred wherever the ruleset puts
it. Because the noise distribution is exact, `estimate()` gives exact odds;
the same code path backs live resolution and the odds tool.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import pairwise
from typing import Protocol, runtime_checkable

from evennia_rp_rules._numbers import Number, to_fraction
from evennia_rp_rules.dice import DiceSpec, RandomRoller, Roll, Roller, distribution
from evennia_rp_rules.outcomes import Odds, Outcome, OutcomeLadder
from evennia_rp_rules.scales import Rating


@dataclass(frozen=True)
class Contest:
    """Everything a resolver needs.

    Attributes:
        actor: The acting side's rating.
        target: The difficulty, or the opposing side's rating.
        actor_bonus: Net flat score bonus on the actor's side.
        target_bonus: Net flat score bonus on the target's side.
        opposed: True when the target is an opponent rather than a stated
            difficulty; resolvers may roll differently (see `opposed_noise`).
    """

    actor: Rating
    target: Rating
    actor_bonus: Fraction = field(default=Fraction(0))
    target_bonus: Fraction = field(default=Fraction(0))
    opposed: bool = False

    def __post_init__(self):
        object.__setattr__(self, "actor_bonus", to_fraction(self.actor_bonus))
        object.__setattr__(self, "target_bonus", to_fraction(self.target_bonus))


@dataclass(frozen=True)
class Resolution:
    """The result of resolving one contest.

    Attributes:
        resolver: The resolver's key.
        contest: The input.
        actor_score, target_score: Effective scores, bonuses included.
        roll: The noise roll.
        margin: Actor minus target plus the roll.
        outcome: Where the margin landed on the ladder.
    """

    resolver: str
    contest: Contest
    actor_score: Fraction
    target_score: Fraction
    roll: Roll
    margin: Fraction
    outcome: Outcome

    @property
    def is_success(self) -> bool:
        return self.outcome.is_success

    def as_dict(self) -> dict:
        """JSON-safe record of the resolution, exact numbers as strings."""
        return {
            "resolver": self.resolver,
            "actor": self.contest.actor.display(),
            "target": self.contest.target.display(),
            "actor_bonus": str(self.contest.actor_bonus),
            "target_bonus": str(self.contest.target_bonus),
            "opposed": self.contest.opposed,
            "actor_score": str(self.actor_score),
            "target_score": str(self.target_score),
            "noise": str(self.roll.spec),
            "roll": self.roll.total,
            "faces": [list(group) for group in self.roll.faces]
            if self.roll.faces is not None
            else None,
            "margin": str(self.margin),
            "outcome": self.outcome.key,
        }


@runtime_checkable
class Resolver(Protocol):
    """What the check pipeline and the odds tool need from a resolver."""

    key: str
    ladder: OutcomeLadder

    def resolve(self, contest: Contest, roller: Roller | None = None) -> Resolution: ...

    def estimate(self, contest: Contest) -> Odds: ...


class ResolverConfigError(ValueError):
    """Resolver parameters in a ruleset are invalid.

    Attributes:
        messages: One line per problem; the ruleset reports each as E002.
    """

    def __init__(self, messages: list[str]):
        self.messages = list(messages)
        super().__init__("; ".join(self.messages))


@dataclass(frozen=True)
class Band:
    """Margins at or above `minimum` land on `outcome` (`None`: everything left)."""

    outcome: Outcome
    minimum: Fraction | None


class GradedResolver:
    """Score-versus-score with additive dice noise and outcome bands.

    Args:
        ladder: The ruleset's outcome ladder.
        noise: Dice expression added to the margin, e.g. `"1d10-1d10"`.
        bands: `(outcome_key, min_margin)` pairs, best outcome first, with
            strictly decreasing minimums; the last pair's minimum is `None`
            and catches every lower margin.
        opposed_noise: Noise for opposed contests; defaults to `noise`.

    Raises:
        ResolverConfigError: On bad dice, unknown outcomes, unordered bands, or
            bands whose outcomes get *better* as the margin falls.
    """

    key = "graded"

    def __init__(
        self,
        ladder: OutcomeLadder,
        *,
        noise: str | DiceSpec,
        bands: list[tuple[str, Number | None]],
        opposed_noise: str | DiceSpec | None = None,
    ):
        problems: list[str] = []
        self.ladder = ladder
        self.noise = _parse_noise(noise, "noise", problems)
        self.opposed_noise = (
            _parse_noise(opposed_noise, "opposed_noise", problems)
            if opposed_noise is not None
            else self.noise
        )
        self.bands = _build_bands(ladder, bands, problems)
        if problems:
            raise ResolverConfigError(problems)

    @classmethod
    def from_params(cls, ladder: OutcomeLadder, params: Mapping) -> GradedResolver:
        """Build from a ruleset's `resolver.params` mapping.

        `bands` is a list of `{"outcome": key, "min": number}` mappings, best
        first; the last omits `min`.
        """
        if not isinstance(params, Mapping):
            raise ResolverConfigError(["params must be a mapping"])
        unknown = set(params) - {"noise", "bands", "opposed_noise"}
        problems = [f"unknown parameter {name!r}" for name in sorted(unknown)]
        for required in ("noise", "bands"):
            if required not in params:
                problems.append(f"missing parameter {required!r}")
        raw_bands = params.get("bands")
        pairs: list[tuple[str, Number | None]] = []
        if "bands" in params:
            if not isinstance(raw_bands, list | tuple) or not raw_bands:
                problems.append("bands must be a non-empty list")
            else:
                for index, band in enumerate(raw_bands):
                    if not isinstance(band, Mapping) or "outcome" not in band:
                        problems.append(f"bands[{index}] must be a mapping with an 'outcome'")
                        continue
                    extra = set(band) - {"outcome", "min"}
                    if extra:
                        problems.append(f"bands[{index}] has unknown fields {sorted(extra)}")
                    pairs.append((band["outcome"], band.get("min")))
        if problems:
            raise ResolverConfigError(problems)
        return cls(
            ladder, noise=params["noise"], bands=pairs, opposed_noise=params.get("opposed_noise")
        )

    # -- scoring ------------------------------------------------------------

    def scores(self, contest: Contest) -> tuple[Fraction, Fraction]:
        """Effective (actor, target) scores, bonuses included."""
        return (
            contest.actor.score() + contest.actor_bonus,
            contest.target.score() + contest.target_bonus,
        )

    def noise_for(self, contest: Contest) -> DiceSpec:
        return self.opposed_noise if contest.opposed else self.noise

    def band_for(self, margin: Fraction) -> Outcome:
        for band in self.bands:
            if band.minimum is None or margin >= band.minimum:
                return band.outcome
        raise AssertionError("bands always end with a catch-all")  # pragma: no cover

    # -- resolution ---------------------------------------------------------

    def resolve(self, contest: Contest, roller: Roller | None = None) -> Resolution:
        actor_score, target_score = self.scores(contest)
        roll = (roller or RandomRoller()).roll(self.noise_for(contest))
        margin = actor_score - target_score + roll.total
        return Resolution(
            self.key, contest, actor_score, target_score, roll, margin, self.band_for(margin)
        )

    def estimate(self, contest: Contest) -> Odds:
        actor_score, target_score = self.scores(contest)
        base = actor_score - target_score
        probabilities: dict[str, Fraction] = {}
        for total, p in distribution(self.noise_for(contest)).items():
            key = self.band_for(base + total).key
            probabilities[key] = probabilities.get(key, Fraction(0)) + p
        return Odds(self.ladder, probabilities)

    def roll_ranges(self, contest: Contest) -> dict[str, tuple[int, int]]:
        """For each reachable outcome, the lowest and highest noise roll producing it.

        Bands are monotone in the margin, so each outcome's rolls are one
        contiguous run; this is the "needed a 7 or better" view staff see.
        """
        actor_score, target_score = self.scores(contest)
        base = actor_score - target_score
        ranges: dict[str, tuple[int, int]] = {}
        for total in distribution(self.noise_for(contest)):
            key = self.band_for(base + total).key
            low, _ = ranges.get(key, (total, total))
            ranges[key] = (min(low, total), total)
        return ranges


def _parse_noise(value, name: str, problems: list[str]) -> DiceSpec | None:
    try:
        return DiceSpec.parse(value)
    except (TypeError, ValueError) as exc:
        problems.append(f"{name}: {exc}")
        return None


def _build_bands(ladder: OutcomeLadder, pairs, problems: list[str]) -> tuple[Band, ...]:
    bands: list[Band] = []
    seen: set[str] = set()
    if not pairs:
        problems.append("bands must not be empty")
    for index, (key, minimum) in enumerate(pairs):
        outcome = ladder.get(key) if isinstance(key, str) else None
        if outcome is None:
            problems.append(f"bands[{index}]: unknown outcome {key!r}")
            continue
        if key in seen:
            problems.append(f"bands[{index}]: outcome {key!r} appears in more than one band")
        seen.add(key)
        last = index == len(pairs) - 1
        if last and minimum is not None:
            problems.append(
                f"bands[{index}]: the last band catches every lower margin, so it takes no 'min'"
            )
        if not last and minimum is None:
            problems.append(f"bands[{index}]: only the last band may omit 'min'")
        threshold = None
        if minimum is not None:
            try:
                threshold = to_fraction(minimum)
            except (TypeError, ValueError):
                problems.append(f"bands[{index}]: 'min' must be a number, got {minimum!r}")
        bands.append(Band(outcome, threshold))
    if problems:
        return tuple(bands)
    thresholds = [b.minimum for b in bands if b.minimum is not None]
    if any(upper <= lower for upper, lower in pairwise(thresholds)):
        problems.append("bands: 'min' values must strictly decrease, best outcome first")
    degrees = [b.outcome.degree for b in bands]
    if any(upper < lower for upper, lower in pairwise(degrees)):
        problems.append("bands: outcomes must not improve as the margin falls")
    return tuple(bands)


__all__ = ["Band", "Contest", "GradedResolver", "Resolution", "Resolver", "ResolverConfigError"]
