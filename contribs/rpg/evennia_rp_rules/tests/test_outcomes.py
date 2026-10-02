# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The outcome ladder and exact odds."""

from __future__ import annotations

import unittest
from fractions import Fraction

from evennia_rp_rules.issues import Issue
from evennia_rp_rules.outcomes import Odds, Outcome, OutcomeLadder
from evennia_rp_rules.testing import fresh_test_ruleset


def ladder_issues(outcomes) -> list[Issue]:
    issues: list[Issue] = []
    OutcomeLadder.from_spec(outcomes, issues)
    return issues


class LadderTests(unittest.TestCase):
    def setUp(self):
        issues: list[Issue] = []
        self.ladder = OutcomeLadder.from_spec(fresh_test_ruleset()["outcomes"], issues)
        self.assertEqual(issues, [])

    def test_ordered_worst_first_whatever_the_spec_order(self):
        outcomes = list(reversed(fresh_test_ruleset()["outcomes"]))
        ladder = OutcomeLadder.from_spec(outcomes, [])
        self.assertEqual(ladder.keys(), ["awful", "bad", "good", "great"])
        self.assertEqual((ladder.worst.key, ladder.best.key), ("awful", "great"))

    def test_lookup(self):
        self.assertTrue(self.ladder["good"].is_success)
        self.assertIn("bad", self.ladder)
        self.assertIsNone(self.ladder.get("meh"))
        self.assertEqual(len(self.ladder), 4)

    def test_duplicates_are_refused(self):
        outcomes = fresh_test_ruleset()["outcomes"]
        outcomes[1]["key"] = "awful"
        outcomes[3]["degree"] = 1
        messages = " | ".join(i.message for i in ladder_issues(outcomes))
        self.assertIn("duplicate outcome 'awful'", messages)
        self.assertIn("duplicate degree 1", messages)

    def test_ladder_needs_both_a_success_and_a_failure(self):
        outcomes = [o | {"success": True} for o in fresh_test_ruleset()["outcomes"]]
        self.assertTrue(any("at least one success" in i.message for i in ladder_issues(outcomes)))

    def test_failures_may_not_outrank_successes(self):
        outcomes = fresh_test_ruleset()["outcomes"]
        outcomes[3]["success"] = False  # "great" becomes a failure above "good"
        self.assertTrue(any("higher degree" in i.message for i in ladder_issues(outcomes)))
        with self.assertRaises(ValueError):
            OutcomeLadder([Outcome("a", "A", 1, False), Outcome("b", "B", 0, True)])

    def test_field_types_are_checked(self):
        outcomes = fresh_test_ruleset()["outcomes"]
        outcomes[0]["degree"] = "low"
        outcomes[1]["success"] = "yes"
        outcomes[2]["label"] = ""
        self.assertEqual(len(ladder_issues(outcomes)), 3)


class OddsTests(unittest.TestCase):
    def setUp(self):
        self.ladder = OutcomeLadder.from_spec(fresh_test_ruleset()["outcomes"], [])

    def test_missing_outcomes_are_zero_and_order_follows_the_ladder(self):
        odds = Odds(self.ladder, {"great": Fraction(1, 4), "bad": Fraction(3, 4)})
        self.assertEqual(list(odds), ["awful", "bad", "good", "great"])
        self.assertEqual(odds["awful"], 0)

    def test_success_failure_and_at_least(self):
        odds = Odds(
            self.ladder,
            {
                "awful": Fraction(1, 10),
                "bad": Fraction(2, 10),
                "good": Fraction(3, 10),
                "great": Fraction(4, 10),
            },
        )
        self.assertEqual(odds.success, Fraction(7, 10))
        self.assertEqual(odds.failure, Fraction(3, 10))
        self.assertEqual(odds.at_least("bad"), Fraction(9, 10))
        self.assertEqual(odds.at_least("great"), Fraction(4, 10))

    def test_unknown_outcomes_are_refused(self):
        with self.assertRaises(KeyError):
            Odds(self.ladder, {"meh": Fraction(1)})


if __name__ == "__main__":
    unittest.main()
