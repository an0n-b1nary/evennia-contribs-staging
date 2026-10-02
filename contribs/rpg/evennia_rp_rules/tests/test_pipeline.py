# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The phased pipeline: collection, phases, stacking, visibility, and order-independence.

TEST_RULESET: tier Low 0 / Mid 10 / High 20, noise 1d6-1d6, bands great >= 5,
good >= 0, bad >= -5, awful below.
"""

from __future__ import annotations

import os
import pathlib
import random
import subprocess
import sys
import unittest

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from evennia_rp_rules.checks import Check, estimate_check, resolve_check
from evennia_rp_rules.dice import ScriptedRoller
from evennia_rp_rules.modifiers import BaseModifier, RungShift, ScoreBonus, TagBonus
from evennia_rp_rules.phases import (
    BUILD,
    CHECK_PHASES,
    DECLARE,
    HIDDEN,
    ON_OUTCOME,
    PRE_RESOLVE,
    SECRET,
    TARGET,
)
from evennia_rp_rules.pipeline import applicable_modifiers
from evennia_rp_rules.ruleset import Ruleset
from evennia_rp_rules.subjects import DictStatSource
from evennia_rp_rules.testing import TEST_RULESET, ProbeSubject, RulesetTestMixin

RULES = Ruleset.from_spec(TEST_RULESET)


def actor(*modifiers, rating="Mid"):
    return ProbeSubject({"brains": rating}, modifiers=modifiers, name="Ana", ruleset=RULES)


def resolve(check, roll=0):
    return resolve_check(check, roller=ScriptedRoller([roll]), ruleset=RULES, send_signal=False)


class Recorder(BaseModifier):
    """Hooks every phase and records what it saw."""

    def __init__(self, key="recorder", hooks=CHECK_PHASES):
        self.key = key
        self._hooks = set(hooks)
        self.seen = []

    def hooks(self):
        return self._hooks

    def apply(self, phase, ctx):
        self.seen.append((phase, ctx.score(), ctx.score(ctx.other_side), ctx.resolution))


class Momentum(BaseModifier):
    """PRE_RESOLVE: +1 if the owner already out-scores the other side after BUILD."""

    key = "momentum"
    label = "Momentum"

    def hooks(self):
        return {PRE_RESOLVE}

    def apply(self, phase, ctx):
        if ctx.score() > ctx.score(ctx.other_side):
            ctx.add(score=1)


class Peeker(BaseModifier):
    """BUILD: adds as much as the owner's bonus so far, which is always 0 mid-phase."""

    key = "peeker"

    def apply(self, phase, ctx):
        ctx.add(score=ctx.bonus() + 1)


class Narrator(BaseModifier):
    key = "narrator"

    def __init__(self):
        self.errors = []

    def hooks(self):
        return {ON_OUTCOME}

    def apply(self, phase, ctx):
        ctx.note(f"outcome was {ctx.resolution.outcome.key}")
        try:
            ctx.add(score=5)
        except RuntimeError as exc:
            self.errors.append(str(exc))


class Hampers(BaseModifier):
    """Penalises the other side instead of helping its owner."""

    key = "hampers"
    label = "Hampers"

    def apply(self, phase, ctx):
        ctx.add(score=-2, side=ctx.other_side)


