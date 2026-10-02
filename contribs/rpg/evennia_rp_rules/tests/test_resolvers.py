# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""GradedResolver: banding, exact estimates, and configuration errors.

TEST_RULESET's noise is 1d6-1d6 (-5..+5, P(k) = (6 - |k|) / 36) and its bands
are great >= 5, good >= 0, bad >= -5, awful below.
"""

from __future__ import annotations

import json
import unittest
from fractions import Fraction

from evennia_rp_rules.dice import ScriptedRoller, distribution
from evennia_rp_rules.resolvers import Contest, GradedResolver, Resolver, ResolverConfigError
from evennia_rp_rules.ruleset import Ruleset
from evennia_rp_rules.testing import fresh_test_ruleset


def build(**param_overrides) -> Ruleset:
    spec = fresh_test_ruleset()
    spec["resolver"]["params"].update(param_overrides)
    return Ruleset.from_spec(spec)


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.ruleset = build()
        self.resolver = self.ruleset.resolver
        self.rate = self.ruleset.parse_rating

    def resolve(self, actor, target, roll, **kwargs):
        contest = Contest(self.rate(actor), self.rate(target), **kwargs)
        return self.resolver.resolve(contest, ScriptedRoller([roll]))

    def test_even_match_with_a_zero_roll_is_the_lowest_success(self):
        result = self.resolve("Mid", "Mid", 0)
        self.assertEqual((result.outcome.key, result.margin), ("good", 0))
        self.assertTrue(result.is_success)

    def test_band_boundaries_are_inclusive_minimums(self):
        cases = [(5, "great"), (4, "good"), (0, "good"), (-1, "bad"), (-5, "bad")]
        for roll, expected in cases:
            with self.subTest(roll=roll):
                self.assertEqual(self.resolve("Mid", "Mid", roll).outcome.key, expected)

    def test_every_outcome_is_reachable(self):
        reached = {
            self.resolve("Mid", "Mid", 5).outcome.key,
            self.resolve("Mid", "Mid", 2).outcome.key,
            self.resolve("Mid", "Mid", -3).outcome.key,
            self.resolve("Low", "Mid", -5).outcome.key,
        }
        self.assertEqual(reached, set(self.ruleset.ladder.keys()))

    def test_pips_and_bonuses_move_the_margin(self):
        # Mid++ is 15; +1.5 bonus; target Mid with a +2 bonus: 16.5 - 12 + roll.
        result = self.resolve("Mid++", "Mid", -4, actor_bonus=Fraction(3, 2), target_bonus=2)
        self.assertEqual(result.actor_score, Fraction(33, 2))
        self.assertEqual(result.target_score, 12)
        self.assertEqual(result.margin, Fraction(1, 2))
        self.assertEqual(result.outcome.key, "good")

    def test_opposed_contests_use_the_opposed_noise(self):
        ruleset = build(opposed_noise="2d6-2d6")
        contest = Contest(ruleset.parse_rating("Mid"), ruleset.parse_rating("Mid"), opposed=True)
        result = ruleset.resolver.resolve(contest, ScriptedRoller([-10]))
        self.assertEqual(str(result.roll.spec), "2d6-2d6")
        self.assertEqual(result.outcome.key, "awful")
        with self.assertRaises(ValueError):  # -10 is impossible on the unopposed 1d6-1d6
            self.resolver.resolve(Contest(contest.actor, contest.target), ScriptedRoller([-10]))

    def test_as_dict_is_json_safe(self):
        record = self.resolve("Mid+", "High", 3, actor_bonus=Fraction(1, 3)).as_dict()
        self.assertEqual(json.loads(json.dumps(record)), record)
        self.assertEqual(record["actor"], "Mid +")
        self.assertEqual(record["actor_bonus"], "1/3")
        self.assertEqual(record["outcome"], "bad")

    def test_satisfies_the_resolver_protocol(self):
        self.assertIsInstance(self.resolver, Resolver)


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.ruleset = build()
        self.resolver = self.ruleset.resolver
        self.rate = self.ruleset.parse_rating

    def test_even_match_by_hand(self):
        odds = self.resolver.estimate(Contest(self.rate("Mid"), self.rate("Mid")))
        self.assertEqual(
            dict(odds),
            {
                "awful": 0,
                "bad": Fraction(15, 36),
                "good": Fraction(20, 36),
                "great": Fraction(1, 36),
            },
        )
        self.assertEqual(odds.success, Fraction(21, 36))

    def test_estimate_agrees_with_resolving_every_roll(self):
        for actor, target in [
            ("Mid", "Mid"),
            ("Low+++", "Mid-"),
            ("High", "Mid---"),
            ("Mid+-", "High"),
        ]:
            contest = Contest(self.rate(actor), self.rate(target), actor_bonus=Fraction(1, 2))
            with self.subTest(actor=actor, target=target):
                tally: dict[str, Fraction] = {}
                for total, p in distribution(self.resolver.noise).items():
                    key = self.resolver.resolve(contest, ScriptedRoller([total])).outcome.key
                    tally[key] = tally.get(key, Fraction(0)) + p
                odds = self.resolver.estimate(contest)
                self.assertEqual({k: v for k, v in odds.items() if v}, tally)
                self.assertEqual(sum(odds.values()), 1)

    def test_roll_ranges_partition_the_noise(self):
        contest = Contest(self.rate("Mid+"), self.rate("Mid"))
        ranges = self.resolver.roll_ranges(contest)
        self.assertEqual(ranges, {"bad": (-5, -4), "good": (-3, 1), "great": (2, 5)})


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.ladder = build().ladder

    def bands(self, *pairs):
        return [
            {"outcome": key, **({} if minimum is None else {"min": minimum})}
            for key, minimum in pairs
        ]

    def problems(self, **params):
        base = {
            "noise": "1d6-1d6",
            "bands": self.bands(("great", 5), ("good", 0), ("bad", -5), ("awful", None)),
        }
        base.update(params)
        with self.assertRaises(ResolverConfigError) as caught:
            GradedResolver.from_params(self.ladder, base)
        return " | ".join(caught.exception.messages)

    def test_unknown_outcome(self):
        self.assertIn(
            "unknown outcome 'meh'", self.problems(bands=self.bands(("meh", 0), ("awful", None)))
        )

    def test_minimums_must_strictly_decrease(self):
        self.assertIn(
            "strictly decrease",
            self.problems(bands=self.bands(("great", 0), ("good", 0), ("awful", None))),
        )

    def test_last_band_is_the_catch_all(self):
        self.assertIn("takes no 'min'", self.problems(bands=self.bands(("good", 0), ("awful", -3))))
        self.assertIn(
            "only the last band", self.problems(bands=self.bands(("good", None), ("awful", None)))
        )

    def test_outcomes_may_not_improve_as_margin_falls(self):
        self.assertIn(
            "must not improve",
            self.problems(bands=self.bands(("good", 5), ("great", 0), ("awful", None))),
        )

    def test_repeated_outcome(self):
        self.assertIn(
            "more than one band",
            self.problems(bands=self.bands(("good", 5), ("good", 0), ("awful", None))),
        )

    def test_bad_noise_unknown_and_missing_params(self):
        self.assertIn("noise", self.problems(noise="2x6"))
        self.assertIn("unknown parameter 'nose'", self.problems(nose="1d6"))
        with self.assertRaises(ResolverConfigError) as caught:
            GradedResolver.from_params(self.ladder, {})
        self.assertIn("missing parameter 'noise'", caught.exception.messages)
        self.assertIn("missing parameter 'bands'", caught.exception.messages)

    def test_empty_bands(self):
        self.assertIn("bands must be a non-empty list", self.problems(bands=[]))
        with self.assertRaises(ResolverConfigError):
            GradedResolver(self.ladder, noise="1d6", bands=[])


if __name__ == "__main__":
    unittest.main()
