# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The odds CLI: views, exit codes, and staying Django-free."""

from __future__ import annotations

import argparse
import contextlib
import io
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest
from fractions import Fraction

from evennia_rp_rules.odds import main, parse_modifier, parse_pips, render_table

TEST_REF = "evennia_rp_rules.testing.TEST_RULESET"


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exc:  # argparse usage errors
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def table_rows(output: str) -> dict[str, list[str]]:
    """Map each plain-table row's label to its cells (labels may contain spaces)."""
    rows = {}
    for line in output.splitlines():
        parts = [p for p in line.split("  ") if p.strip()]
        if parts:
            rows[parts[0].strip()] = [p.strip() for p in parts[1:]]
    return rows


class ViewTests(unittest.TestCase):
    def test_matrix_success_by_hand(self):
        code, out, _ = run("--ruleset", TEST_REF, "--matrix", "success")
        self.assertEqual(code, 0)
        rows = table_rows(out)
        # Mid vs Mid on 1d6-1d6: P(roll >= 0) = 21/36 = 58.3%.
        self.assertEqual(rows["Mid"], ["100%", "58.3%", "0%"])
        self.assertIn("Ruleset test (", out)

    def test_matrix_outcome_and_at_least(self):
        _, out, _ = run("--ruleset", TEST_REF, "--matrix", "great")
        self.assertEqual(table_rows(out)["Mid"][1], "2.8%")  # 1/36
        _, out, _ = run("--ruleset", TEST_REF, "--matrix", "bad+")
        self.assertEqual(table_rows(out)["Mid"][1], "100%")

    def test_matrix_pip_rows_skip_impossible_counts(self):
        _, out, _ = run("--ruleset", TEST_REF, "--matrix", "success", "--pips", "-3,0,2,9")
        rows = table_rows(out)
        self.assertIn("Mid ---", rows)
        self.assertIn("Mid ++", rows)
        self.assertFalse(any("+++++++++" in label for label in rows))

    def test_modifiers_apply_to_the_right_side(self):
        _, out, _ = run("--ruleset", TEST_REF, "--matrix", "success", "--modifier", "score=+5")
        self.assertEqual(table_rows(out)["Mid"][1], "100%")
        _, out, _ = run(
            "--ruleset", TEST_REF, "--matrix", "success", "--target-modifier", "rung=-1"
        )
        self.assertEqual(table_rows(out)["Mid"][2], "58.3%")  # High shifted down to Mid

    def test_detail_view(self):
        code, out, _ = run("--ruleset", TEST_REF, "--detail", "Mid+", "Mid")
        self.assertEqual(code, 0)
        self.assertIn("score 13 (rung 10, pips +3)", out)
        self.assertIn("Noise   1d6-1d6 (-5..5)", out)
        rows = table_rows(out)
        # Margin is 3 + roll: great needs roll >= 2, i.e. (4+3+2+1)/36.
        self.assertEqual(rows["Great"], ["2..5", "27.8%"])
        # Only rolls of -5 and -4 fail: 1 - 3/36.
        self.assertEqual(rows["(any success)"], ["91.7%"])

    def test_markdown_tables_are_well_formed(self):
        _, out, _ = run("--ruleset", TEST_REF, "--matrix", "success", "--markdown")
        lines = [line for line in out.splitlines() if line.startswith("|")]
        widths = {line.count("|") for line in lines}
        self.assertEqual(len(widths), 1, lines)

    def test_scores_view_lists_every_pip_count(self):
        code, out, _ = run("--ruleset", TEST_REF, "--scores")
        self.assertEqual(code, 0)
        rows = table_rows(out)
        self.assertEqual(rows["Mid"], ["4", "7", "9", "10", "13", "15", "16"])
        self.assertEqual(rows["High"][-1], "23")
        self.assertNotIn("!", out)


class CrossingRulesetTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = pathlib.Path(tmp.name) / "crossing.py"
        self.path.write_text(
            textwrap.dedent(
                """
                from evennia_rp_rules.testing import fresh_test_ruleset
                RULESET = fresh_test_ruleset()
                RULESET["scales"]["tier"]["edge"] = [6, 4]
                """
            ),
            encoding="utf-8",
        )

    def test_scores_still_render_and_mark_crossings(self):
        code, out, _ = run("--ruleset", str(self.path), "--scores")
        self.assertEqual(code, 0)
        self.assertIn("10!", out)  # Low++ reaches Mid
        self.assertIn("E003", out)

    def test_other_views_refuse_an_invalid_ruleset(self):
        code, _, err = run("--ruleset", str(self.path), "--matrix", "success")
        self.assertEqual(code, 1)
        self.assertIn("E003", err)
        self.assertIn("--scores still works", err)


class ErrorTests(unittest.TestCase):
    def test_unknown_outcome_and_rating(self):
        code, _, err = run("--ruleset", TEST_REF, "--matrix", "meh")
        self.assertEqual(code, 2)
        self.assertIn("unknown outcome 'meh'", err)
        code, _, err = run("--ruleset", TEST_REF, "--detail", "Huge", "Mid")
        self.assertEqual(code, 2)
        self.assertIn("Unknown", err)

    def test_unloadable_ruleset(self):
        code, _, err = run("--ruleset", "no.such.rules")
        self.assertEqual(code, 1)
        self.assertIn("E001", err)

    def test_argument_parsers(self):
        self.assertEqual(parse_modifier("score=+4"), ("score", Fraction(4)))
        self.assertEqual(parse_modifier("rung=-1"), ("rung", Fraction(-1)))
        self.assertEqual(parse_modifier("score=2.5"), ("score", Fraction(5, 2)))
        for bad in ("score", "power=1", "score=abc", "rung=0.5"):
            with self.subTest(bad=bad), self.assertRaises(argparse.ArgumentTypeError):
                parse_modifier(bad)
        self.assertEqual(parse_pips("-2, 0,3"), [-2, 0, 3])
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_pips("a,b")

    def test_render_table_aligns_columns(self):
        text = render_table(["A", "Long header"], [["x", "1"], ["yy", "22"]])
        self.assertEqual(len({len(line) for line in text.splitlines()[:2]}), 1)


class IsolationTests(unittest.TestCase):
    def test_odds_tool_never_imports_django_or_evennia(self):
        probe = (
            "import sys, evennia_rp_rules.odds as odds; "
            "odds.main(['--matrix', 'success']); "
            "print('LOADED', 'django' in sys.modules, 'evennia' in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            check=True,
            cwd=pathlib.Path(__file__).resolve().parents[2],
        )
        self.assertIn("LOADED False False", result.stdout)


if __name__ == "__main__":
    unittest.main()