class PhaseTests(unittest.TestCase):
    def test_check_phases_run_in_order_and_outcome_sees_the_resolution(self):
        recorder = Recorder()
        result = resolve(
            Check("test", actor(recorder, ScoreBonus(2, key="b")), "brains", difficulty="Mid"),
            roll=1,
        )
        phases = [seen[0] for seen in recorder.seen]
        self.assertEqual(phases, [BUILD, PRE_RESOLVE, ON_OUTCOME])
        # BUILD sees the phase-start state; PRE_RESOLVE sees BUILD's bonus.
        self.assertEqual(recorder.seen[0][1], 10)
        self.assertEqual(recorder.seen[1][1], 12)
        self.assertIsNone(recorder.seen[1][3])
        self.assertIs(recorder.seen[2][3], result.resolution)

    def test_reserved_phases_never_run_in_a_check(self):
        recorder = Recorder(hooks={DECLARE})
        resolve(Check("test", actor(recorder), "brains", difficulty="Mid"))
        self.assertEqual(recorder.seen, [])

    def test_within_a_phase_modifiers_see_the_phase_start(self):
        result = resolve(
            Check("test", actor(Peeker(), ScoreBonus(5, key="b")), "brains", difficulty="Mid")
        )
        self.assertEqual(result.bonuses["actor"], 6)

    def test_pre_resolve_reacts_to_build(self):
        ahead = resolve(
            Check("test", actor(Momentum(), ScoreBonus(1, key="b")), "brains", difficulty="Mid")
        )
        self.assertEqual(ahead.bonuses["actor"], 2)
        even = resolve(Check("test", actor(Momentum()), "brains", difficulty="Mid"))
        self.assertEqual(even.bonuses["actor"], 0)

    def test_on_outcome_notes_but_cannot_change_numbers(self):
        narrator = Narrator()
        result = resolve(Check("test", actor(narrator), "brains", difficulty="Mid"), roll=5)
        self.assertEqual([n.text for n in result.notes], ["outcome was great"])
        self.assertEqual(len(narrator.errors), 1)
        self.assertEqual(result.bonuses["actor"], 0)

    def test_estimates_skip_on_outcome(self):
        recorder = Recorder()
        estimate_check(Check("test", actor(recorder), "brains", difficulty="Mid"), ruleset=RULES)
        self.assertEqual([seen[0] for seen in recorder.seen], [BUILD, PRE_RESOLVE])

    def test_modifiers_can_target_the_other_side(self):
        result = resolve(Check("test", actor(Hampers()), "brains", difficulty="Mid"))
        self.assertEqual(result.score("target"), 8)
        entry = result.ledger[0]
        self.assertEqual((entry.owner, entry.side), ("actor", "target"))

    def test_applies_is_asked_once_with_no_phase(self):
        class Picky(BaseModifier):
            key = "picky"

            def __init__(self):
                self.asked = []

            def applies(self, ctx):
                self.asked.append(ctx.phase)
                return False

            def apply(self, phase, ctx):  # pragma: no cover - never applies
                raise AssertionError

        picky = Picky()
        resolve(Check("test", actor(picky), "brains", difficulty="Mid"))
        self.assertEqual(picky.asked, [None])


class CollectionTests(unittest.TestCase):
    def test_subject_check_and_opponent_modifiers_are_collected(self):
        opponent = ProbeSubject(
            {"brains": "Mid"}, modifiers=[ScoreBonus(3, key="foe")], ruleset=RULES
        )
        ana = actor(ScoreBonus(1, key="mine"))
        check = Check(
            "test", ana, "brains", opponent=opponent, modifiers=[ScoreBonus(-1, key="weather")]
        )
        result = resolve(check)
        self.assertEqual(ana.seen, [check])
        self.assertEqual(opponent.seen, [check])
        owners = {e.key: e.owner for e in result.ledger}
        self.assertEqual(owners, {"mine": "actor", "foe": "target", "weather": "actor"})
        self.assertEqual(result.bonuses, {"actor": 0, "target": 3})

    def test_loose_modifiers_choose_their_side(self):
        storm = ScoreBonus(-2, key="storm")
        storm.side = TARGET
        result = resolve(Check("test", actor(), "brains", difficulty="Mid", modifiers=[storm]))
        self.assertEqual(result.score("target"), 8)
        bad = ScoreBonus(1, key="bad")
        bad.side = "middle"
        with self.assertRaises(ValueError):
            resolve(Check("test", actor(), "brains", difficulty="Mid", modifiers=[bad]))

    def test_applicable_modifiers_previews_without_running(self):
        expertise = TagBonus(8, tags={"riddles"}, key="expertise")
        check = Check(
            "test",
            actor(expertise, ScoreBonus(1, key="b", stats={"charm"})),
            "brains",
            tags={"riddles"},
            difficulty="Mid",
        )
        self.assertEqual(applicable_modifiers(check, ruleset=RULES), [("actor", expertise)])

    def test_unknown_visibility_is_rejected(self):
        loud = ScoreBonus(1, key="loud", visibility="loud")
        with self.assertRaises(ValueError):
            resolve(Check("test", actor(loud), "brains", difficulty="Mid"))


