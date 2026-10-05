# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Syntax, multi-kind spelling collisions and difficulty scale behavior."""

from django.test import SimpleTestCase, override_settings

from evennia_rp_contest.difficulty import resolve_difficulty
from evennia_rp_contest.parsing import ContestError, find_tag, parse_challenge, parse_test
from evennia_rp_rules.testing import RulesetTestMixin, fresh_test_ruleset


class ParsingTests(RulesetTestMixin, SimpleTestCase):
    def test_stat_alias_and_comment_delimiters(self):
        req = parse_test(" #2=str/clim~a {brace} $You() |r~more=still ")
        self.assertEqual((req.stat, req.tag, req.challenge_number), ("brawn", "climbing", 2))
        self.assertEqual(req.comment, "a {brace} $You() |r~more=still")

    def test_optional_tag_and_suggestion(self):
        self.assertIsNone(parse_test("brains").tag)
        req = parse_challenge("High~Cross the chasm")
        self.assertIsNone(req.stat)
        self.assertIsNone(req.tag)
        req = parse_challenge("High=brains/Fire~Read the flames", once=True)
        self.assertEqual((req.stat, req.tag, req.once), ("brains", "fire", True))

    def test_invalid_input(self):
        for text in ("", "#0=brawn", "#foo=brawn", "brains/", "unknown", "brains/nope"):
            with self.subTest(text=text), self.assertRaises(ContestError):
                parse_test(text)
        for text in ("Mid", "~prompt", "Mid~", "Mid=~prompt"):
            with self.subTest(text=text), self.assertRaises(ContestError):
                parse_challenge(text)

    @override_settings(RP_CONTEST_COMMENT_MAX=5)
    def test_long_text_is_refused(self):
        with self.assertRaises(ContestError):
            parse_test("brawn~longer")
        with self.assertRaises(ContestError):
            parse_challenge("Mid~longer")

    @override_settings(RP_CONTEST_TAG_KIND="domain")
    def test_single_kind(self):
        self.assertEqual(find_tag("clim").key, "climbing")
        with self.assertRaises(ContestError):
            find_tag("fire")

    @override_settings(RP_CONTEST_TAG_KIND=None)
    def test_any_kind(self):
        self.assertEqual(find_tag("fire").kind, "element")

    def test_cross_kind_collision_requires_selection(self):
        spec = fresh_test_ruleset()
        spec["tags"].append({"key": "firecraft", "name": "Fire", "kind": "domain"})
        with override_settings(RP_RULES_RULESET=spec):
            with self.assertRaisesRegex(ContestError, "Which tag.*element:fire.*domain:firecraft"):
                find_tag("Fire")
            self.assertEqual(find_tag("element:fire").key, "fire")
            self.assertEqual(find_tag("domain:firecraft").key, "firecraft")

    @override_settings(RP_CONTEST_DEFAULT_DIFFICULTY=None, RP_CONTEST_DIFFICULTIES={"Hard": "High"})
    def test_default_and_presets(self):
        self.assertEqual(resolve_difficulty().rung.key, "mid")
        self.assertEqual(resolve_difficulty("HARD").rung.key, "high")
        self.assertEqual(resolve_difficulty("Mid++", stat="brawn").edge, 2)
