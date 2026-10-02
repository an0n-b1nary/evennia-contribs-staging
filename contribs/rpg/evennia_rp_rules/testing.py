# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Test helpers for this contrib and the packages built on it.

`TEST_RULESET` is deliberately tiny and round-numbered so expected outcomes can
be worked out by hand:

    scale "tier": low 0, mid 10, high 20
        edge      [3, 2, 1]   (max 6; halved on high by edge_factor 0.5)
        weakness  [1, 2, 3]   (max 6)
    noise "1d6-1d6"  (-5..+5)
    bands: great >= 5, good >= 0, bad >= -5, awful below

so `mid` vs `mid` with a scripted roll of 0 is exactly `good`, and so on.

`RulesetTestMixin` points `RP_RULES_RULESET` at a spec for the duration of each
test and exposes the built ruleset as `self.ruleset`; it needs Django
(`SimpleTestCase` or anything above it).
"""

from __future__ import annotations

from copy import deepcopy

from evennia_rp_rules.dice import ScriptedRoller
from evennia_rp_rules.ruleset import get_ruleset, reset_ruleset_cache

TEST_RULESET = {
    "version": "test",
    "scales": {
        "tier": {
            "rungs": [
                {"key": "low", "label": "Low", "score": 0},
                {"key": "mid", "label": "Mid", "score": 10},
                {"key": "high", "label": "High", "score": 20, "edge_factor": 0.5},
            ],
            "edge": [3, 2, 1],
            "weakness": [1, 2, 3],
        },
    },
    "stats": [
        {"key": "brawn", "name": "Brawn", "aliases": ["str"]},
        {"key": "brains", "name": "Brains"},
        {"key": "charm", "name": "Charm"},
    ],
    "tags": [
        {"key": "climbing", "name": "Climbing"},
        {"key": "riddles", "name": "Riddles"},
        {"key": "fire", "name": "Fire", "kind": "element"},
    ],
    "outcomes": [
        {"key": "awful", "label": "Awful", "degree": -2, "success": False},
        {"key": "bad", "label": "Bad", "degree": -1, "success": False},
        {"key": "good", "label": "Good", "degree": 1, "success": True},
        {"key": "great", "label": "Great", "degree": 2, "success": True},
    ],
    "resolver": {
        "params": {
            "noise": "1d6-1d6",
            "bands": [
                {"outcome": "great", "min": 5},
                {"outcome": "good", "min": 0},
                {"outcome": "bad", "min": -5},
                {"outcome": "awful"},
            ],
        },
    },
}


def fresh_test_ruleset() -> dict:
    """A fresh deep copy of `TEST_RULESET`, safe to mutate in a test."""
    return deepcopy(TEST_RULESET)


class RulesetTestMixin:
    """Run each test against `ruleset_spec` (default `TEST_RULESET`).

    Attributes set in `setUp`:
        ruleset: The built `Ruleset`, as `get_ruleset()` returns it.
    """

    ruleset_spec = TEST_RULESET

    def setUp(self):
        super().setUp()
        from django.test import override_settings

        override = override_settings(RP_RULES_RULESET=self.ruleset_spec)
        override.enable()
        self.addCleanup(override.disable)
        reset_ruleset_cache()
        self.addCleanup(reset_ruleset_cache)
        self.ruleset = get_ruleset()

    def scripted(self, *totals: int) -> ScriptedRoller:
        """A roller that returns `totals` in order."""
        return ScriptedRoller(totals)


__all__ = ["TEST_RULESET", "RulesetTestMixin", "fresh_test_ruleset"]
