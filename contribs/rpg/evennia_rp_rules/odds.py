# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Exact odds tables for tuning a ruleset. Runs without Django or a game.

    python -m evennia_rp_rules.odds --ruleset world.ruleset --scores
    python -m evennia_rp_rules.odds --ruleset world.ruleset --matrix success --pips -2,0,3,5
    python -m evennia_rp_rules.odds --ruleset world.ruleset --matrix critical_success
    python -m evennia_rp_rules.odds --ruleset world.ruleset --detail "B+++" A --modifier score=+4
    python -m evennia_rp_rules.odds --ruleset path/to/ruleset.py --matrix success --markdown

`--ruleset` takes a module (its `RULESET`), a `module.ATTR` path, or a `.py`
file; run from the game directory so `world.ruleset` is importable. It
defaults to the bundled neutral example.

Views:
    --scores    every rung's hidden score at each net pip count. Works even when
                the ruleset fails E003, marking the cells that cross with `!`,
                because that's exactly when you need to see the numbers.
    --matrix W  chance of W for each actor rating (rows) against each target
                rung (columns). W is `success`, `failure`, an outcome key, or
                `KEY+` for that outcome or better.
    --detail A T  full outcome distribution for one matchup, with the noise
                rolls that produce each outcome.

Every probability is exact enumeration over the noise distribution, not
simulation. Modifiers: `score=+N` adds to the side's score; `rung=+N` shifts
its rung (clamped at the ends).
"""

from __future__ import annotations

import argparse
import sys
from fractions import Fraction

from evennia_rp_rules._numbers import fmt, percent, to_fraction
from evennia_rp_rules.issues import RulesetError
from evennia_rp_rules.resolvers import Contest
from evennia_rp_rules.ruleset import DEFAULT_RULESET, Ruleset, load_ruleset_spec
from evennia_rp_rules.scales import Rating, Scale, scales_from_spec

CROSSING_MARK = "!"


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------


def render_table(headers: list[str], rows: list[list[str]], *, markdown: bool = False) -> str:
    """Plain aligned columns, or a GitHub-flavoured markdown table."""
    if markdown:
        lines = [
            "| " + " | ".join(headers) + " |",
            "|" + "|".join([":---", *["---:"] * (len(headers) - 1)]) + "|",
        ]
        lines += ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join(lines)
    widths = [max(len(str(cell)) for cell in column) for column in zip(headers, *rows, strict=True)]

    def line(cells):
        first, *rest = cells
        return "  ".join(
            [first.ljust(widths[0]), *(c.rjust(w) for c, w in zip(rest, widths[1:], strict=True))]
        ).rstrip()

    return "\n".join(
        [line(headers), "  ".join("-" * w for w in widths), *(line(row) for row in rows)]
    )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def scores_table(scale: Scale, *, markdown: bool = False) -> str:
    """Hidden score of each rung at each net pip count, crossings marked."""
    pips = list(range(-scale.max_weakness, scale.max_edge + 1))
    headers = [scale.name, *(f"{n:+d}" if n else "0" for n in pips)]
    rows = []
    for i, rung in enumerate(scale.rungs):
        upper = scale.rungs[i + 1].score if i + 1 < len(scale.rungs) else None
        lower = scale.rungs[i - 1].score if i > 0 else None
        cells = [rung.label]
        for n in pips:
            value = rung.score + scale.pip_value(rung, n)
            crosses = (upper is not None and value >= upper) or (
                lower is not None and value <= lower
            )
            cells.append(fmt(value) + (CROSSING_MARK if crosses else ""))
        rows.append(cells)
    return render_table(headers, rows, markdown=markdown)


def matrix_table(
    ruleset: Ruleset,
    what: str,
    *,
    scale: Scale,
    pips: list[int],
    actor_mods: list[tuple[str, Fraction]] = (),
    target_mods: list[tuple[str, Fraction]] = (),
    opposed: bool = False,
    markdown: bool = False,
) -> str:
    """Chance of `what` for each actor rating against each bare target rung."""
    pick = _selector(ruleset, what)
    targets = [scale.rating(rung) for rung in scale.rungs]
    headers = [f"{what} vs", *(t.display() for t in targets)]
    rows = []
    for rung in scale.rungs:
        for net in pips:
            actor = _pipped(scale.rating(rung), net)
            if actor is None:
                continue
            cells = [actor.display()]
            for target in targets:
                contest = _contest(actor, target, actor_mods, target_mods, opposed)
                cells.append(percent(pick(ruleset.resolver.estimate(contest))))
            rows.append(cells)
    return render_table(headers, rows, markdown=markdown)


def detail_table(
    ruleset: Ruleset,
    actor: Rating,
    target: Rating,
    *,
    actor_mods: list[tuple[str, Fraction]] = (),
    target_mods: list[tuple[str, Fraction]] = (),
    opposed: bool = False,
    markdown: bool = False,
) -> str:
    """One matchup: both scores, the noise, and each outcome's rolls and chance."""
    contest = _contest(actor, target, actor_mods, target_mods, opposed)
    resolver = ruleset.resolver
    odds = resolver.estimate(contest)
    lines = []
    scores = getattr(resolver, "scores", None)
    if scores is not None:
        actor_score, target_score = scores(contest)
        lines.append(_side_line("Actor", contest.actor, contest.actor_bonus, actor_score))
        lines.append(_side_line("Target", contest.target, contest.target_bonus, target_score))
    noise = getattr(resolver, "noise_for", None)
    if noise is not None:
        spec = noise(contest)
        lines.append(
            f"Noise   {spec} ({spec.minimum}..{spec.maximum}){'  [opposed]' if opposed else ''}"
        )
    ranges = resolver.roll_ranges(contest) if hasattr(resolver, "roll_ranges") else {}
    rows = []
    for outcome in reversed(list(ruleset.ladder)):
        low_high = ranges.get(outcome.key)
        rolls = (
            "-"
            if low_high is None
            else (
                str(low_high[0]) if low_high[0] == low_high[1] else f"{low_high[0]}..{low_high[1]}"
            )
        )
        rows.append([outcome.label, rolls, percent(odds[outcome.key])])
    rows.append(["(any success)", "", percent(odds.success)])
    lines += ["", render_table(["Outcome", "Rolls", "Chance"], rows, markdown=markdown)]
    return "\n".join(lines)


