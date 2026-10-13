# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Encounter effects must obey real combat clocks and damage accounting."""

from copy import deepcopy

from django.test import SimpleTestCase, override_settings

from . import effects, engine
from .data import Build, CombatError, Move
from .state import upgrade


@override_settings(RP_COMBAT_PARTNERS={})
class TestEncounterEffects(SimpleTestCase):
    def setUp(self):
        self.state = engine.new_state()
        build = Build(
            tuple(
                (name, "0")
                for name in (
                    "attack",
                    "attack_defense",
                    "spell",
                    "spell_defense",
                    "dispirit",
                    "will",
                    "agility",
                )
            )
        )
        engine.join(self.state, 1, "Boss", "boss", build, boss=3)
        engine.join(self.state, 2, "Hero", "heroes", build)

    def attack(self, actor=1):
        target = 2 if actor == 1 else 1
        self.state["participants"][str(actor)]["pose"] = False
        ident = engine.declaration(self.state, actor, [target], Move(), 100)
        engine.reaction(self.state, target, f"{ident}:1", "resist")

    def test_full_skip_at_boundary_no_exchange_rewards_or_clock_tick(self):
        before = deepcopy(self.state["participants"]["1"])
        effects.stagger(self.state, 1, 30, "test")
        row = self.state["participants"]["1"]
        self.assertEqual((row["turns"], row["actions_left"]), (1, 3))
        for name in ("clock", "reserves", "spirit", "transcendence", "actions_spent", "tempo"):
            self.assertEqual(row[name], before[name])
        self.assertFalse(effects.stagger(self.state, 1, 50, "another"))
        self.assertEqual(engine.value(row, "staggered"), 30)
        ident = engine.declaration(self.state, 1, [2], Move(), 100)
        engine.cancel(self.state, 2, f"{ident}:1")
        self.assertEqual(engine.value(row, "staggered"), 30)
        self.attack()
        self.assertIsNone(row["turn_skip"])
        self.assertEqual(engine.value(row, "staggered"), 0)

    def test_partial_remainder_finishes_then_next_whole_turn_skipped(self):
        self.attack()
        row = self.state["participants"]["1"]
        self.assertEqual(row["actions_left"], 2)
        effects.stagger(self.state, 1, 30, "test")
        self.attack()
        self.assertTrue(row["turn_skip"]["pending"])
        self.assertEqual(engine.value(row, "staggered"), 30)
        self.attack()
        self.assertEqual((row["turns"], row["actions_left"]), (2, 3))
        self.assertEqual(row["actions_spent"], 3)
        self.assertEqual(row["clock"], 3)
        self.assertFalse(row["turn_skip"]["pending"])

    def test_penalty_all_reaction_previews(self):
        ident = engine.declaration(self.state, 2, [1], Move(), 100)
        baseline = engine.reaction_view(self.state, 1, f"{ident}:1")
        engine.cancel(self.state, 1, f"{ident}:1")
        effects.stagger(self.state, 1, 30, "test")
        ident = engine.declaration(self.state, 2, [1], Move(), 100)
        changed = engine.reaction_view(self.state, 1, f"{ident}:1")
        for reaction in ("evade", "resist", "overpower"):
            # All three chances are shown by the same real policy view.
            self.assertEqual(
                int(dict(changed.penalties)[reaction]), int(dict(baseline.penalties)[reaction]) + 30
            )

    def test_final_cap_skip_leaves_reaction_opening_until_end(self):
        row = self.state["participants"]["1"]
        row["turns"] = row["turn_limit"] - 1
        effects.stagger(self.state, 1, 30, "final")
        self.assertEqual(row["turns"], row["turn_limit"])
        with self.assertRaises(CombatError):
            engine.declaration(self.state, 1, [2], Move(), 100)
        self.attack(actor=2)
        self.assertEqual(engine.value(row, "staggered"), 30)
        self.assertEqual(row["actions_spent"], 0)

    def test_recovery_executes_and_consumes_pending_whole_turn_skip(self):
        self.attack()
        row = self.state["participants"]["1"]
        effects.stagger(self.state, 1, 30, "recovery")
        row["recovering"] = True
        row["pose"] = False
        engine.recover(self.state, 1)
        self.assertTrue(row["turn_skip"]["pending"])
        self.assertEqual(row["actions_spent"], 2)
        self.attack()
        self.assertEqual(row["turns"], 2)
        row["recovering"] = True
        row["pose"] = False
        engine.recover(self.state, 1)
        self.assertIsNone(row["turn_skip"])

    def test_damage_and_resist_effects_are_idempotent_and_zero_targets_ineligible(self):
        effects.damage(self.state, 1, 2, 10, "wave")
        before = deepcopy(self.state)
        self.assertEqual(effects.damage(self.state, 1, 2, 10, "wave"), 10)
        self.assertEqual(self.state, before)
        with self.assertRaises(CombatError):
            effects.damage(self.state, 1, 2, 11, "wave")
        effects.resist(self.state, 1, 2, 35, 1, "tank")
        before = deepcopy(self.state)
        effects.resist(self.state, 1, 2, 35, 1, "tank")
        self.assertEqual(self.state, before)
        self.state["participants"]["2"]["hp"] = 0
        self.assertEqual(effects.damage(self.state, 1, 2, 50, "failure"), 0)

    def test_populated_schema_upgrade_keeps_builds_and_resources(self):
        old = deepcopy(self.state)
        old["schema"] = 3
        old.pop("effect_results")
        for row in old["participants"].values():
            row.pop("turn_skip")
            row.pop("partner_subjects")
            row.pop("actions_spent")
        before = deepcopy(old)
        upgraded = upgrade(old)
        self.assertEqual(old, before)
        self.assertEqual(upgraded["schema"], 4)
        self.assertEqual(upgraded["participants"]["1"]["build"], old["participants"]["1"]["build"])
        self.assertEqual(upgrade(upgraded), upgraded)
