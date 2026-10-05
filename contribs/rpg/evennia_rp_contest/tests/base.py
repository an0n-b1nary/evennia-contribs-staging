# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Tests use a stat-block adapter and require no chargen installation."""

from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from evennia_rp_rules.subjects import DictStatSource
from evennia_rp_rules.testing import RulesetTestMixin


def stat_block_adapter(obj):
    return DictStatSource(obj.attributes.get("contest_test_stats", default={}), name=obj.key)


class ContestMixin(RulesetTestMixin):
    def setUp(self):
        super().setUp()
        override = override_settings(
            RP_RULES_SUBJECT_ADAPTER="evennia_rp_contest.tests.base.stat_block_adapter",
            RP_RULES_VOCABULARY=None,
            RP_CONTEST_DEFAULT_DIFFICULTY="Mid",
            RP_CONTEST_SCENE_ID_RESOLVER=None,
        )
        override.enable()
        self.addCleanup(override.disable)
        for character in (self.char1, self.char2):
            character.attributes.add("contest_test_stats", {k: "Mid" for k in self.ruleset.stats})


class ContestTest(ContestMixin, EvenniaTest):
    pass


class ContestCommandTest(ContestMixin, EvenniaCommandTest):
    pass