def _side_line(name: str, rating: Rating, bonus: Fraction, total: Fraction) -> str:
    parts = f"rung {fmt(rating.rung.score)}, pips {fmt(rating.pip_value, signed=True)}"
    if bonus:
        parts += f", bonus {fmt(bonus, signed=True)}"
    return f"{name:<7} {rating.display():<10} score {fmt(total)} ({parts})"


def _selector(ruleset: Ruleset, what: str):
    if what == "success":
        return lambda odds: odds.success
    if what == "failure":
        return lambda odds: odds.failure
    at_least = what.endswith("+")
    key = what[:-1] if at_least else what
    if key not in ruleset.ladder:
        choices = ", ".join(["success", "failure", *ruleset.ladder.keys()])
        raise ValueError(
            f"unknown outcome {key!r}; choose from {choices} (append + for 'or better')"
        )
    return (lambda odds: odds.at_least(key)) if at_least else (lambda odds: odds[key])


def _pipped(rating: Rating, net: int) -> Rating | None:
    scale = rating.scale
    if net > scale.max_edge or -net > scale.max_weakness:
        return None
    return rating.with_pips(edge=max(net, 0), weakness=max(-net, 0))


def _contest(actor, target, actor_mods, target_mods, opposed) -> Contest:
    actor, actor_bonus = _apply_mods(actor, actor_mods)
    target, target_bonus = _apply_mods(target, target_mods)
    return Contest(actor, target, actor_bonus, target_bonus, opposed=opposed)


def _apply_mods(rating: Rating, mods) -> tuple[Rating, Fraction]:
    bonus = Fraction(0)
    for kind, value in mods:
        if kind == "score":
            bonus += value
        else:  # rung
            rating = rating.shifted(int(value))
    return rating, bonus


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_modifier(text: str) -> tuple[str, Fraction]:
    """Parse `score=+4` or `rung=-1`."""
    kind, sep, value = text.partition("=")
    kind = kind.strip().lower()
    if not sep or kind not in {"score", "rung"}:
        raise argparse.ArgumentTypeError(f"expected score=N or rung=N, got {text!r}")
    try:
        number = to_fraction(value.strip())
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from exc
    if kind == "rung" and number.denominator != 1:
        raise argparse.ArgumentTypeError("rung shifts are whole steps")
    return kind, number


