# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Shared fixtures for the chargen suites.

Every test runs on evennia_rp_rules' TEST_RULESET: stats Brawn, Brains and
Charm on the tier scale Low / Mid / High, at most 3 edge and 3 weakness.
`POINT_BUY` costs Low 0, Mid 1, High 3 against a budget of 4.
"""

from __future__ import annotations

from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from evennia_rp_chargen import services
from evennia_rp_chargen.stats import StatHandler
from evennia_rp_rules.testing import RulesetTestMixin

POINT_BUY = {
    "path": "evennia_rp_chargen.allocation.PointBuyAllocation",
    "params": {"costs": {"low": 0, "mid": 1, "high": 3}, "budget": 4},
}


class ChargenTestMixin(RulesetTestMixin):
    def make_sheet(self, character, *, finalize=True, **ratings):
        """Give `character` a sheet: unnamed stats default to Low."""
        services.ensure_build(character)
        handler = StatHandler(character)
        for key in self.ruleset.stats:
            handler.set(key, self.ruleset.parse_rating(ratings.get(key, "Low")))
        if finalize:
            services.finalize(character)
        return services.get_build(character)


class ChargenTest(ChargenTestMixin, EvenniaTest):
    pass


class ChargenCommandTest(ChargenTestMixin, EvenniaCommandTest):
    pass
