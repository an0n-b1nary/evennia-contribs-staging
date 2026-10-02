# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Ordinal scales, pips, and ratings.

A `Scale` is an ordered ladder of `Rung`s (say, grades D, C, B, A, S), each with
a hidden numeric score. A `Rating` is a position on a scale: a rung plus some
**edge** pips (`+`, each nudging the score up) and **weakness** pips (`-`, each
nudging it down). Players see `B +++ -`; only the resolver sees numbers.

Pip value is piecewise. Each scale carries two increment curves, one for edge
and one for weakness, and the *n*th pip is worth the *n*th increment. A curve
like `[2, 1.5, 1, 0.5, 0.25]` makes each extra pip worth less; a weakness curve
like `[0.5, 0.75, 1, 1.25, 1.5]` makes each extra weakness hurt more. Each rung
also scales its pips by an `edge_factor` / `weakness_factor`, so the same pips
can matter less on a high rung than on a low one.

Edge and weakness combine by **net** count: three edge and one weakness is
two net edge, valued on the edge curve; one edge and three weakness is two net
weakness, valued on the weakness curve. Both counts stay on the rating so the
sheet can still show the flavour choice.

The scale's invariant is that **pips never cross a rung**: at full edge a rung
must still score strictly below the next rung up, and at full weakness strictly
above the next rung down. `Scale.crossings()` reports violations as E003, an
error, so a mis-tuned table fails at startup rather than in play.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise

from evennia_rp_rules import _spec
from evennia_rp_rules._numbers import fmt, to_fraction
from evennia_rp_rules.issues import Issue

EDGE_GLYPH = "+"
WEAKNESS_GLYPH = "-"
# Always accepted when parsing, whatever glyphs a scale displays with.
_EDGE_CHARS = frozenset("+")
_WEAKNESS_CHARS = frozenset("-\u2212\u2013")  # hyphen-minus, minus sign, en dash


@dataclass(frozen=True)
class Rung:
    """One step of a scale.

    Attributes:
        key: Stable slug stored on character sheets (`"b"`).
        label: What players see (`"B"`).
        score: Hidden numeric value the resolver works with.
        edge_factor: Multiplier on edge pip value at this rung.
        weakness_factor: Multiplier on weakness pip value at this rung.
        aliases: Extra spellings accepted by `Scale.parse`.
    """

    key: str
    label: str
    score: Fraction
    edge_factor: Fraction = Fraction(1)
    weakness_factor: Fraction = Fraction(1)
    aliases: tuple[str, ...] = ()