class StackingTests(unittest.TestCase):
    def test_only_the_strongest_of_a_stack_counts(self):
        small = ScoreBonus(2, key="small", label="Small", stack="blessing")
        big = ScoreBonus(5, key="big", label="Big", stack="blessing")
        other = ScoreBonus(1, key="other")
        result = resolve(Check("test", actor(small, big, other), "brains", difficulty="Mid"))
        self.assertEqual(result.bonuses["actor"], 6)
        lost = [e for e in result.ledger if not e.applied]
        self.assertEqual([e.key for e in lost], ["small"])
        self.assertEqual(lost[0].reason, "doesn't stack with Big")

    def test_rung_shifts_outrank_scores_in_a_stack(self):
        shift = RungShift(1, key="shift", stack="s")
        bonus = ScoreBonus(9, key="bonus", stack="s")
        result = resolve(Check("test", actor(shift, bonus), "brains", difficulty="Mid"))
        self.assertEqual(result.effective["actor"].rung.key, "high")
        self.assertEqual(result.bonuses["actor"], 0)

    def test_stacks_are_per_side(self):
        mine = ScoreBonus(2, key="mine", stack="aura")
        theirs = ScoreBonus(3, key="theirs", stack="aura")
        theirs.side = TARGET
        result = resolve(Check("test", actor(mine), "brains", difficulty="Mid", modifiers=[theirs]))
        self.assertEqual(result.bonuses, {"actor": 2, "target": 3})

    def test_a_later_phase_can_win_a_stack(self):
        class LateBig(ScoreBonus):
            def hooks(self):
                return {PRE_RESOLVE}

        early = ScoreBonus(2, key="early", stack="x")
        late = LateBig(4, key="late", stack="x")
        result = resolve(Check("test", actor(early, late), "brains", difficulty="Mid"))
        self.assertEqual(result.bonuses["actor"], 4)
        self.assertEqual([e.key for e in result.ledger if not e.applied], ["early"])


class VisibilityTests(unittest.TestCase):
    def setUp(self):
        self.open = ScoreBonus(1, key="open")
        self.feint = ScoreBonus(2, key="feint", visibility=HIDDEN)
        self.thumb = ScoreBonus(4, key="thumb", visibility=SECRET)
        self.guard = ScoreBonus(3, key="guard", visibility=HIDDEN)
        self.opponent = DictStatSource({"brains": "Mid"}, modifiers=[self.guard], ruleset=RULES)
        self.check = Check(
            "test", actor(self.open, self.feint, self.thumb), "brains", opponent=self.opponent
        )

    def keys(self, entries):
        return sorted(e.key for e in entries)

    def test_entries_for_each_viewer(self):
        result = resolve(self.check)
        self.assertEqual(
            self.keys(result.entries_for("staff")), ["feint", "guard", "open", "thumb"]
        )
        self.assertEqual(self.keys(result.entries_for("actor")), ["feint", "open"])
        self.assertEqual(self.keys(result.entries_for("target")), ["guard", "open"])
        self.assertEqual(self.keys(result.entries_for()), ["open"])
        with self.assertRaises(ValueError):
            result.entries_for("room")

    def test_estimates_count_only_what_the_viewer_knows(self):
        def bonuses(viewer):
            estimate = estimate_check(self.check, viewer=viewer, ruleset=RULES)
            return estimate.bonuses["actor"], estimate.bonuses["target"]

        self.assertEqual(bonuses("staff"), (7, 3))
        self.assertEqual(bonuses("actor"), (3, 0))
        self.assertEqual(bonuses("target"), (1, 3))
        self.assertEqual(bonuses("public"), (1, 0))

    def test_resolution_always_counts_everything(self):
        self.assertEqual(resolve(self.check).bonuses, {"actor": 7, "target": 3})

    def test_hidden_entries_from_open_modifiers_stay_out_of_estimates(self):
        class Sly(BaseModifier):
            key = "sly"

            def apply(self, phase, ctx):
                ctx.add(score=1)
                ctx.add(score=10, visibility=SECRET, label="sly secret")

        check = Check("test", actor(Sly()), "brains", difficulty="Mid")
        self.assertEqual(estimate_check(check, viewer="actor", ruleset=RULES).bonuses["actor"], 1)
        self.assertEqual(estimate_check(check, viewer="staff", ruleset=RULES).bonuses["actor"], 11)


