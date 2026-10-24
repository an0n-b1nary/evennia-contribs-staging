# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Command migration contracts and pass boundaries under real partner rules."""

from copy import deepcopy
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from . import engine, services, tactics
from .commands import CmdAction, CmdCombat, CmdModifier, CmdPass, CmdTactics
from .data import CombatError
from .models import Fight
from .tests import build, declare, duel


@override_settings(RP_COMBAT_PARTNERS={})
class TestPass(SimpleTestCase):
    def test_pass_spends_an_action_and_recovers_only_pressure(self):
        state = duel()
        row = engine.participant(state, 1)
        flags = {
            "empower": True,
            "burst": True,
            "counter": "heavy",
            "callshot": True,
            "waive": True,
            "surge": "",
        }
        row.update(pressure=20, recovering=True, tempo=2, armed=flags.copy())
        resources = {key: row[key] for key in ("reserves", "spirit", "transcendence", "tempo")}
        engine.pass_action(state, 1)
        self.assertEqual(
            (row["turns"], row["clock"], row["pose"], row["recovering"]), (1, 1, True, False)
        )
        self.assertLess(row["pressure"], 20)
        self.assertEqual({key: row[key] for key in resources}, resources)
        self.assertFalse(state["exchanges"])
        self.assertEqual(row["armed"], flags)

    def test_auto_participant_passes_without_owing_a_pose(self):
        state = duel()
        row = engine.participant(state, 1)
        row.update(auto=True, recovering=True)
        engine.pass_action(state, 1)
        self.assertFalse(row["pose"])
        engine.pass_action(state, 1)
        self.assertEqual(row["clock"], 2)

    def test_pass_requires_clear_queues_and_pose(self):
        for kind in ("incoming", "outgoing", "pose"):
            state = duel()
            row = engine.participant(state, 1)
            row[kind] = ["pending"] if kind == "incoming" else True
            before = deepcopy(state)
            with self.assertRaises(CombatError):
                engine.pass_action(state, 1)
            self.assertEqual(state, before)

    def test_pass_ticks_poison_expires_stance_and_settles_incapacitation(self):
        state = duel()
        row = engine.participant(state, 1)
        row["hp"] = 2
        engine.condition(row, "poisoned", 3, 2)
        engine.condition(row, "resist_stance", 10, 1)
        engine.pass_action(state, 1)
        self.assertEqual(row["hp"], 0)
        self.assertTrue(row["return_required"])
        self.assertNotIn("resist_stance", row["conditions"])
        self.assertEqual(row["clock"], 1)

    def test_pass_preserves_flags_then_an_executed_action_consumes_them(self):
        state = duel()
        row = engine.participant(state, 1)
        row["armed"] = {"burst": True, "counter": "balanced"}
        engine.pass_action(state, 1)
        self.assertEqual(row["armed"], {"burst": True, "counter": "balanced"})
        row["pose"] = False
        token = declare(state, bet="subtle")
        self.assertTrue(engine.get_exchange(state, token)["burst"])
        engine.cancel(state, 2, token)
        self.assertEqual(row["armed"], {"burst": True, "counter": "balanced"})
        token = declare(state, bet="subtle")
        engine.reaction(state, 2, token, "resist")
        self.assertEqual(row["armed"], {"counter": "balanced"})

    def test_staggered_skip_adds_no_extra_clock_or_rewards(self):
        from .effects import stagger

        state = duel(boss=2)
        row = engine.participant(state, 1)
        engine.pass_action(state, 1)
        row["pose"] = False
        stagger(state, 1, 10, 2)
        engine.pass_action(state, 1)
        self.assertEqual((row["turns"], row["clock"], row["actions_spent"]), (2, 2, 2))
        self.assertEqual(row["reserves"], 3)

    def test_counter_and_empower_wait_through_ineligible_reaction(self):
        state = duel()
        defender = engine.participant(state, 2)
        defender.update(armed={"counter": "heavy", "empower": True}, transcendence=100)
        token = declare(state)
        engine.reaction(state, 2, token, "evade")
        self.assertEqual(defender["armed"], {"counter": "heavy", "empower": True})
        engine.participant(state, 1)["pose"] = False
        token = declare(state)
        engine.reaction(state, 2, token, "overpower")
        self.assertEqual(
            state["exchanges"][token.split(":")[0]]["reactions"]["2"]["counter"]["key"], "heavy"
        )
        self.assertEqual(defender["armed"], {})

    def test_pending_counter_is_reserved_for_one_packet(self):
        state = duel(boss=2)
        engine.join(state, 3, "Third", "two", build())
        engine.join(state, 4, "Fourth", "one", build())
        row = engine.participant(state, 2)
        row["armed"] = {"counter": "heavy"}
        first = declare(state, targets=(2, 3))
        engine.reaction(state, 2, first, "overpower")
        self.assertEqual(row["armed"], {"counter": "heavy"})
        second = declare(state, ident=4, targets=(2,))
        engine.reaction(state, 2, second, "overpower")
        other = state["exchanges"][second.split(":")[0]]["reactions"]["2"]
        self.assertEqual(other["counter"]["key"], "balanced")
        engine.reaction(state, 3, first, "resist")
        self.assertEqual(row["armed"], {})


