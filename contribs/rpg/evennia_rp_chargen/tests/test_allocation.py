# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Allocation validators and the pip policy, as pure functions of ratings."""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from evennia_rp_chargen.allocation import (
    ArrayAllocation,
    FreeAllocation,
    PointBuyAllocation,
    get_allocation,
)
from evennia_rp_chargen.pips import PipPolicy
from evennia_rp_rules.ruleset import Ruleset
from evennia_rp_rules.testing import TEST_RULESET

RULES = Ruleset.from_spec(TEST_RULESET)


def ratings(**values):
    return {key: RULES.parse_rating(values[key]) if key in values else None for key in RULES.stats}


class FreeAllocationTests(SimpleTestCase):
    def test_only_unset_stats_block_finalising(self):
        report = FreeAllocation().check(ratings(brawn="High", brains="High"), RULES)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.todo, ["Set Charm."])
        self.assertFalse(report.can_finalize)
        full = FreeAllocation().check(ratings(brawn="High", brains="High", charm="High"), RULES)
        self.assertTrue(full.can_finalize)


class PointBuyTests(SimpleTestCase):
    def setUp(self):
        self.buy = PointBuyAllocation({"low": 0, "mid": 1, "high": 3}, 4)

    def test_spending_within_budget(self):
        report = self.buy.check(ratings(brawn="High", brains="Mid", charm="Low"), RULES)
        self.assertEqual((report.spent, report.budget), (4, 4))
        self.assertTrue(report.can_finalize)
        self.assertEqual(report.summary, "4 of 4 build points spent")

    def test_overspending_is_an_error(self):
        report = self.buy.check(ratings(brawn="High", brains="High"), RULES)
        self.assertEqual(report.errors, ["That costs 6 build points, and you have 4."])

    def test_pips_cost_nothing(self):
        report = self.buy.check(ratings(brawn="Mid+++--", brains="Mid", charm="Mid"), RULES)
        self.assertEqual(report.spent, 3)

    def test_underspending_is_fine_unless_required(self):
        loose = self.buy.check(ratings(brawn="Low", brains="Low", charm="Low"), RULES)
        self.assertTrue(loose.can_finalize)
        strict = PointBuyAllocation({"low": 0, "mid": 1, "high": 3}, 4, require_full=True)
        report = strict.check(ratings(brawn="Low", brains="Low", charm="Low"), RULES)
        self.assertEqual(report.todo, ["Spend your remaining 4 build points."])

    @override_settings(RP_CHARGEN_ALLOCATION_NOUN="creation points")
    def test_noun_is_configurable(self):
        report = self.buy.check(ratings(brawn="Mid"), RULES)
        self.assertIn("creation points", report.summary)

    def test_config_problems(self):
        self.assertEqual(self.buy.config_problems(RULES), [])
        bad = PointBuyAllocation({"low": 0, "mid": -1}, 4)
        problems = bad.config_problems(RULES)
        self.assertTrue(any("no cost for rung(s) high" in p for p in problems))
        self.assertTrue(any("at least 0" in p for p in problems))


class ArrayTests(SimpleTestCase):
    def setUp(self):
        self.array = ArrayAllocation(["high", "mid", "low"])

    def test_each_rung_once(self):
        report = self.array.check(ratings(brawn="High", brains="Mid", charm="Low"), RULES)
        self.assertTrue(report.can_finalize)
        self.assertEqual(report.summary, "Unassigned: none")

    def test_reusing_a_rung_is_an_error(self):
        report = self.array.check(ratings(brawn="High", brains="High"), RULES)
        self.assertEqual(report.errors, ["Only 1 stat(s) may be High, not 2."])

    def test_partial_assignment_is_todo(self):
        report = self.array.check(ratings(brawn="Mid"), RULES)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.summary, "Unassigned: High Low")
        self.assertEqual(report.todo, ["Set Brains, Charm."])

    def test_config_problems(self):
        self.assertEqual(self.array.config_problems(RULES), [])
        problems = ArrayAllocation(["high", "epic"]).config_problems(RULES)
        self.assertEqual(len(problems), 2)


class GetAllocationTests(SimpleTestCase):
    def test_default_is_free(self):
        self.assertIsInstance(get_allocation(), FreeAllocation)

    @override_settings(
        RP_CHARGEN_ALLOCATION={
            "path": "evennia_rp_chargen.allocation.ArrayAllocation",
            "params": {"array": ["high", "mid", "low"]},
        }
    )
    def test_settings_choose_and_configure(self):
        allocation = get_allocation()
        self.assertIsInstance(allocation, ArrayAllocation)
        self.assertEqual(allocation.array, ["high", "mid", "low"])

    @override_settings(RP_CHARGEN_ALLOCATION={"path": "no.such.Allocation"})
    def test_bad_path(self):
        with self.assertRaises(ImproperlyConfigured):
            get_allocation()

    @override_settings(
        RP_CHARGEN_ALLOCATION={
            "path": "evennia_rp_chargen.allocation.PointBuyAllocation",
            "params": {"budget": 4},
        }
    )
    def test_bad_params(self):
        with self.assertRaises(ImproperlyConfigured):
            get_allocation()


class PipPolicyTests(SimpleTestCase):
    def test_caps_default_to_the_scale(self):
        policy = PipPolicy()
        scale = RULES.scale()
        self.assertEqual((policy.edge_limit(scale), policy.weakness_limit(scale)), (3, 3))
        capped = PipPolicy(edge_cap=2, weakness_cap=9)
        self.assertEqual((capped.edge_limit(scale), capped.weakness_limit(scale)), (2, 3))

    def test_budget_and_caps(self):
        policy = PipPolicy(edge_budget=4, edge_cap=2, weakness_cap=1)
        self.assertEqual(policy.errors(ratings(brawn="Mid++", brains="Mid++"), RULES), [])
        self.assertEqual(policy.edge_left(ratings(brawn="Mid++", brains="Mid+")), 1)
        errors = policy.errors(ratings(brawn="Mid+++", brains="Mid++", charm="Mid--"), RULES)
        self.assertEqual(
            errors,
            [
                "Brawn may carry at most 2 edge, not 3.",
                "Charm may carry at most 1 weakness, not 2.",
                "That's 5 edge in all, and you have 4.",
            ],
        )

    def test_weakness_never_buys_edge(self):
        policy = PipPolicy(edge_budget=2)
        heavy = ratings(brawn="Mid+++", brains="Mid---")
        self.assertIn("That's 3 edge in all, and you have 2.", policy.errors(heavy, RULES))

    def test_no_budget(self):
        self.assertIsNone(PipPolicy().edge_left(ratings(brawn="Mid+++")))
