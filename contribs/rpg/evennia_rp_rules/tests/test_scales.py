# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Scales, ratings, piecewise pips, and the rung-crossing invariant."""

from __future__ import annotations

import unittest
from fractions import Fraction

from evennia_rp_rules.issues import Issue
from evennia_rp_rules.scales import Rating, Rung, Scale
from evennia_rp_rules.testing import fresh_test_ruleset


def build_scale(**overrides) -> Scale:
    spec = fresh_test_ruleset()["scales"]["tier"]
    spec.update(overrides)
    issues: list[Issue] = []
    scale = Scale.from_spec("tier", spec, issues)
    assert scale is not None, issues
    return scale


def spec_issues(**overrides) -> list[Issue]:
    spec = fresh_test_ruleset()["scales"]["tier"]
    spec.update(overrides)
    issues: list[Issue] = []
    Scale.from_spec("tier", spec, issues)
    return issues


class ParseAndDisplayTests(unittest.TestCase):
    def setUp(self):
        self.scale = build_scale()

    def test_parse_accepts_spacing_case_and_minus_variants(self):
        cases = {
            "Mid": ("mid", 0, 0),
            "mid+++": ("mid", 3, 0),
            "MID ++ -": ("mid", 2, 1),
            "Mid + \u2212\u2212": ("mid", 1, 2),
            "high\u2013": ("high", 0, 1),
            "  low  ": ("low", 0, 0),
        }
        for text, (rung, edge, weakness) in cases.items():
            with self.subTest(text=text):
                rating = self.scale.parse(text)
                self.assertEqual(
                    (rating.rung.key, rating.edge, rating.weakness), (rung, edge, weakness)
                )

    def test_unknown_rung_lists_the_choices(self):
        with self.assertRaises(ValueError) as caught:
            self.scale.parse("Huge++")
        self.assertIn("Low, Mid, High", str(caught.exception))

    def test_pips_beyond_the_curve_are_refused(self):
        with self.assertRaises(ValueError):
            self.scale.parse("Mid++++")
        with self.assertRaises(ValueError):
            self.scale.parse("Mid----")

    def test_pips_without_a_rung_are_refused(self):
        with self.assertRaises(ValueError):
            self.scale.parse("+++")

    def test_display_puts_edge_before_weakness(self):
        rating = self.scale.rating("mid", edge=3, weakness=1)
        self.assertEqual(rating.display(), "Mid +++ -")
        self.assertEqual(rating.display(compact=True), "Mid+++-")
        self.assertEqual(str(self.scale.rating("low")), "Low")
        self.assertEqual(self.scale.rating("low", weakness=2).display(), "Low --")

    def test_display_round_trips_through_parse(self):
        for edge in range(4):
            for weakness in range(4):
                rating = self.scale.rating("mid", edge=edge, weakness=weakness)
                self.assertEqual(self.scale.parse(rating.display()), rating)

    def test_custom_glyphs_display_and_parse(self):
        scale = build_scale(glyphs={"edge": "*", "weakness": "~"})
        rating = scale.rating("mid", edge=2, weakness=1)
        self.assertEqual(rating.display(), "Mid ** ~")
        self.assertEqual(scale.parse("Mid ** ~"), rating)
        self.assertEqual(scale.parse("Mid ++ -"), rating)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.scale = build_scale()

    def test_edge_uses_the_piecewise_curve(self):
        scores = [self.scale.rating("mid", edge=n).score() for n in range(4)]
        self.assertEqual(scores, [10, 13, 15, 16])

    def test_weakness_uses_its_own_curve(self):
        scores = [self.scale.rating("mid", weakness=n).score() for n in range(4)]
        self.assertEqual(scores, [10, 9, 7, 4])

    def test_edge_and_weakness_combine_by_net_count(self):
        # +3 -1 is net +2 on the edge curve: 3 + 2.
        self.assertEqual(self.scale.rating("mid", edge=3, weakness=1).score(), 15)
        # +1 -3 is net -2 on the weakness curve: 1 + 2.
        self.assertEqual(self.scale.rating("mid", edge=1, weakness=3).score(), 7)
        # Balanced pips cancel exactly.
        self.assertEqual(self.scale.rating("mid", edge=2, weakness=2).score(), 10)
        self.assertEqual(self.scale.rating("mid", edge=3, weakness=1).net_pips, 2)

    def test_rung_factor_scales_pips(self):
        # High has edge_factor 0.5: 20 + (3 + 2 + 1) / 2.
        self.assertEqual(self.scale.rating("high", edge=3).score(), 23)
        self.assertEqual(self.scale.rating("high", weakness=3).score(), 14)

    def test_fractional_increments_stay_exact(self):
        scale = build_scale(edge=[0.1, 0.2])
        self.assertEqual(scale.rating("mid", edge=2).pip_value, Fraction(3, 10))

    def test_shifted_clamps_and_keeps_pips(self):
        rating = self.scale.rating("mid", edge=2, weakness=1)
        self.assertEqual(rating.shifted(1).rung.key, "high")
        self.assertEqual(rating.shifted(5).rung.key, "high")
        self.assertEqual(rating.shifted(-5).rung.key, "low")
        self.assertEqual((rating.shifted(1).edge, rating.shifted(1).weakness), (2, 1))


