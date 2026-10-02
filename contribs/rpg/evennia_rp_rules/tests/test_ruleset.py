# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Ruleset validation, lookup, loading, and the settings-backed cache."""

from __future__ import annotations

import pathlib
import tempfile
import textwrap
import unittest

from django.test import SimpleTestCase, override_settings

from evennia_rp_rules.example_ruleset import RULESET as EXAMPLE_RULESET
from evennia_rp_rules.issues import RulesetError
from evennia_rp_rules.ruleset import (
    Ruleset,
    get_ruleset,
    load_ruleset_spec,
    reset_ruleset_cache,
    spec_digest,
)
from evennia_rp_rules.testing import TEST_RULESET, RulesetTestMixin, fresh_test_ruleset


def issue_ids(spec) -> list[str]:
    return [issue.id for issue in Ruleset.validate(spec)]


def messages(spec) -> str:
    return " | ".join(issue.message for issue in Ruleset.validate(spec))


class ValidationTests(unittest.TestCase):
    def test_bundled_rulesets_are_clean(self):
        self.assertEqual(Ruleset.validate(EXAMPLE_RULESET), [])
        self.assertEqual(Ruleset.validate(TEST_RULESET), [])

    def test_built_ruleset_exposes_its_parts(self):
        ruleset = Ruleset.from_spec(TEST_RULESET)
        self.assertEqual(ruleset.version, "test")
        self.assertEqual(sorted(ruleset.stats), ["brains", "brawn", "charm"])
        self.assertEqual(ruleset.stats["brawn"].scale.key, "tier")
        self.assertEqual(ruleset.default_scale.key, "tier")
        self.assertEqual(ruleset.tags["fire"].kind, "element")
        self.assertEqual(ruleset.tags["climbing"].kind, "domain")
        self.assertEqual(ruleset.resolver.key, "graded")

    def test_missing_sections_are_e001(self):
        spec = fresh_test_ruleset()
        for key in ("version", "scales", "stats", "outcomes"):
            del spec[key]
        text = messages(spec)
        for key in ("version", "scales", "stats", "outcomes"):
            self.assertIn(f"missing {key!r}", text)
        with self.assertRaises(RulesetError):
            Ruleset.from_spec(spec)

    def test_unknown_top_level_key_is_e001(self):
        spec = fresh_test_ruleset() | {"outcome": []}
        self.assertEqual(issue_ids(spec), ["E001"])

    def test_stat_problems(self):
        spec = fresh_test_ruleset()
        spec["stats"] += [
            {"key": "Brawn!", "name": "Bad"},
            {"key": "brawn", "name": "Again"},
            {"key": "wit", "name": "Wit", "aliases": ["STR"]},
            {"key": "luck", "name": "Luck", "scale": "fate"},
        ]
        text = messages(spec)
        self.assertIn("invalid key 'Brawn!'", text)
        self.assertIn("duplicate stat 'brawn'", text)
        self.assertIn("'str' is already used by 'brawn'", text)
        self.assertIn("unknown scale 'fate'", text)
        self.assertIn("E002", issue_ids(spec))

    def test_tag_spellings_are_unique_per_kind_only(self):
        spec = fresh_test_ruleset()
        spec["tags"].append(
            {"key": "fire-domain", "name": "Fire"}
        )  # domain "Fire" beside element "Fire"
        self.assertEqual(Ruleset.validate(spec), [])
        spec["tags"].append(
            {"key": "blaze", "name": "Blaze", "kind": "element", "aliases": ["fire"]}
        )
        self.assertIn("already used by 'fire'", messages(spec))

    def test_several_scales_need_a_default_or_explicit_scales(self):
        spec = fresh_test_ruleset()
        spec["scales"]["coin"] = {
            "rungs": [{"key": "tails", "score": 0}, {"key": "heads", "score": 1}]
        }
        self.assertIn("required when more than one scale", messages(spec))
        spec["default_scale"] = "tier"
        self.assertEqual(Ruleset.validate(spec), [])
        spec["default_scale"] = "nope"
        self.assertIn("unknown scale 'nope'", messages(spec))

    def test_resolver_problems_are_e002(self):
        spec = fresh_test_ruleset()
        spec["resolver"]["path"] = "evennia_rp_rules.resolvers.NoSuchResolver"
        self.assertIn("can't import", messages(spec))
        spec = fresh_test_ruleset()
        spec["resolver"]["params"]["bands"][0]["outcome"] = "meh"
        spec["resolver"]["params"]["noise"] = "2x6"
        ids = issue_ids(spec)
        self.assertEqual(ids, ["E002", "E002"])

    def test_crossing_pips_fail_the_ruleset_with_e003(self):
        spec = fresh_test_ruleset()
        spec["scales"]["tier"]["edge"] = [5, 4, 1]
        with self.assertRaises(RulesetError) as caught:
            Ruleset.from_spec(spec)
        self.assertEqual({i.id for i in caught.exception.issues}, {"E003"})

    def test_dead_pips_warn_but_still_build(self):
        spec = fresh_test_ruleset()
        spec["scales"]["tier"]["edge"] = [3, 0.25, 0.25]
        issues = Ruleset.validate(spec)
        self.assertEqual({(i.id, i.level) for i in issues}, {("W001", "warning")})
        self.assertIn("Mid++ = Mid+", issues[0].message + issues[1].message)
        Ruleset.from_spec(spec)  # does not raise

    def test_every_problem_is_reported_at_once(self):
        spec = fresh_test_ruleset()
        spec["version"] = ""
        spec["stats"][0]["key"] = "BAD"
        spec["outcomes"][0]["degree"] = "x"
        spec["scales"]["tier"]["edge"] = [99]
        self.assertGreaterEqual(len(Ruleset.validate(spec)), 4)

    def test_digest_is_stable_and_content_sensitive(self):
        self.assertEqual(spec_digest(fresh_test_ruleset()), spec_digest(TEST_RULESET))
        changed = fresh_test_ruleset()
        changed["resolver"]["params"]["noise"] = "2d6-2d6"
        self.assertNotEqual(spec_digest(changed), spec_digest(TEST_RULESET))
        self.assertEqual(Ruleset.from_spec(TEST_RULESET).digest, spec_digest(TEST_RULESET))


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.ruleset = Ruleset.from_spec(TEST_RULESET)

    def test_find_stat_by_key_name_alias_and_unique_prefix(self):
        for text in ("brawn", "Brawn", "STR", "brainS"):
            with self.subTest(text=text):
                self.assertIn(self.ruleset.find_stat(text).key, {"brawn", "brains"})
        self.assertEqual(self.ruleset.find_stat("str").key, "brawn")
        self.assertEqual(self.ruleset.find_stat("ch").key, "charm")

    def test_ambiguous_and_unknown_stats(self):
        with self.assertRaisesRegex(LookupError, "could mean Brains, Brawn"):
            self.ruleset.find_stat("bra")
        with self.assertRaisesRegex(
            LookupError, "Unknown stat 'luck'. Choose from: Brains, Brawn, Charm"
        ):
            self.ruleset.find_stat("luck")
        with self.assertRaises(LookupError):
            self.ruleset.find_stat("  ")

    def test_find_tag_can_filter_by_kind(self):
        self.assertEqual(self.ruleset.find_tag("fire").key, "fire")
        with self.assertRaisesRegex(LookupError, "Unknown domain 'fire'"):
            self.ruleset.find_tag("fire", kind="domain")
        self.assertEqual(self.ruleset.find_tag("climb", kind="domain").key, "climbing")

    def test_parse_rating_uses_the_default_scale(self):
        self.assertEqual(self.ruleset.parse_rating("Mid++").score(), 15)