class Scale:
    """An ordered ladder of rungs with piecewise pip curves.

    Args:
        key: Slug the ruleset refers to the scale by.
        rungs: Lowest first, with strictly increasing scores.
        edge: Edge pip increments; its length is the most edge a rating may carry.
        weakness: Weakness pip increments; likewise bounds weakness.
        name: Display name for the scale itself.
        edge_glyph, weakness_glyph: Characters used by `Rating.display`.
    """

    def __init__(
        self,
        key: str,
        rungs: list[Rung],
        edge=(),
        weakness=(),
        *,
        name: str | None = None,
        edge_glyph: str = EDGE_GLYPH,
        weakness_glyph: str = WEAKNESS_GLYPH,
    ):
        if not rungs:
            raise ValueError("a scale needs at least one rung")
        scores = [rung.score for rung in rungs]
        if any(lower >= upper for lower, upper in pairwise(scores)):
            raise ValueError("rung scores must strictly increase from the first rung to the last")
        self.key = key
        self.name = name or key
        self.rungs: tuple[Rung, ...] = tuple(rungs)
        self.edge_curve: tuple[Fraction, ...] = tuple(to_fraction(v) for v in edge)
        self.weakness_curve: tuple[Fraction, ...] = tuple(to_fraction(v) for v in weakness)
        if any(v <= 0 for v in (*self.edge_curve, *self.weakness_curve)):
            raise ValueError("pip increments must be positive")
        self.edge_glyph = edge_glyph
        self.weakness_glyph = weakness_glyph
        self._index = {rung.key: i for i, rung in enumerate(self.rungs)}
        self._lookup: dict[str, Rung] = {}
        for rung in self.rungs:
            for spelling in (rung.key, rung.label, *rung.aliases):
                self._lookup.setdefault(spelling.casefold(), rung)

    def __repr__(self) -> str:
        return f"<Scale {self.key}: {' '.join(r.label for r in self.rungs)}>"

    # -- spec ---------------------------------------------------------------

    @classmethod
    def from_spec(cls, key: str, spec, issues: list[Issue]) -> Scale | None:
        """Validate a scale spec, appending problems to `issues`.

        Returns the scale, or `None` if the spec was malformed (in which case
        at least one issue was appended). E003 crossings are *not* checked
        here; the ruleset runs `crossings()` on every scale it builds.
        """
        where = f"scales.{key}"
        spec = _spec.require_mapping(spec, issues, where)
        if spec is None:
            return None
        before = len(issues)
        raw_rungs = _spec.require_list(spec.get("rungs"), issues, f"{where}.rungs")
        rungs: list[Rung] = []
        seen: set[str] = set()
        for index, raw in enumerate(raw_rungs or []):
            rung = _rung_from_spec(raw, issues, f"{where}.rungs[{index}]")
            if rung is None:
                continue
            for folded in sorted({s.casefold() for s in (rung.key, rung.label, *rung.aliases)}):
                if folded in seen:
                    _spec.malformed(
                        issues,
                        f"{where}.rungs[{index}]",
                        f"spelling {folded!r} is used by more than one rung",
                    )
                seen.add(folded)
            rungs.append(rung)
        scores = [rung.score for rung in rungs]
        if any(lower >= upper for lower, upper in pairwise(scores)):
            _spec.malformed(
                issues,
                f"{where}.rungs",
                "rung scores must strictly increase",
                "list rungs lowest first",
            )
        curves = {}
        for side in ("edge", "weakness"):
            raw_curve = _spec.require_list(
                spec.get(side, []), issues, f"{where}.{side}", allow_empty=True
            )
            curves[side] = [
                v
                for i, value in enumerate(raw_curve or [])
                if (
                    v := _spec.require_number(
                        value, issues, f"{where}.{side}[{i}]", minimum=0, strict=True
                    )
                )
                is not None
            ]
        glyphs = spec.get("glyphs", {})
        glyphs = _spec.require_mapping(glyphs, issues, f"{where}.glyphs") or {}
        for side in ("edge", "weakness"):
            glyph = glyphs.get(side)
            if glyph is not None and (not isinstance(glyph, str) or len(glyph) != 1):
                _spec.malformed(
                    issues, f"{where}.glyphs.{side}", f"expected one character, got {glyph!r}"
                )
        name = spec.get("name")
        if name is not None:
            name = _spec.require_text(name, issues, f"{where}.name")
        if len(issues) > before:
            return None
        return cls(
            key,
            rungs,
            curves["edge"],
            curves["weakness"],
            name=name,
            edge_glyph=glyphs.get("edge", EDGE_GLYPH),
            weakness_glyph=glyphs.get("weakness", WEAKNESS_GLYPH),
        )

    # -- lookup -------------------------------------------------------------

    @property
    def max_edge(self) -> int:
        return len(self.edge_curve)

    @property
    def max_weakness(self) -> int:
        return len(self.weakness_curve)

    def rung(self, text: str) -> Rung:
        """Find a rung by key, label, or alias (case-insensitive).

        Raises:
            KeyError: With a player-readable message listing the valid labels.
        """
        rung = self._lookup.get(str(text).strip().casefold())
        if rung is None:
            choices = ", ".join(r.label for r in self.rungs)
            raise KeyError(f"Unknown {self.name.lower()} {text!r}. Choose from {choices}.")
        return rung

    def index(self, rung: Rung) -> int:
        """Position of `rung`, 0 for the lowest."""
        return self._index[rung.key]

    def rating(self, rung: Rung | str, edge: int = 0, weakness: int = 0) -> Rating:
        """Build a rating from a rung (or its spelling) and pip counts."""
        if not isinstance(rung, Rung):
            rung = self.rung(rung)
        return Rating(self, rung, edge, weakness)

    def parse(self, text: str) -> Rating:
        """Parse `"B+++"`, `"B +++ -"`, `"b ++ --"` and the like.

        Every `+` (or this scale's edge glyph) counts as edge and every `-`,
        U+2212 MINUS SIGN or U+2013 EN DASH
        (or the weakness glyph) as weakness, in any order.

        Raises:
            ValueError: Unknown rung, or more pips than the scale's curves allow.
        """
        raw = str(text).strip()
        edge_chars = _EDGE_CHARS | {self.edge_glyph}
        weakness_chars = _WEAKNESS_CHARS | {self.weakness_glyph}
        pip_chars = edge_chars | weakness_chars
        cut = len(raw)
        while cut and (raw[cut - 1] in pip_chars or raw[cut - 1].isspace()):
            cut -= 1
        rung_text, pip_text = raw[:cut].strip(), raw[cut:]
        if not rung_text:
            raise ValueError(f"No {self.name.lower()} given in {text!r}.")
        try:
            rung = self.rung(rung_text)
        except KeyError as exc:
            raise ValueError(exc.args[0]) from None
        edge = sum(1 for ch in pip_text if ch in edge_chars)
        weakness = sum(1 for ch in pip_text if ch in weakness_chars)
        return Rating(self, rung, edge, weakness)

    # -- scoring ------------------------------------------------------------

    def pip_value(self, rung: Rung, net_pips: int) -> Fraction:
        """Score adjustment for `net_pips` (negative means net weakness) at `rung`."""
        if net_pips > 0:
            return sum(self.edge_curve[:net_pips], Fraction(0)) * rung.edge_factor
        if net_pips < 0:
            return -sum(self.weakness_curve[:-net_pips], Fraction(0)) * rung.weakness_factor
        return Fraction(0)

    def crossings(self) -> list[Issue]:
        """E003 for every rung whose full edge or full weakness reaches a neighbour."""
        issues = []
        for i, rung in enumerate(self.rungs):
            if i + 1 < len(self.rungs) and self.max_edge:
                upper = self.rungs[i + 1]
                top = rung.score + self.pip_value(rung, self.max_edge)
                if top >= upper.score:
                    issues.append(
                        Issue(
                            "E003",
                            f"scales.{self.key}: {rung.label} with {self.max_edge} edge scores "
                            f"{fmt(top)}, reaching {upper.label} ({fmt(upper.score)})",
                            f"lower the edge curve or {rung.label}'s edge_factor, or widen the "
                            f"{rung.label}->{upper.label} gap; pips must never cross a rung",
                        )
                    )
            if i > 0 and self.max_weakness:
                lower = self.rungs[i - 1]
                bottom = rung.score + self.pip_value(rung, -self.max_weakness)
                if bottom <= lower.score:
                    issues.append(
                        Issue(
                            "E003",
                            f"scales.{self.key}: {rung.label} with {self.max_weakness} weakness scores "
                            f"{fmt(bottom)}, reaching {lower.label} ({fmt(lower.score)})",
                            f"lower the weakness curve or {rung.label}'s weakness_factor, or widen the "
                            f"{lower.label}->{rung.label} gap; pips must never cross a rung",
                        )
                    )
        return issues