class InvariantTests(unittest.TestCase):
    def test_well_tuned_scale_has_no_crossings(self):
        self.assertEqual(build_scale().crossings(), [])

    def test_edge_reaching_the_next_rung_is_e003(self):
        # 5 + 4 + 1 = 10 is exactly the low->mid and mid->high gap: reaching counts.
        issues = build_scale(edge=[5, 4, 1]).crossings()
        self.assertEqual([i.id for i in issues], ["E003", "E003"])
        self.assertIn("Low with 3 edge", issues[0].message)
        self.assertIn("Mid with 3 edge", issues[1].message)
        self.assertTrue(all(i.level == "error" for i in issues))

    def test_weakness_reaching_the_previous_rung_is_e003(self):
        issues = build_scale(weakness=[5, 5]).crossings()
        messages = " | ".join(i.message for i in issues)
        self.assertIn("Mid with 2 weakness", messages)
        self.assertIn("High with 2 weakness", messages)
        self.assertNotIn("Low with", messages)

    def test_rung_factor_can_rescue_a_curve(self):
        # 12 would cross mid->high, but only from mid; with mid's factor at 0.5 it scores 16.
        spec = fresh_test_ruleset()["scales"]["tier"]
        spec["edge"] = [6, 6]
        spec["rungs"][0]["edge_factor"] = 0.5
        spec["rungs"][1]["edge_factor"] = 0.5
        issues: list[Issue] = []
        scale = Scale.from_spec("tier", spec, issues)
        self.assertEqual(scale.crossings(), [])

    def test_crossing_hint_names_the_gap(self):
        issue = build_scale(edge=[10]).crossings()[0]
        self.assertIn("Low->Mid", issue.hint)


class ConstructionTests(unittest.TestCase):
    def test_scores_must_strictly_increase(self):
        with self.assertRaises(ValueError):
            Scale("x", [Rung("a", "A", Fraction(1)), Rung("b", "B", Fraction(1))])
        rungs = fresh_test_ruleset()["scales"]["tier"]["rungs"]
        rungs[2]["score"] = 5
        self.assertTrue(any("strictly increase" in i.message for i in spec_issues(rungs=rungs)))

    def test_pip_increments_must_be_positive(self):
        self.assertTrue(spec_issues(edge=[1, 0]))
        self.assertTrue(spec_issues(weakness=[-1]))

    def test_malformed_rungs_are_reported(self):
        rungs = [{"key": "Bad Key", "score": 0}, {"key": "ok"}]
        messages = " | ".join(i.message for i in spec_issues(rungs=rungs))
        self.assertIn("invalid key 'Bad Key'", messages)
        self.assertIn("missing 'score'", messages)

    def test_duplicate_spellings_are_reported(self):
        rungs = [
            {"key": "low", "label": "Low", "score": 0},
            {"key": "mid", "label": "Mid", "score": 10, "aliases": ["LOW"]},
        ]
        self.assertTrue(any("more than one rung" in i.message for i in spec_issues(rungs=rungs)))

    def test_key_and_label_differing_only_by_case_is_fine(self):
        self.assertEqual(spec_issues(), [])

    def test_glyphs_must_be_single_characters(self):
        self.assertTrue(spec_issues(glyphs={"edge": "++"}))

    def test_rating_rejects_a_rung_from_another_scale(self):
        other = Rung("mid", "Mid", Fraction(99))
        with self.assertRaises(ValueError):
            Rating(build_scale(), other)

    def test_rating_rejects_negative_or_boolean_pips(self):
        scale = build_scale()
        with self.assertRaises(ValueError):
            scale.rating("mid", edge=-1)
        with self.assertRaises(ValueError):
            scale.rating("mid", edge=True)


if __name__ == "__main__":
    unittest.main()