def parse_pips(text: str) -> list[int]:
    try:
        return [int(part) for part in text.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected comma-separated integers, got {text!r}"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evennia_rp_rules.odds",
        description="Exact odds tables for an evennia_rp_rules ruleset.",
    )
    parser.add_argument(
        "--ruleset", default=DEFAULT_RULESET, help="module, module.ATTR, or .py file"
    )
    parser.add_argument("--scale", help="scale key (default: the ruleset's default scale)")
    view = parser.add_mutually_exclusive_group()
    view.add_argument("--scores", action="store_true", help="hidden score per rung and net pips")
    view.add_argument("--matrix", metavar="WHAT", help="success, failure, an outcome key, or KEY+")
    view.add_argument(
        "--detail", nargs=2, metavar=("ACTOR", "TARGET"), help='one matchup, e.g. "B+++" A'
    )
    parser.add_argument(
        "--pips", type=parse_pips, default=[0], help="net pips for matrix rows, e.g. -2,0,3,5"
    )
    parser.add_argument(
        "--modifier",
        type=parse_modifier,
        action="append",
        default=[],
        help="actor: score=N or rung=N",
    )
    parser.add_argument(
        "--target-modifier", type=parse_modifier, action="append", default=[], help="target side"
    )
    parser.add_argument("--opposed", action="store_true", help="use the resolver's opposed noise")
    parser.add_argument("--markdown", action="store_true", help="emit markdown tables")
    return parser


def _attach_negative_values(argv: list[str]) -> list[str]:
    """Rewrite `--pips -2,0,3` as `--pips=-2,0,3`.

    Before Python 3.14, argparse reads a value starting with `-` as another
    option unless it is a plain negative number, so `--pips -2,0,3` would be
    a usage error on the versions this package supports.
    """
    out: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--pips" and i + 1 < len(argv) and argv[i + 1].startswith("-"):
            out.append(f"--pips={argv[i + 1]}")
            i += 2
            continue
        out.append(argv[i])
        i += 1
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    args = build_parser().parse_args(_attach_negative_values(argv))
    try:
        spec = load_ruleset_spec(args.ruleset)
    except RulesetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.scores:
        # Scales only, so E003 crossings are shown rather than refused.
        issues = []
        scales = scales_from_spec(spec.get("scales", {}), issues)
        if not scales:
            for issue in issues:
                print(f"error: {issue}", file=sys.stderr)
            return 1
        keys = [args.scale] if args.scale else list(scales)
        if args.scale and args.scale not in scales:
            print(f"error: unknown scale {args.scale!r}", file=sys.stderr)
            return 1
        blocks = []
        for key in keys:
            scale = scales[key]
            crossings = scale.crossings()
            block = [f"{scale.name} ({key})", "", scores_table(scale, markdown=args.markdown)]
            if crossings:
                block += ["", f"{CROSSING_MARK} = crosses a neighbouring rung (E003):"]
                block += [f"  {issue.message}" for issue in crossings]
            blocks.append("\n".join(block))
        print("\n\n".join(blocks))
        return 0

    try:
        ruleset = Ruleset.from_spec(spec)
    except RulesetError as exc:
        for issue in exc.issues:
            print(f"error: {issue}", file=sys.stderr)
        print("(--scores still works on a ruleset that only fails E003)", file=sys.stderr)
        return 1
    try:
        scale = ruleset.scale(args.scale)
    except KeyError:
        print(f"error: unknown scale {args.scale!r}", file=sys.stderr)
        return 1

    try:
        if args.detail:
            actor, target = (scale.parse(text) for text in args.detail)
            output = detail_table(
                ruleset,
                actor,
                target,
                actor_mods=args.modifier,
                target_mods=args.target_modifier,
                opposed=args.opposed,
                markdown=args.markdown,
            )
        else:
            output = matrix_table(
                ruleset,
                args.matrix or "success",
                scale=scale,
                pips=args.pips,
                actor_mods=args.modifier,
                target_mods=args.target_modifier,
                opposed=args.opposed,
                markdown=args.markdown,
            )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Ruleset {ruleset.version} ({ruleset.digest})\n")
    for issue in Ruleset.validate(spec):
        print(f"warning: {issue}\n")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
