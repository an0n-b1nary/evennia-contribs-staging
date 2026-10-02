# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Dice expressions, rollers, and exact distributions.

A `DiceSpec` is a sum of dice and constants: `"1d20"`, `"2d6-7"`,
`"1d10-1d10"`. Rolling is delegated to a `Roller` so resolution never touches
a module-level RNG:

    RandomRoller()          — live play (or `RandomRoller(random.Random(42))`
                              for a reproducible sequence)
    ScriptedRoller([3, -2]) — tests: returns these totals in order, and
                              refuses totals the expression can't produce

`distribution(spec)` enumerates every total exactly, as `Fraction`s that sum
to 1, which is what the odds tool and resolver estimates are built on.
"""

from __future__ import annotations

import random
import re
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from typing import Protocol, runtime_checkable

# Bounds that keep exact enumeration cheap (a few million steps, cached).
MAX_DICE = 20
MAX_SIDES = 1000
MAX_SPAN = 2000

_TERM = re.compile(r"\s*([+-])?\s*(?:(\d*)\s*[dD]\s*(\d+)|(\d+))\s*")


@dataclass(frozen=True)
class DiceTerm:
    """`count` dice of `sides` sides, added (`sign=1`) or subtracted (`sign=-1`)."""

    count: int
    sides: int
    sign: int = 1


@dataclass(frozen=True)
class DiceSpec:
    """A parsed dice expression.

    Attributes:
        terms: The dice groups, in written order.
        constant: The sum of every constant term.
    """

    terms: tuple[DiceTerm, ...]
    constant: int = 0

    @classmethod
    def parse(cls, text: str | DiceSpec) -> DiceSpec:
        """Parse `"2d6+1"`, `"d20"`, `"1d10 - 1d10"` and so on.

        Raises:
            ValueError: On syntax errors, zero dice or sides, or expressions
                beyond `MAX_DICE` dice, `MAX_SIDES` sides per die, or a
                `MAX_SPAN` gap between the lowest and highest total.
        """
        if isinstance(text, DiceSpec):
            return text
        source = str(text)
        if not source.strip():
            raise ValueError("empty dice expression")
        terms: list[DiceTerm] = []
        constant = 0
        position = 0
        first = True
        while position < len(source):
            match = _TERM.match(source, position)
            if not match or match.end() == position:
                raise ValueError(f"can't parse dice expression {source!r} at {source[position:]!r}")
            sign_text, count_text, sides_text, number_text = match.groups()
            if sign_text is None and not first:
                raise ValueError(f"missing '+' or '-' in dice expression {source!r}")
            sign = -1 if sign_text == "-" else 1
            if number_text is not None:
                constant += sign * int(number_text)
            else:
                count = int(count_text) if count_text else 1
                sides = int(sides_text)
                if count < 1 or sides < 1:
                    raise ValueError(f"dice need at least one die of at least one side: {source!r}")
                terms.append(DiceTerm(count, sides, sign))
            position = match.end()
            first = False
        if sum(term.count for term in terms) > MAX_DICE:
            raise ValueError(f"at most {MAX_DICE} dice per expression")
        if any(term.sides > MAX_SIDES for term in terms):
            raise ValueError(f"at most {MAX_SIDES} sides per die")
        spec = cls(tuple(terms), constant)
        if spec.maximum - spec.minimum > MAX_SPAN:
            raise ValueError(f"at most {MAX_SPAN} between the lowest and highest total")
        return spec

    @property
    def minimum(self) -> int:
        return self.constant + sum(
            t.count if t.sign > 0 else -t.count * t.sides for t in self.terms
        )

    @property
    def maximum(self) -> int:
        return self.constant + sum(
            t.count * t.sides if t.sign > 0 else -t.count for t in self.terms
        )

    def __str__(self) -> str:
        parts = []
        for term in self.terms:
            text = f"{term.count}d{term.sides}"
            parts.append(
                text if not parts and term.sign > 0 else f"{'+' if term.sign > 0 else '-'}{text}"
            )
        if self.constant or not parts:
            parts.append(str(self.constant) if not parts else f"{self.constant:+d}")
        return "".join(parts)


@dataclass(frozen=True)
class Roll:
    """One rolled result.

    Attributes:
        spec: The expression rolled.
        total: The result.
        faces: Each die's face, per term, when actually rolled; `None` when a
            `ScriptedRoller` supplied the total directly.
    """

    spec: DiceSpec
    total: int
    faces: tuple[tuple[int, ...], ...] | None = None


@runtime_checkable
class Roller(Protocol):
    def roll(self, spec: DiceSpec) -> Roll: ...


class RandomRoller:
    """Rolls with a `random.Random` (a fresh unseeded one by default)."""

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()

    def roll(self, spec: DiceSpec | str) -> Roll:
        spec = DiceSpec.parse(spec)
        faces = tuple(
            tuple(self.rng.randint(1, t.sides) for _ in range(t.count)) for t in spec.terms
        )
        total = spec.constant + sum(t.sign * sum(f) for t, f in zip(spec.terms, faces, strict=True))
        return Roll(spec, total, faces)


class ScriptedRoller:
    """Returns pre-set totals in order. For tests and staff demonstrations.

    Raises:
        ValueError: From `roll()`, when a scripted total is impossible for the
            expression being rolled (so a test can't pass on a roll the real
            dice could never produce).
        LookupError: From `roll()`, when the script has run out.
    """

    def __init__(self, totals: Iterable[int]):
        self._totals = deque(totals)
        self.rolled: list[Roll] = []

    def roll(self, spec: DiceSpec | str) -> Roll:
        spec = DiceSpec.parse(spec)
        if not self._totals:
            raise LookupError("ScriptedRoller has no totals left")
        total = self._totals.popleft()
        if distribution(spec).get(total, 0) == 0:
            raise ValueError(f"{spec} can't roll {total} (range {spec.minimum}..{spec.maximum})")
        roll = Roll(spec, total, None)
        self.rolled.append(roll)
        return roll

    @property
    def remaining(self) -> int:
        return len(self._totals)


def distribution(spec: DiceSpec | str) -> dict[int, Fraction]:
    """Exact `{total: probability}` for every total `spec` can roll."""
    return dict(_distribution(DiceSpec.parse(spec)))


@lru_cache(maxsize=256)
def _distribution(spec: DiceSpec) -> tuple[tuple[int, Fraction], ...]:
    counts: dict[int, int] = {spec.constant: 1}
    outcomes = 1
    for term in spec.terms:
        for _ in range(term.count):
            step: dict[int, int] = {}
            for total, ways in counts.items():
                for face in range(1, term.sides + 1):
                    value = total + term.sign * face
                    step[value] = step.get(value, 0) + ways
            counts = step
            outcomes *= term.sides
    return tuple((total, Fraction(ways, outcomes)) for total, ways in sorted(counts.items()))


__all__ = [
    "DiceSpec",
    "DiceTerm",
    "RandomRoller",
    "Roll",
    "Roller",
    "ScriptedRoller",
    "distribution",
]
