# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The shared outcome ladder.

Every resolver, whether a `+test` check today or a combat reaction later, lands
on a rung of one ordered ladder: `critical_failure` < `failure` <
`narrow_success` < `success` < `critical_success`, or whatever a ruleset
names. Each outcome has an integer **degree** (its position; higher is better)
and an explicit `is_success` flag, so code downstream can ask "did it work?"
without knowing the ladder's names.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from fractions import Fraction

from evennia_rp_rules import _spec
from evennia_rp_rules.issues import Issue


@dataclass(frozen=True)
class Outcome:
    """One rung of the outcome ladder.

    Attributes:
        key: Stable slug stored in check records.
        label: What players see.
        degree: Ordinal position; higher is better, and degrees are unique.
        is_success: Whether this outcome counts as the attempt succeeding.
    """

    key: str
    label: str
    degree: int
    is_success: bool


class OutcomeLadder:
    """Outcomes ordered by degree, worst first.

    Raises:
        ValueError: On duplicate keys or degrees, a ladder without both a
            success and a failure, or any failure ranked above a success.
    """

    def __init__(self, outcomes: list[Outcome]):
        ordered = sorted(outcomes, key=lambda o: o.degree)
        keys = [o.key for o in ordered]
        degrees = [o.degree for o in ordered]
        if len(set(keys)) != len(keys):
            raise ValueError("outcome keys must be unique")
        if len(set(degrees)) != len(degrees):
            raise ValueError("outcome degrees must be unique")
        problem = _ladder_shape_problem(ordered)
        if problem:
            raise ValueError(problem)
        self._outcomes: tuple[Outcome, ...] = tuple(ordered)
        self._by_key = {o.key: o for o in ordered}

    @classmethod
    def from_spec(cls, spec, issues: list[Issue]) -> OutcomeLadder | None:
        """Validate the ruleset's `outcomes` list, appending problems to `issues`."""
        raw = _spec.require_list(spec, issues, "outcomes")
        if raw is None:
            return None
        before = len(issues)
        outcomes: list[Outcome] = []
        keys: set[str] = set()
        degrees: set[int] = set()
        for index, item in enumerate(raw):
            where = f"outcomes[{index}]"
            item = _spec.require_mapping(item, issues, where)
            if item is None:
                continue
            key = _spec.require_key(item.get("key"), issues, f"{where}.key")
            label = _spec.require_text(item.get("label"), issues, f"{where}.label")
            degree = item.get("degree")
            if not isinstance(degree, int) or isinstance(degree, bool):
                _spec.malformed(issues, f"{where}.degree", f"expected an integer, got {degree!r}")
                degree = None
            success = item.get("success")
            if not isinstance(success, bool):
                _spec.malformed(
                    issues, f"{where}.success", f"expected true or false, got {success!r}"
                )
                success = None
            if key in keys:
                _spec.malformed(issues, f"{where}.key", f"duplicate outcome {key!r}")
            if degree in degrees:
                _spec.malformed(issues, f"{where}.degree", f"duplicate degree {degree}")
            keys.add(key)
            degrees.add(degree)
            if None not in (key, label, degree, success):
                outcomes.append(Outcome(key, label, degree, success))
        if len(issues) > before:
            return None
        problem = _ladder_shape_problem(sorted(outcomes, key=lambda o: o.degree))
        if problem:
            _spec.malformed(issues, "outcomes", problem)
            return None
        return cls(outcomes)

    def __iter__(self) -> Iterator[Outcome]:
        return iter(self._outcomes)

    def __len__(self) -> int:
        return len(self._outcomes)

    def __getitem__(self, key: str) -> Outcome:
        return self._by_key[key]

    def __contains__(self, key: object) -> bool:
        return key in self._by_key

    def get(self, key: str, default: Outcome | None = None) -> Outcome | None:
        return self._by_key.get(key, default)

    def keys(self) -> list[str]:
        return [o.key for o in self._outcomes]

    @property
    def best(self) -> Outcome:
        return self._outcomes[-1]

    @property
    def worst(self) -> Outcome:
        return self._outcomes[0]


def _ladder_shape_problem(ordered: list[Outcome]) -> str | None:
    if not any(o.is_success for o in ordered) or all(o.is_success for o in ordered):
        return "the ladder needs at least one success and at least one failure outcome"
    first_success = next(i for i, o in enumerate(ordered) if o.is_success)
    if not all(o.is_success for o in ordered[first_success:]):
        return "every success outcome must have a higher degree than every failure outcome"
    return None


class Odds(Mapping):
    """Exact probability of each outcome, as `{outcome_key: Fraction}`.

    Iterates in ladder order (worst first) and always carries every outcome on
    the ladder, unreachable ones at zero, so tables line up.
    """

    def __init__(self, ladder: OutcomeLadder, probabilities: Mapping[str, Fraction]):
        unknown = set(probabilities) - set(ladder.keys())
        if unknown:
            raise KeyError(f"not on the ladder: {', '.join(sorted(unknown))}")
        self.ladder = ladder
        self._p = {o.key: Fraction(probabilities.get(o.key, 0)) for o in ladder}

    def __getitem__(self, key: str) -> Fraction:
        return self._p[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._p)

    def __len__(self) -> int:
        return len(self._p)

    def __repr__(self) -> str:
        inner = ", ".join(f"{key}={float(p):.4f}" for key, p in self._p.items())
        return f"<Odds {inner}>"

    @property
    def success(self) -> Fraction:
        """Probability that the outcome counts as a success."""
        return sum((self._p[o.key] for o in self.ladder if o.is_success), Fraction(0))

    @property
    def failure(self) -> Fraction:
        return 1 - self.success

    def at_least(self, key: str) -> Fraction:
        """Probability of `key` or anything better."""
        floor = self.ladder[key].degree
        return sum((self._p[o.key] for o in self.ladder if o.degree >= floor), Fraction(0))


def ladder_from_spec(spec, issues: list[Issue]) -> OutcomeLadder | None:
    return OutcomeLadder.from_spec(spec, issues)


__all__ = ["Odds", "Outcome", "OutcomeLadder", "ladder_from_spec"]