class LoadingTests(unittest.TestCase):
    def test_mapping_passes_through(self):
        self.assertIs(load_ruleset_spec(TEST_RULESET), TEST_RULESET)

    def test_module_and_attribute_paths(self):
        self.assertIs(load_ruleset_spec("evennia_rp_rules.example_ruleset"), EXAMPLE_RULESET)
        self.assertIs(load_ruleset_spec("evennia_rp_rules.testing.TEST_RULESET"), TEST_RULESET)

    def test_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "my_rules.py"
            path.write_text(
                textwrap.dedent(
                    """
                    from evennia_rp_rules.testing import fresh_test_ruleset
                    RULESET = fresh_test_ruleset()
                    RULESET["version"] = "from-file"
                    """
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_ruleset_spec(str(path))["version"], "from-file")

    def test_bad_references_are_e001(self):
        for ref in (
            "no.such.module",
            "evennia_rp_rules.dice",
            "evennia_rp_rules.testing.NOPE",
            "missing.py",
            "",
            7,
        ):
            with self.subTest(ref=ref), self.assertRaises(RulesetError) as caught:
                load_ruleset_spec(ref)
            self.assertEqual(caught.exception.issues[0].id, "E001")


class SettingsTests(SimpleTestCase):
    def setUp(self):
        reset_ruleset_cache()
        self.addCleanup(reset_ruleset_cache)

    def test_default_is_the_example_ruleset(self):
        with override_settings():
            from django.conf import settings

            if hasattr(settings, "RP_RULES_RULESET"):
                del settings.RP_RULES_RULESET
            reset_ruleset_cache()
            self.assertEqual(get_ruleset().version, EXAMPLE_RULESET["version"])

    def test_setting_accepts_a_dotted_path_and_is_cached(self):
        with override_settings(RP_RULES_RULESET="evennia_rp_rules.testing.TEST_RULESET"):
            first = get_ruleset()
            self.assertEqual(first.version, "test")
            self.assertIs(get_ruleset(), first)

    def test_changing_the_setting_clears_the_cache(self):
        with override_settings(RP_RULES_RULESET=TEST_RULESET):
            self.assertEqual(get_ruleset().version, "test")
            changed = fresh_test_ruleset() | {"version": "changed"}
            with override_settings(RP_RULES_RULESET=changed):
                self.assertEqual(get_ruleset().version, "changed")
            self.assertEqual(get_ruleset().version, "test")

    def test_unrelated_settings_keep_the_cache(self):
        with override_settings(RP_RULES_RULESET=TEST_RULESET):
            first = get_ruleset()
            with override_settings(SOME_OTHER_SETTING=1):
                self.assertIs(get_ruleset(), first)

    def test_invalid_setting_raises(self):
        broken = fresh_test_ruleset()
        broken["scales"]["tier"]["edge"] = [50]
        with override_settings(RP_RULES_RULESET=broken), self.assertRaises(RulesetError):
            get_ruleset()


class MixinTests(RulesetTestMixin, SimpleTestCase):
    def test_mixin_exposes_the_test_ruleset(self):
        self.assertEqual(self.ruleset.version, "test")
        self.assertIs(get_ruleset(), self.ruleset)
        self.assertEqual(self.scripted(1, 2).roll("1d6").total, 1)


class CustomSpecMixinTests(RulesetTestMixin, SimpleTestCase):
    ruleset_spec = EXAMPLE_RULESET

    def test_subclass_can_choose_its_spec(self):
        self.assertEqual(self.ruleset.version, EXAMPLE_RULESET["version"])