class CommutativityTests(unittest.TestCase):
    """Shuffling where modifiers come from, and in what order, never changes a result."""

    def modifiers(self):
        return [
            TagBonus(8, per_level=1, level=3, tags={"riddles"}, key="expertise"),
            ScoreBonus(-2, key="flaw"),
            ScoreBonus(2, key="small", stack="blessing"),
            ScoreBonus(2, key="tie", stack="blessing"),
            ScoreBonus(5, key="big", stack="blessing"),
            RungShift(1, key="shift"),
            RungShift(-1, key="unshift", tags={"riddles"}),
            Momentum(),
            Peeker(),
            Hampers(),
            ScoreBonus(3, key="feint", visibility=HIDDEN),
        ]

    def record(self, rng):
        mods = self.modifiers()
        rng.shuffle(mods)
        cut = rng.randrange(len(mods) + 1)
        check = Check(
            "test",
            actor(*mods[:cut], rating="Mid+"),
            "brains",
            tags={"riddles"},
            difficulty="High-",
            modifiers=mods[cut:],
        )
        result = resolve(check, roll=2).as_dict()
        estimate = estimate_check(check, viewer="actor", ruleset=RULES).as_dict()
        return result, estimate

    def test_shuffled_sources_give_identical_results(self):
        rng = random.Random(20261002)
        baseline = self.record(rng)
        for _ in range(25):
            self.assertEqual(self.record(rng), baseline)

    def test_shuffled_subject_order_gives_identical_results(self):
        mods = self.modifiers()
        forward = resolve(Check("test", actor(*mods), "brains", difficulty="Mid")).as_dict()
        backward = resolve(
            Check("test", actor(*reversed(mods)), "brains", difficulty="Mid")
        ).as_dict()
        self.assertEqual(forward, backward)


def give_storm(check):
    return [ScoreBonus(-1, key="storm", label="Storm")]


def give_nothing(check):
    return None


def adapt(obj):
    if obj == "npc":
        return DictStatSource({"brains": "High"}, name="NPC")
    return None


class SettingsTests(RulesetTestMixin, SimpleTestCase):
    @override_settings(
        RP_RULES_MODIFIER_PROVIDERS=[f"{__name__}.give_storm", f"{__name__}.give_nothing"]
    )
    def test_providers_from_settings(self):
        result = resolve_check(
            Check("test", {"brains": "Mid"}, "brains", difficulty="Mid"), roller=self.scripted(0)
        )
        self.assertEqual([e.label for e in result.ledger], ["Storm"])
        self.assertEqual(result.score("actor"), 9)

    @override_settings(RP_RULES_MODIFIER_PROVIDERS=["no.such.provider"])
    def test_bad_provider_is_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured):
            resolve_check(
                Check("test", {"brains": "Mid"}, "brains", difficulty="Mid"),
                roller=self.scripted(0),
            )

    @override_settings(RP_RULES_SUBJECT_ADAPTER=f"{__name__}.adapt")
    def test_subject_adapter_from_settings(self):
        result = resolve_check(
            Check("test", "npc", "brains", difficulty="Mid"), roller=self.scripted(0)
        )
        self.assertEqual(result.score("actor"), 20)

    @override_settings(RP_RULES_ROLLER=f"{__name__}.scripted_four")
    def test_roller_from_settings(self):
        result = resolve_check(Check("test", {"brains": "Mid"}, "brains", difficulty="Mid"))
        self.assertEqual(result.resolution.roll.total, 4)


def scripted_four():
    return ScriptedRoller([4])


class NoSettingsTests(unittest.TestCase):
    def test_pipeline_runs_without_configured_settings(self):
        probe = (
            "from evennia_rp_rules import Check, resolve_check, ScriptedRoller, TagBonus\n"
            "from evennia_rp_rules.ruleset import Ruleset\n"
            "from evennia_rp_rules.testing import TEST_RULESET\n"
            "rules = Ruleset.from_spec(TEST_RULESET)\n"
            "subject = {'brains': 'Mid'}\n"
            "from evennia_rp_rules.subjects import DictStatSource\n"
            "subject = DictStatSource(subject, modifiers=[TagBonus(2, tags=['riddles'], key='x')],"
            " ruleset=rules)\n"
            "check = Check('test', subject, 'brains', tags=['riddles'], difficulty='Mid')\n"
            "result = resolve_check(check, roller=ScriptedRoller([0]), ruleset=rules)\n"
            "print('RESULT', result.outcome.key, result.score('actor'))\n"
        )
        env = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            check=True,
            env=env,
            cwd=pathlib.Path(__file__).resolve().parents[2],
        )
        self.assertIn("RESULT good 12", result.stdout)


if __name__ == "__main__":
    unittest.main()
