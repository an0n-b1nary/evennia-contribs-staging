# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Effect kinds: building modifiers from data, their filters, and spec errors."""

from __future__ import annotations

import unittest
from fractions import Fraction

from django.test import SimpleTestCase, override_settings

from evennia_rp_rules.checks import Check, resolve_check
from evennia_rp_rules.dice import ScriptedRoller
from evennia_rp_rules.modifiers import (
    BaseModifier,
    EffectSpecError,
    LedgerEntry,
    Modifier,
    RungShift,
    ScoreBonus,
    TagBonus,
    build_modifier,
    effect_kinds,
    effect_problems,
)
from evennia_rp_rules.ruleset import Ruleset
from evennia_rp_rules.subjects import DictStatSource
from evennia_rp_rules.testing import TEST_RULESET
from evennia_rp_rules.vocabulary import RulesetVocabulary

RULES = Ruleset.from_spec(TEST_RULESET)


def run(modifier, *, stat="brains", tags=(), kind="test", rating="Mid", roll=0):
    actor = DictStatSource({stat: rating}, modifiers=[modifier], ruleset=RULES)
    check = Check(kind, actor, stat, tags=tags, difficulty="Mid")
    return resolve_check(check, roller=ScriptedRoller([roll]), ruleset=RULES, send_signal=False)


class BuildTests(unittest.TestCase):
    def test_tag_bonus_scales_with_level(self):
        spec = {"kind": "tag_bonus", "tags": ["riddles"], "score": 8, "per_level": 1}
        for level, amount in ((1, 8), (3, 10), (5, 12)):
            with self.subTest(level=level):
                modifier = build_modifier(spec, level=level, key="expertise")
                self.assertIsInstance(modifier, TagBonus)
                self.assertEqual(modifier.amount, amount)
                self.assertEqual(modifier.tags, frozenset({"riddles"}))

    def test_owner_metadata_and_spec_overrides(self):
        modifier = build_modifier(
            {"kind": "score_bonus", "score": "1.5", "label": "Lucky", "visibility": "hidden"},
            key="charm-1",
            label="Charm",
            source="ability",
            scope="ability",
            visibility="open",
        )
        self.assertEqual((modifier.key, modifier.label), ("charm-1", "Lucky"))
        self.assertEqual((modifier.source, modifier.scope), ("ability", "ability"))
        self.assertEqual(modifier.visibility, "hidden")
        self.assertEqual(modifier.amount, Fraction(3, 2))

    def test_defaults(self):
        modifier = build_modifier({"kind": "rung_shift", "steps": -1})
        self.assertIsInstance(modifier, RungShift)
        self.assertEqual(
            (modifier.key, modifier.label, modifier.visibility),
            ("rung_shift", "rung_shift", "open"),
        )
        self.assertIsInstance(modifier, Modifier)

    def test_every_problem_is_reported_at_once(self):
        with self.assertRaises(EffectSpecError) as caught:
            build_modifier(
                {"kind": "tag_bonus", "score": "lots", "tags": [], "visibility": "loud", "x": 1}
            )
        text = str(caught.exception)
        for fragment in (
            "unknown fields ['x']",
            "'score' must be a number",
            "'tags' must not be empty",
            "visibility must be one of",
        ):
            self.assertIn(fragment, text)

    def test_missing_and_mistyped_fields(self):
        cases = [
            ({"kind": "score_bonus"}, "missing 'score'"),
            ({"kind": "tag_bonus", "score": 1}, "missing 'tags'"),
            ({"kind": "rung_shift", "steps": 1.5}, "'steps' must be a whole number"),
            ({"kind": "score_bonus", "score": 1, "stats": [3]}, "'stats' must be a list"),
            ({"kind": "score_bonus", "score": 1, "stack": ""}, "'stack' must be a non-empty"),
            ({"kind": "score_bonus", "score": 1, "priority": "high"}, "'priority' must be"),
            ({"kind": "nope"}, "unknown effect kind 'nope'"),
            (["kind", "score_bonus"], "must be a mapping"),
        ]
        for spec, fragment in cases:
            with self.subTest(spec=spec):
                with self.assertRaises(EffectSpecError) as caught:
                    build_modifier(spec)
                self.assertIn(fragment, str(caught.exception))

    def test_level_must_be_positive(self):
        with self.assertRaises(EffectSpecError):
            build_modifier({"kind": "score_bonus", "score": 1}, level=0)

    def test_a_single_tag_may_be_a_string(self):
        modifier = build_modifier({"kind": "tag_bonus", "tags": "riddles", "score": 1})
        self.assertEqual(modifier.tags, frozenset({"riddles"}))

    def test_effect_problems_checks_vocabulary_and_stats(self):
        spec = {
            "kind": "score_bonus",
            "score": 1,
            "tags": ["riddles", "juggling"],
            "stats": ["brains", "luck"],
        }
        problems = effect_problems(spec, vocabulary=RulesetVocabulary(RULES), ruleset=RULES)
        self.assertEqual(problems, ["unknown tag 'juggling'", "unknown stat 'luck'"])
        self.assertEqual(effect_problems({"kind": "score_bonus"}), ["score_bonus: missing 'score'"])
        self.assertEqual(effect_problems({"kind": "score_bonus", "score": 1}), [])