def _rung_from_spec(raw, issues: list[Issue], where: str) -> Rung | None:
    raw = _spec.require_mapping(raw, issues, where)
    if raw is None:
        return None
    before = len(issues)
    key = _spec.require_key(raw.get("key"), issues, f"{where}.key")
    label = raw.get("label", key)
    label = _spec.require_text(label, issues, f"{where}.label") if label is not None else None
    if "score" not in raw:
        _spec.malformed(issues, where, "missing 'score'")
        score = None
    else:
        score = _spec.require_number(raw["score"], issues, f"{where}.score")
    factors = {
        name: _spec.require_number(
            raw.get(name, 1), issues, f"{where}.{name}", minimum=0, strict=True
        )
        for name in ("edge_factor", "weakness_factor")
    }
    aliases = _spec.text_aliases(raw.get("aliases"), issues, f"{where}.aliases")
    if len(issues) > before:
        return None
    return Rung(key, label, score, factors["edge_factor"], factors["weakness_factor"], aliases)


@dataclass(frozen=True)
class Rating:
    """A position on a scale: a rung plus edge and weakness pips.

    Raises:
        ValueError: If the rung isn't on the scale, or a pip count is negative
            or exceeds what the scale's curves define.
    """

    scale: Scale
    rung: Rung
    edge: int = 0
    weakness: int = 0

    def __post_init__(self):
        position = self.scale._index.get(self.rung.key)
        if position is None or self.scale.rungs[position] != self.rung:
            raise ValueError(f"rung {self.rung.key!r} is not on scale {self.scale.key!r}")
        for name, count, limit in (
            ("edge", self.edge, self.scale.max_edge),
            ("weakness", self.weakness, self.scale.max_weakness),
        ):
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError(f"{name} must be a non-negative integer, got {count!r}")
            if count > limit:
                raise ValueError(f"{self.scale.name} allows at most {limit} {name}, got {count}")

    @property
    def net_pips(self) -> int:
        """Edge minus weakness; the count the pip curves are applied to."""
        return self.edge - self.weakness

    @property
    def pip_value(self) -> Fraction:
        return self.scale.pip_value(self.rung, self.net_pips)

    def score(self) -> Fraction:
        """Hidden numeric value: rung score plus net pip value."""
        return self.rung.score + self.pip_value

    def display(self, *, compact: bool = False) -> str:
        """Player-facing form, edge first: `"B +++ -"` (or `"B+++-"` compact)."""
        parts = [self.rung.label]
        if self.edge:
            parts.append(self.scale.edge_glyph * self.edge)
        if self.weakness:
            parts.append(self.scale.weakness_glyph * self.weakness)
        return ("" if compact else " ").join(parts)

    def __str__(self) -> str:
        return self.display()

    def shifted(self, steps: int) -> Rating:
        """The same pips on a rung `steps` away, clamped to the scale's ends."""
        index = min(max(self.scale.index(self.rung) + steps, 0), len(self.scale.rungs) - 1)
        return Rating(self.scale, self.scale.rungs[index], self.edge, self.weakness)

    def with_pips(self, edge: int | None = None, weakness: int | None = None) -> Rating:
        return Rating(
            self.scale,
            self.rung,
            self.edge if edge is None else edge,
            self.weakness if weakness is None else weakness,
        )


def scales_from_spec(spec, issues: list[Issue]) -> dict[str, Scale]:
    """Build every scale in a ruleset's `scales` mapping."""
    spec = _spec.require_mapping(spec, issues, "scales")
    if spec is None:
        return {}
    if not spec:
        _spec.malformed(issues, "scales", "define at least one scale")
    scales = {}
    for key, raw in spec.items():
        if _spec.require_key(key, issues, f"scales.{key}") is None:
            continue
        scale = Scale.from_spec(key, raw, issues)
        if scale is not None:
            scales[key] = scale
    return scales


__all__ = ["Rating", "Rung", "Scale", "scales_from_spec"]
