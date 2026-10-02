# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Exact-number helpers.

Every score, pip increment, factor and band threshold is held as a
`fractions.Fraction`. Rulesets are authored with ordinary numbers (`2.5`,
`0.75`), and binary floats would make the rung-crossing invariant and band
boundaries wobble at exact ties; fractions keep `B +++++ < A` an exact
statement, and keep the odds tool's probabilities summing to exactly 1.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

Number = int | float | Decimal | Fraction | str


def to_fraction(value: Number) -> Fraction:
    """Convert an authored number to an exact `Fraction`.

    Floats go through their shortest `repr`, so `0.1` becomes `1/10` rather
    than the binary approximation a direct `Fraction(0.1)` would give.

    Raises:
        TypeError: For booleans and non-numeric types.
        ValueError: For strings that aren't numbers.
    """
    if isinstance(value, bool):
        raise TypeError("expected a number, got a boolean")
    if isinstance(value, Fraction | int):
        return Fraction(value)
    if isinstance(value, float | Decimal | str):
        return Fraction(str(value).strip())
    raise TypeError(f"expected a number, got {type(value).__name__}")


def fmt(value: Fraction | int, *, places: int = 2, signed: bool = False) -> str:
    """Render an exact number compactly: `4`, `2.5`, `0.33`, `+1.25`."""
    value = Fraction(value)
    if value.denominator == 1:
        text = str(value.numerator)
    else:
        text = f"{float(value):.{places}f}".rstrip("0").rstrip(".")
    if signed and value >= 0:
        text = f"+{text}"
    return text


def percent(probability: Fraction) -> str:
    """Render a probability as a percentage with one decimal place.

    Nonzero values that would round to `0.0%` (or up to `100.0%`) are shown as
    `<0.1%` / `>99.9%`, so a reachable outcome never reads as impossible.
    """
    if probability == 0:
        return "0%"
    if probability == 1:
        return "100%"
    value = float(probability) * 100
    if value < 0.05:
        return "<0.1%"
    if value > 99.95:
        return ">99.9%"
    return f"{value:.1f}%"
