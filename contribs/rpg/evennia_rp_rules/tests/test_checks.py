# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Checks: construction, resolution, errors, records, and the check_resolved signal.

TEST_RULESET: tier Low 0 / Mid 10 / High 20 (High's edge halved), edge [3, 2, 1],
weakness [1, 2, 3], noise 1d6-1d6, bands great >= 5, good >= 0, bad >= -5,
awful below.
"""

from __future__ import annotations

import json
import unittest
from fractions import Fraction

from django.test import SimpleTestCase

from evennia_rp_rules.checks import (
    Check,
    CheckError,
    CheckEstimate,
    CheckResult,
    estimate_check,
    resolve_check,
)
from evennia_rp_rules.dice import ScriptedRoller
from evennia_rp_rules.ruleset import Ruleset
from evennia_rp_rules.signals import check_resolved
from evennia_rp_rules.subjects import DictStatSource
from evennia_rp_rules.testing import (
    TEST_RULESET,
    ProbeSubject,
    RulesetTestMixin,
    fresh_test_ruleset,
)

RULES = Ruleset.from_spec(TEST_RULESET)


def subject(**ratings) -> DictStatSource:
    return DictStatSource(ratings, name="Ana", ruleset=RULES)


def resolve(check, *rolls, ruleset=RULES):
    return resolve_check(check, roller=ScriptedRoller(rolls), ruleset=ruleset, send_signal=False)


class CheckConstructionTests(unittest.TestCase):
    def test_normalises_tags_and_freezes_mappings(self):
        tag = RULES.tags["riddles"]
        check = Check(
            "test", subject(), "brains", tags=[tag, "fire"], difficulty="Mid", context={"room": 1}
        )
        self.assertEqual(check.tags, frozenset({"riddles", "fire"}))
        self.assertEqual(check.opponent_tags, frozenset())
        with self.assertRaises(TypeError):
            check.context["room"] = 2

    def test_a_single_tag_string_is_one_tag(self):
        check = Check("test", subject(), "brains", tags="riddles", difficulty="Mid")
        self.assertEqual(check.tags, frozenset({"riddles"}))

    def test_stat_may_be_a_stat_definition(self):
        check = Check("test", subject(), RULES.stats["brains"], difficulty="Mid")
        self.assertEqual(check.stat, "brains")

    def test_needs_exactly_one_of_difficulty_and_opponent(self):
        with self.assertRaises(ValueError):
            Check("test", subject(), "brains")
        with self.assertRaises(ValueError):
            Check("test", subject(), "brains", difficulty="Mid", opponent=subject())

    def test_rejects_blank_kind_and_stat(self):
        with self.assertRaises(ValueError):
            Check("", subject(), "brains", difficulty="Mid")
        with self.assertRaises(ValueError):
            Check("test", subject(), "", difficulty="Mid")

    def test_frozen(self):
        check = Check("test", subject(), "brains", difficulty="Mid")
        with self.assertRaises(AttributeError):
            check.stat = "brawn"

    def test_sides(self):
        check = Check(
            "test",
            subject(),
            "brains",
            tags={"riddles"},
            opponent=subject(),
            opponent_stat="charm",
            opponent_tags={"fire"},
        )
        self.assertTrue(check.opposed)
        self.assertEqual(check.stat_for("actor"), "brains")
        self.assertEqual(check.stat_for("target"), "charm")
        self.assertEqual(check.tags_for("target"), frozenset({"fire"}))
        same = Check("test", subject(), "brains", opponent=subject())
        self.assertEqual(same.stat_for("target"), "brains")


class ResolveTests(unittest.TestCase):
    def test_every_band_is_reachable(self):
        check = Check("test", subject(brains="Mid"), "brains", difficulty="Mid")
        for roll, outcome in ((5, "great"), (4, "good"), (0, "good"), (-1, "bad"), (-5, "bad")):
            with self.subTest(roll=roll):
                self.assertEqual(resolve(check, roll).outcome.key, outcome)
        low = Check("test", subject(brains="Low"), "brains", difficulty="High")
        self.assertEqual(resolve(low, -5).outcome.key, "awful")

    def test_scores_and_ratings(self):
        result = resolve(Check("test", subject(brains="Mid++"), "brains", difficulty="High-"), 0)
        self.assertIsInstance(result, CheckResult)
        self.assertEqual(result.actor_rating.display(), "Mid ++")
        self.assertEqual(result.target_rating.display(), "High -")
        self.assertEqual(result.score("actor"), 15)
        self.assertEqual(result.score("target"), 19)
        self.assertEqual(result.resolution.margin, -4)
        self.assertEqual(result.outcome.key, "bad")
        self.assertFalse(result.is_success)

    def test_difficulty_may_be_a_rating(self):
        result = resolve(
            Check("test", subject(brains="Mid"), "brains", difficulty=RULES.parse_rating("Low")), 0
        )
        self.assertEqual(result.score("target"), 0)

    def test_opposed_uses_the_opponent_rating_and_opposed_noise(self):
        spec = fresh_test_ruleset()
        spec["resolver"]["params"]["opposed_noise"] = "1d4-1d4"
        rules = Ruleset.from_spec(spec)
        check = Check(
            "test",
            subject(brawn="Mid"),
            "brawn",
            opponent=subject(charm="High"),
            opponent_stat="charm",
        )
        result = resolve(check, 3, ruleset=rules)
        self.assertEqual(str(result.resolution.roll.spec), "1d4-1d4")
        self.assertEqual(result.score("target"), 20)
        self.assertEqual(result.resolution.margin, -7)
        self.assertTrue(result.resolution.contest.opposed)

    def test_as_dict_is_json_safe_and_complete(self):
        check = Check("test", subject(brains="Mid+"), "brains", tags={"riddles"}, difficulty="Mid")
        data = json.loads(json.dumps(resolve(check, 1).as_dict()))
        self.assertEqual(data["outcome"]["key"], "good")
        self.assertEqual(data["outcome"]["degree"], 1)
        self.assertEqual(data["sides"]["actor"]["rating"], "Mid +")
        self.assertEqual(data["sides"]["actor"]["score"], "13")
        self.assertEqual(data["ruleset"]["digest"], RULES.digest)
        self.assertEqual(data["resolution"]["roll"], 1)
        self.assertEqual(data["tags"], ["riddles"])


class CheckErrorTests(unittest.TestCase):
    def assertCheckError(self, check, text):
        with self.assertRaises(CheckError) as caught:
            resolve(check, 0)
        self.assertIn(text, str(caught.exception))

    def test_unknown_stat(self):
        self.assertCheckError(
            Check("test", subject(), "luck", difficulty="Mid"), "Unknown stat 'luck'"
        )

    def test_actor_without_stats(self):
        self.assertCheckError(Check("test", object(), "brains", difficulty="Mid"), "has no stats")

    def test_missing_rating_names_the_stat(self):
        self.assertCheckError(
            Check("test", subject(brawn="Mid"), "brains", difficulty="Mid"),
            "Ana has no Brains rating",
        )

    def test_opponent_missing_rating(self):
        check = Check("test", subject(brains="Mid"), "brains", opponent=subject(brawn="Mid"))
        self.assertCheckError(check, "has no Brains rating")

    def test_bad_difficulty(self):
        self.assertCheckError(
            Check("test", subject(brains="Mid"), "brains", difficulty="Epic"), "Unknown"
        )

    def test_rating_on_another_scale(self):
        spec = fresh_test_ruleset()
        spec["scales"]["other"] = {"rungs": [{"key": "x", "label": "X", "score": 0}]}
        spec["default_scale"] = "tier"
        other = Ruleset.from_spec(spec).scale("other").rating("x")
        self.assertCheckError(
            Check("test", subject(brains=other), "brains", difficulty="Mid"), "rated on"
        )

    def test_a_rating_from_an_older_ruleset_is_rehomed(self):
        stale = Ruleset.from_spec(fresh_test_ruleset()).parse_rating("Mid+")
        self.assertIsNot(stale.scale, RULES.scale())
        result = resolve(Check("test", subject(brains=stale), "brains", difficulty="Mid"), 0)
        self.assertIs(result.actor_rating.scale, RULES.scale())
        self.assertEqual(result.score("actor"), 13)


class EstimateTests(unittest.TestCase):
    def test_estimate_is_exact_and_rolls_nothing(self):
        check = Check("test", subject(brains="Mid"), "brains", difficulty="Mid")
        estimate = estimate_check(check, ruleset=RULES)
        self.assertIsInstance(estimate, CheckEstimate)
        self.assertEqual(sum(estimate.odds.values()), 1)
        # 1d6-1d6 >= 0 is 21/36; >= 5 is 1/36.
        self.assertEqual(estimate.odds.success, Fraction(21, 36))
        self.assertEqual(estimate.odds["great"], Fraction(1, 36))
        self.assertEqual(estimate.viewer, "public")
        json.dumps(estimate.as_dict())

    def test_rejects_unknown_viewer(self):
        check = Check("test", subject(brains="Mid"), "brains", difficulty="Mid")
        with self.assertRaises(ValueError):
            estimate_check(check, viewer="everyone", ruleset=RULES)


class SignalTests(RulesetTestMixin, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.received = []

        def receiver(sender, **kwargs):
            self.received.append((sender, kwargs))

        check_resolved.connect(receiver, weak=False, dispatch_uid="test_checks.receiver")
        self.addCleanup(check_resolved.disconnect, dispatch_uid="test_checks.receiver")

    def check(self):
        return Check("test", ProbeSubject({"brains": "Mid"}), "brains", difficulty="Mid")

    def test_resolve_fires_check_resolved(self):
        check = self.check()
        result = resolve_check(check, roller=self.scripted(1))
        self.assertEqual(len(self.received), 1)
        sender, kwargs = self.received[0]
        self.assertIs(sender, Check)
        self.assertIs(kwargs["check"], check)
        self.assertIs(kwargs["result"], result)

    def test_dry_runs_and_estimates_are_silent(self):
        resolve_check(self.check(), roller=self.scripted(1), send_signal=False)
        estimate_check(self.check())
        self.assertEqual(self.received, [])

    def test_mapping_subjects_work_directly(self):
        result = resolve_check(
            Check("test", {"brains": "Mid"}, "brains", difficulty="Mid"), roller=self.scripted(0)
        )
        self.assertEqual(result.outcome.key, "good")

    def test_uses_the_configured_ruleset_by_default(self):
        result = resolve_check(self.check(), roller=self.scripted(0))
        self.assertEqual(result.ruleset_digest, self.ruleset.digest)


if __name__ == "__main__":
    unittest.main()