@override_settings(
    RP_COMBAT_PARTNERS={},
    RP_COMBAT_REVEALED=True,
    RP_COMBAT_FROZEN=False,
    RP_COMBAT_TACTICS_REVEALED=True,
)
class TestCommandFlows(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char2.location = self.char1.location
        snapshot = patch("evennia_rp_combat.services.snapshot", return_value=build())
        snapshot.start()
        self.addCleanup(snapshot.stop)
        services.setup(self.char1)
        services.join(self.char1, "one")
        services.join(self.char2, "two")

    def test_old_actions_and_unknown_or_stacked_switches_are_refused(self):
        for text in ("/attack Char=balanced", "/recover", "/npc", "/act/npc", "/act/unknown"):
            self.call(CmdCombat(), text, "Use one known switch.")
        self.assertFalse(services.state_for(self.char1)["exchanges"])

    def test_unknown_target_reports_only_the_failed_search(self):
        output = self.call(CmdAction(), "Nobody=balanced", "Could not find 'Nobody'.")
        self.assertNotIn("Name at least one target", output)
        self.call(CmdAction(), "=balanced", "Name at least one target.")
        self.assertFalse(services.state_for(self.char1)["exchanges"])

    def test_unique_rps_prefix_declares_and_pass_is_a_separate_action(self):
        self.call(CmdAction(), "/p Char2=balanced", "1.1")
        state = services.state_for(self.char1)
        self.assertEqual(next(iter(state["exchanges"].values()))["bet"], "penetrating")
        services.control(self.char2, "cancel", argument="1.1:1")
        self.call(CmdPass(), "", "")
        self.assertEqual(
            services.state_for(self.char1)["participants"][str(self.char1.pk)]["clock"], 1
        )

    def test_arm_pass_disarm_persists_without_exchange_rewards(self):
        self.call(CmdModifier(), "", "Empower armed.")
        self.call(CmdPass(), "", "")
        row = services.state_for(self.char1)["participants"][str(self.char1.pk)]
        self.assertEqual(row["armed"], {"empower": True})
        self.assertEqual((row["reserves"], row["transcendence"]), (3, 0))
        self.call(CmdModifier(), "/off", "Empower disarmed.")
        self.assertEqual(
            services.state_for(self.char1)["participants"][str(self.char1.pk)]["armed"], {}
        )

    def test_tactics_set_use_delete_at_limit_preserves_committed_reactions(self):
        with override_settings(RP_COMBAT_TACTICS_LIMIT=2):
            first = tactics.save(self.char1, "First", appetite="cautious")
            self.call(CmdTactics(), "/set Second/rps_appetite=bold", "Tactics saved.")
            self.assertEqual(tactics.profile(self.char1)["appetite"], "cautious")
            services.join(self.obj1, "one")
            services.execute(
                self.char2,
                "fixture multi-target allowance",
                lambda state: engine.participant(state, self.char2.pk).update(
                    allowance=2, actions_left=2
                ),
            )
            token = services.declare(self.char2, [self.char1, self.obj1])
            services.react(self.char1, f"{token}:1", "overpower", counter="heavy")
            before = services.state_for(self.char1)
            self.call(CmdTactics(), "/use Second", "Active Tactics: Second.")
            self.assertEqual(services.state_for(self.char1), before)
            with self.assertRaisesRegex(CombatError, "full"):
                tactics.save(self.char1, "Third", select=False)
            tactics.delete(self.char1, "First")
            self.assertEqual(tactics.profile(self.char1)["rps_appetite"], "bold")
            tactics.save(self.char1, "Third", select=False)
            tactics.delete(self.char1, "Second")
            self.assertEqual(tactics.profile(self.char1), {})
            self.assertFalse(
                services.state_for(self.char1)["participants"][str(self.char1.pk)]["auto"]
            )
            self.assertIsNotNone(first.pk)
            self.assertEqual(services.state_for(self.char1), before)
            services.react(self.obj1, f"{token}:1", "resist")
            committed = services.state_for(self.char1)["exchanges"][token]["reactions"][
                str(self.char1.pk)
            ]
            self.assertEqual(committed["counter"]["key"], "heavy")

    def test_join_cap_is_set_in_a_separate_step_and_cannot_increase_after_join(self):
        services.prepare_cap(self.obj1, 8)
        services.join(self.obj1, "one", boss=2)
        row = engine.participant(services.state_for(self.obj1), self.obj1.pk)
        self.assertEqual((row["turn_limit"], row["allowance"]), (8, 2))
        services.prepare_cap(self.obj1, 6)
        with self.assertRaises(CombatError):
            services.prepare_cap(self.obj1, 7)

    def test_tactics_fields_reject_objects_and_invalid_weights(self):
        for field, value in (
            ("action_weights", '{"standard":100}'),
            ("preferred_moves", '["heavy"]'),
            ("action_weights", "standard/0"),
            ("action_weights", "standard/50,standard/50"),
        ):
            with self.assertRaises((CombatError, ValueError)):
                tactics.set_field(self.char1, "Bad", field, value)
        self.assertEqual(tactics.profile(self.char1), {})

    def test_mine_discovers_faded_and_shelved_across_rooms_only_for_members(self):
        fight = services.open_fight(self.char1.location)
        services.control(self.char1, "fade")
        self.char1.location = self.room2
        self.assertIn(f"#{fight.pk}: open; faded;", services.mine(self.char1))
        self.assertNotIn(f"#{fight.pk}:", services.mine(self.obj1))
        fight.status = Fight.SHELVED
        fight.save(update_fields=["status"])
        self.assertIn(f"#{fight.pk}: shelved;", services.mine(self.char1))
        fight.state["participants"][str(self.char1.pk)]["status"] = "withdrawn"
        fight.save(update_fields=["state"])
        self.assertNotIn(f"#{fight.pk}:", services.mine(self.char1))
        fight.status = Fight.ENDED
        fight.save(update_fields=["status"])
        self.assertNotIn(f"#{fight.pk}:", services.mine(self.char1))

    def test_correction_is_explicit_private_and_cannot_bypass_pending_exchanges(self):
        from django.apps import apps

        if not apps.is_installed("evennia_rp_chargen"):
            self.skipTest("optional chargen partner absent")
        from evennia_rp_chargen import guards, locks
        from evennia_rp_chargen.services import ChargenError

        services.declare(self.char1, [self.char2])
        with self.assertRaisesRegex(CombatError, "pending"):
            services.control(self.char1, "unlock")
        services.control(self.char2, "cancel", argument="1.1:1")
        with self.assertRaises(ChargenError):
            locks.unlock(self.char1)
        services.control(self.char1, "unlock", reason="secret arsenal")
        self.assertFalse(locks.scope_locked(self.char1, "pips"))
        self.assertFalse(locks.scope_locked(self.char1, "loadout"))
        locks.note_ic_action(self.char1)
        self.assertFalse(locks.scope_locked(self.char1, "loadout"))
        services.control(self.char1, "relock", reason="secret arsenal")
        self.assertNotIn("secret arsenal", services.journal(self.char1))
        for kind in (
            guards.RATING,
            guards.EQUIP,
            guards.UNEQUIP,
            guards.SIGNATURE,
            guards.TAKE_FLAW,
        ):
            self.assertTrue(guards.refusals(guards.BuildChange(self.char1, kind)))
