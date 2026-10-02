# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""System checks: ruleset issues and unresolvable RP_RULES_* paths surface at startup."""

from __future__ import annotations

from django.core import checks
from django.test import SimpleTestCase, override_settings

from evennia_rp_rules.system_checks import check_dotted_paths, check_ruleset
from evennia_rp_rules.testing import TEST_RULESET, fresh_test_ruleset


def ids(messages) -> list[str]:
    return [message.id for message in messages]


def crossing_ruleset() -> dict:
    spec = fresh_test_ruleset()
    spec["scales"]["tier"]["edge"] = [9, 9, 9]
    return spec


class RulesetCheckTests(SimpleTestCase):
    def test_default_and_test_rulesets_are_clean(self):
        self.assertEqual(check_ruleset(), [])
        with override_settings(RP_RULES_RULESET=TEST_RULESET):
            self.assertEqual(check_ruleset(), [])

    @override_settings(RP_RULES_RULESET="no.such.module")
    def test_unloadable_ruleset_is_e001(self):
        self.assertEqual(ids(check_ruleset()), ["evennia_rp_rules.E001"])

    def test_crossing_pips_are_errors(self):
        with override_settings(RP_RULES_RULESET=crossing_ruleset()):
            messages = check_ruleset()
        self.assertTrue(messages)
        self.assertTrue(all(m.id == "evennia_rp_rules.E003" for m in messages))
        self.assertTrue(all(m.level == checks.ERROR for m in messages))
        self.assertTrue(all(m.hint for m in messages))

    def test_dead_pips_are_warnings(self):
        spec = fresh_test_ruleset()
        spec["scales"]["tier"]["edge"] = [3, 2, 0.5]
        with override_settings(RP_RULES_RULESET=spec):
            messages = check_ruleset()
        self.assertTrue(messages)
        self.assertEqual(set(ids(messages)), {"evennia_rp_rules.W001"})
        self.assertTrue(all(m.level == checks.WARNING for m in messages))

    def test_registered_with_django(self):
        with override_settings(RP_RULES_RULESET=crossing_ruleset()):
            found = ids(checks.run_checks())
        self.assertIn("evennia_rp_rules.E003", found)


def a_provider(check):
    return []


class Kind:
    @classmethod
    def from_spec(cls, spec, **meta):
        return cls()


class DottedPathCheckTests(SimpleTestCase):
    def test_nothing_configured_is_clean(self):
        self.assertEqual(check_dotted_paths(), [])

    @override_settings(
        RP_RULES_SUBJECT_ADAPTER=f"{__name__}.a_provider",
        RP_RULES_VOCABULARY=f"{__name__}.Kind",
        RP_RULES_ROLLER=f"{__name__}.Kind",
        RP_RULES_MODIFIER_PROVIDERS=[f"{__name__}.a_provider"],
        RP_RULES_EFFECT_KINDS={"k": f"{__name__}.Kind"},
    )
    def test_good_paths_are_clean(self):
        self.assertEqual(check_dotted_paths(), [])

    @override_settings(
        RP_RULES_SUBJECT_ADAPTER="nowhere.adapter",
        RP_RULES_VOCABULARY="nodots",
        RP_RULES_MODIFIER_PROVIDERS=[f"{__name__}.a_provider", f"{__name__}.missing"],
        RP_RULES_EFFECT_KINDS={"k": f"{__name__}.a_provider"},
    )
    def test_bad_paths_are_w002(self):
        messages = check_dotted_paths()
        self.assertEqual(ids(messages), ["evennia_rp_rules.W002"] * 4)
        text = " | ".join(m.msg for m in messages)
        for fragment in (
            "RP_RULES_SUBJECT_ADAPTER",
            "RP_RULES_VOCABULARY",
            "RP_RULES_MODIFIER_PROVIDERS[1]",
            "has no from_spec()",
        ):
            self.assertIn(fragment, text)

    @override_settings(RP_RULES_MODIFIER_PROVIDERS="one.path.only")
    def test_a_bare_string_provider_setting_is_flagged(self):
        self.assertEqual(ids(check_dotted_paths()), ["evennia_rp_rules.W002"])

    @override_settings(RP_RULES_ROLLER=f"{__name__}.CONSTANT")
    def test_non_callable_is_flagged(self):
        self.assertEqual(ids(check_dotted_paths()), ["evennia_rp_rules.W002"])


CONSTANT = 4