class FilterTests(unittest.TestCase):
    def test_tag_bonus_applies_only_on_a_shared_tag(self):
        modifier = TagBonus(4, tags={"riddles", "fire"}, key="expertise")
        self.assertEqual(run(modifier, tags={"riddles"}).score("actor"), 14)
        self.assertEqual(run(modifier, tags={"climbing"}).score("actor"), 10)
        self.assertEqual(run(modifier).score("actor"), 10)

    def test_stat_and_kind_filters(self):
        modifier = ScoreBonus(-2, stats={"charm"}, check_kinds={"test"}, key="shy")
        self.assertEqual(run(modifier, stat="charm").score("actor"), 8)
        self.assertEqual(run(modifier, stat="brains").score("actor"), 10)
        self.assertEqual(run(modifier, stat="charm", kind="combat").score("actor"), 10)

    def test_rung_shift_keeps_pips_and_clamps(self):
        up = RungShift(1, key="blessed")
        result = run(up, rating="Mid+")
        self.assertEqual(result.effective["actor"].display(), "High +")
        self.assertEqual(result.score("actor"), Fraction(43, 2))  # 20 + 3 * 0.5
        self.assertEqual(run(RungShift(5, key="x")).effective["actor"].rung.key, "high")
        self.assertEqual(run(RungShift(-5, key="x")).effective["actor"].rung.key, "low")

    def test_opposing_match_resists_the_other_sides_tags(self):
        resist = build_modifier(
            {"kind": "tag_bonus", "tags": ["riddles"], "score": 3, "match": "opposing"},
            key="resistance",
        )
        expert = TagBonus(3, tags={"riddles"}, key="expertise")
        actor = DictStatSource({"brains": "Mid"}, ruleset=RULES)
        opponent = DictStatSource({"brains": "Mid"}, modifiers=[resist, expert], ruleset=RULES)
        check = Check("test", actor, "brains", tags={"riddles"}, opponent=opponent)
        result = resolve_check(check, roller=ScriptedRoller([0]), ruleset=RULES, send_signal=False)
        # Resistance sees the actor's Riddles; the opponent's own side carries no tags.
        self.assertEqual([e.key for e in result.ledger], ["resistance"])
        self.assertEqual(result.score("target"), 13)

    def test_match_must_be_known(self):
        with self.assertRaises(EffectSpecError) as caught:
            build_modifier({"kind": "tag_bonus", "tags": ["x"], "score": 1, "match": "sideways"})
        self.assertIn("'match' must be one of", str(caught.exception))
        with self.assertRaises(ValueError):
            ScoreBonus(1, key="x", match="sideways")

    def test_tag_bonus_needs_tags(self):
        with self.assertRaises(ValueError):
            TagBonus(1, tags=(), key="x")


class LedgerEntryTests(unittest.TestCase):
    def test_describe(self):
        entry = LedgerEntry("expertise", "Expertise: Riddles", "actor", "actor", "build", score=8)
        self.assertEqual(entry.describe(), "Expertise: Riddles +8")
        shift = LedgerEntry("b", "Blessed", "actor", "actor", "build", rung=1)
        self.assertEqual(shift.describe(), "Blessed +1 rung")
        both = LedgerEntry("c", "", "actor", "actor", "build", score=Fraction(-3, 2), rung=-2)
        self.assertEqual(both.describe(), "c -1.5 -2 rungs")
        lost = LedgerEntry(
            "d",
            "Dim",
            "actor",
            "actor",
            "build",
            score=1,
            applied=False,
            reason="doesn't stack with Bright",
        )
        self.assertEqual(lost.describe(), "Dim +1 (not applied: doesn't stack with Bright)")


class Doubled(BaseModifier):
    """A custom effect kind: doubles the owner's rung score as a bonus."""

    def __init__(self, **meta):
        self.key = meta.get("key") or "doubled"
        self.label = meta.get("label") or "Doubled"

    @classmethod
    def from_spec(cls, spec, *, level=1, **meta):
        if "oops" in spec:
            raise EffectSpecError(["doubled: oops"])
        return cls(**meta)

    def apply(self, phase, ctx):
        ctx.add(score=ctx.rating().rung.score)


class CustomKindTests(SimpleTestCase):
    @override_settings(RP_RULES_EFFECT_KINDS={"doubled": f"{__name__}.Doubled"})
    def test_settings_add_kinds(self):
        self.assertIn("doubled", effect_kinds())
        modifier = build_modifier({"kind": "doubled"}, key="d")
        self.assertIsInstance(modifier, Doubled)
        self.assertEqual(run(modifier).score("actor"), 20)
        self.assertEqual(effect_problems({"kind": "doubled", "oops": 1}), ["doubled: oops"])

    @override_settings(RP_RULES_EFFECT_KINDS={"bad": "no.such.Kind"})
    def test_unimportable_kind_is_improperly_configured(self):
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            effect_kinds()

    @override_settings(RP_RULES_EFFECT_KINDS={"bad": f"{__name__}.run"})
    def test_kind_without_from_spec_is_improperly_configured(self):
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            effect_kinds()


if __name__ == "__main__":
    unittest.main()
