# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Shared resource accounting against the real combat resolver and coordinator."""

from copy import deepcopy
from fractions import Fraction as F
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from evennia.utils.test_resources import EvenniaCommandTest
from evennia_rp_combat import engine, partners
from evennia_rp_combat import services as combat
from evennia_rp_combat.commands import CmdAction, CmdSurge
from evennia_rp_combat.data import CombatError, Move
from evennia_rp_combat.improv_commands import CmdImprov

from . import checks, rules, services, synergy
from .tests import REGISTRY, build, declare, teams


def request(target=4):
    return {"party": {"kind": "surge", "target": str(target)}}


def fund(state, key, amount=200):
    rules.party(state, key)["synergy"] = str(amount)


def changed(state):
    partners.emit(state, partners.Event("state_changed", "", "", 0))


@override_settings(RP_COMBAT_PARTNERS=REGISTRY)
class TestSynergy(SimpleTestCase):
    def test_upgrade_starts_old_parties_at_zero_without_replaying_earning(self):
        state, first, _second = teams()
        token = declare(state)
        engine.reaction(state, 4, token, "resist")
        old = deepcopy(state["partners"]["party"])
        old["schema"] = 1
        old["data"].pop("surges")
        old["data"].pop("synergy_awards")
        for row in old["data"]["parties"].values():
            row.pop("synergy")
        before = deepcopy(old)
        upgraded = rules.upgrade(old)
        self.assertEqual(old, before)
        self.assertEqual(upgraded["schema"], 3)
        self.assertEqual(upgraded["data"]["parties"][first]["synergy"], "0")
        self.assertEqual(rules.upgrade(upgraded), upgraded)

    def test_exact_hostile_damage_action_and_empower_awards_never_repeat(self):
        state, first, second = teams()
        state["participants"]["1"]["transcendence"] = 100
        token = declare(state, empower=True)
        exchange = engine.get_exchange(state, token)
        self.assertEqual(synergy.pool(state, first), 0)
        engine.reaction(state, 4, token, "resist")
        self.assertEqual(synergy.pool(state, first), 50)
        damage = exchange["outcomes"][0]["damage"]
        self.assertEqual(synergy.pool(state, second), F(damage, 4))
        partners.emit(
            state,
            partners.Event(
                "packet",
                "1",
                exchange["id"],
                1,
                "4",
                damage=damage,
                empowered=True,
                target_was_participating=True,
            ),
        )
        partners.emit(state, partners.Event("exchange_end", "1", exchange["id"], 1))
        self.assertEqual(synergy.pool(state, first), 50)
        self.assertEqual(synergy.pool(state, second), F(damage, 4))

    def test_completed_support_and_failed_dispirit_earn_but_cancellation_does_not(self):
        state, first, _second = teams()
        token = declare(state)
        engine.cancel(state, 4, token)
        self.assertEqual(synergy.pool(state, first), 0)
        declare(state, move=Move(action="dispirit"), roll=100)
        self.assertEqual(synergy.pool(state, first), 10)
        state["participants"]["1"]["pose"] = False
        declare(state, target=2, move=Move(action="assist"))
        self.assertEqual(synergy.pool(state, first), 20)

    def test_cap_counts_at_most_five_and_freezes_wholly_unavailable(self):
        state, first, _second = teams()
        for ident in range(7, 12):
            engine.join(state, ident, f"Ally {ident}", "one", build())
            rules.join(state, ident, first)
        fund(state, first, 500)
        self.assertEqual(synergy.cap(state, first), 500)
        for ident in rules.roster(state, first):
            engine.fade(state, ident)
        changed(state)
        self.assertEqual(synergy.pool(state, first), 500)
        self.assertEqual(synergy.available(state, first), 0)
        engine.join(state, 1, "Ignored", "one", build())
        changed(state)
        self.assertEqual(synergy.pool(state, first), 100)
        self.assertIn("clamped", " ".join(state["notices"]))
        rules.leave(state, 1)
        changed(state)
        self.assertEqual(synergy.pool(state, first), 100)
        other = rules.create(state, 1, "New team")
        self.assertEqual(synergy.pool(state, other), 0)

    def test_defeating_hit_awards_once_with_pre_damage_eligibility(self):
        state, _first, second = teams()
        for ident in (5, 6):
            engine.fade(state, ident)
        victim = state["participants"]["4"]
        victim["hp"] = 3
        token = declare(state)
        engine.reaction(state, 4, token, "resist")
        self.assertEqual(victim["hp"], 0)
        self.assertEqual(synergy.pool(state, second), F(3, 4))
        self.assertEqual(synergy.available(state, second), 0)

    def test_counter_damage_rewards_actual_victim_not_reaction_acceptance(self):
        state, first, second = teams()
        token = declare(state, roll=1)
        engine.reaction(state, 4, token, "overpower")
        outcome = state["exchanges"][token.split(":")[0]]["outcomes"][0]
        self.assertEqual(synergy.pool(state, first), 10 + F(outcome["counter_damage"], 4))
        self.assertEqual(synergy.pool(state, second), F(outcome["damage"], 4))

    def test_poison_earns_only_attributed_hostile_loss_not_recovery_or_self_costs(self):
        for source, recovery in (("4", False), ("1", False), ("", False), ("4", True)):
            state, first, _second = teams()
            actor = state["participants"]["1"]
            engine.condition(actor, "poisoned", 3, 2, source)
            if recovery:
                actor["recovering"] = True
                engine.pass_action(state, 1)
            else:
                token = declare(state, move=Move(kind="improvised", power=1, effects=("strain",)))
                engine.reaction(state, 4, token, "resist")
            self.assertEqual(
                synergy.pool(state, first), 0 if recovery else F(43, 4) if source == "4" else 10
            )

    def test_one_target_damage_boost_adds_to_party_boost_and_empower_tiers(self):
        state, first, _second = teams()
        for ident in (1, 2, 3):
            state["participants"][str(ident)]["spirit"] = 1000
        fund(state, first)
        state["participants"]["1"]["transcendence"] = 100
        baseline = deepcopy(state)
        token = declare(state, empower=True, partner_requests=request())
        original = declare(baseline, empower=True)
        modifiers = partners.modifiers(state["exchanges"][token.split(":")[0]], 4)
        self.assertEqual((modifiers.damage_boost, modifiers.surge), ("10", "25"))
        engine.reaction(state, 4, token, "resist")
        engine.reaction(baseline, 4, original, "resist")
        boosted = state["exchanges"][token.split(":")[0]]["outcomes"][0]["damage"]
        ordinary = baseline["exchanges"][original.split(":")[0]]["outcomes"][0]["damage"]
        self.assertGreater(boosted, ordinary)
        self.assertEqual(synergy.pool(state, first), 150)
        self.assertEqual(state["participants"]["1"]["clock"], 1)

    def test_support_stacking_primary_heal_encore_riders_and_dispirit(self):
        performer = build(abilities=(("proficiency", "performance", 1),))
        state, first, _second = teams(builds={1: performer})
        fund(state, first)
        state["participants"]["1"]["transcendence"] = 100
        for ident in (1, 2, 3):
            state["participants"][str(ident)]["hp"] = 50
        declare(
            state,
            target=2,
            move=Move(action="assist", kind="improvised", effects=("heal",)),
            empower=True,
            domain="performance",
            domain_effects={"performance": "encore"},
            partner_requests=request(2),
        )
        self.assertEqual(
            [state["participants"][str(i)]["spirit"] for i in (1, 2, 3)], [375, 438, 375]
        )
        self.assertEqual([state["participants"][str(i)]["hp"] for i in (1, 2, 3)], [50, 76, 50])
        self.assertEqual(rules.data(state)["support"]["1"]["points"], "5")
        state, first, _second = teams()
        fund(state, first)
        state["participants"]["1"]["transcendence"] = 100
        declare(
            state, move=Move(action="dispirit"), roll=1, empower=True, partner_requests=request()
        )
        self.assertEqual(state["participants"]["4"]["spirit"], -1000)  # ordinary cap, output -1050
        self.assertEqual(rules.data(state)["support"]["1"]["points"], "5")

    def test_reservations_prevent_two_spenders_and_failed_spend_is_atomic(self):
        state, first, _second = teams()
        fund(state, first, 100)
        token = declare(state, partner_requests=request())
        self.assertEqual((synergy.available(state, first), synergy.held(state, first)), (0, 100))
        before = deepcopy(state)
        with self.assertRaisesRegex(CombatError, "available Synergy"):
            declare(state, actor=2, target=5, partner_requests=request(5))
        self.assertEqual(state, before)
        engine.cancel(state, 4, token)
        self.assertEqual((synergy.pool(state, first), synergy.held(state, first)), (100, 0))
        declare(state, actor=2, target=5, partner_requests=request(5))

    def test_miss_spends_and_boss_personal_turn_marker_survives_party_hopping(self):
        state, first, _second = teams(boss=3)
        fund(state, first, 300)
        token = declare(state, roll=1, partner_requests=request())
        engine.reaction(state, 4, token, "evade")
        actor = state["participants"]["1"]
        self.assertEqual((actor["turns"], actor["actions_left"]), (0, 2))
        self.assertEqual(synergy.pool(state, first), 210)
        actor["pose"] = False
        rules.leave(state, 1)
        other = rules.create(state, 1, "Elsewhere")
        fund(state, other, 100)
        engine.fade(state, 1)
        engine.join(state, 1, "Ignored", "one", build())
        with self.assertRaisesRegex(CombatError, "this personal turn"):
            declare(state, partner_requests=request())
        for _ in range(2):
            token = declare(state)
            engine.reaction(state, 4, token, "resist")
            state["participants"]["1"]["pose"] = False
        self.assertEqual(state["participants"]["1"]["turns"], 1)
        declare(state, partner_requests=request())

    def test_multitarget_refunds_only_selected_packet_and_releases_its_marker(self):
        for canceled in (4, 5):
            state, first, _second = teams(boss=3)
            fund(state, first, 200)
            ex = engine.declaration(state, 1, (4, 5, 6), Move(), 100, partner_requests=request(5))
            self.assertEqual(
                [partners.modifiers(state["exchanges"][ex], i).surge for i in (4, 5, 6)],
                ["0", "25", "0"],
            )
            engine.reaction(state, 6, f"{ex}:1", "resist")
            engine.cancel(state, canceled, f"{ex}:1")
            engine.reaction(state, 5 if canceled == 4 else 4, f"{ex}:1", "resist")
            row = rules.data(state)["surges"][f"{ex}:1"]
            self.assertEqual(row["status"], "refunded" if canceled == 5 else "executed")
            self.assertEqual(synergy.pool(state, first), 210 if canceled == 5 else 110)
            state["participants"]["1"]["pose"] = False
            if canceled == 5:
                declare(state, partner_requests=request())
            else:
                with self.assertRaisesRegex(CombatError, "this personal turn"):
                    declare(state, partner_requests=request())

    def test_burst_one_hit_surge_and_one_action_empower_award_with_real_passives(self):
        from .tests import TestCombatAbilities

        specialist = TestCombatAbilities().ruled(
            {"rule": "measured_tempo", "amount": "1/4", "cap": 2},
            {"rule": "explosive", "factor": "1/2"},
        )
        state, first, _second = teams(builds={1: specialist})
        fund(state, first, 200)
        state["participants"]["1"].update(spirit=1000, transcendence=100, tempo=2)
        token = declare(state, burst=True, empower=True)
        ex = token.split(":")[0]
        engine.reaction(state, 4, token, "resist")
        self.assertEqual(synergy.pool(state, first), 240)
        state["participants"]["1"]["transcendence"] = 100
        engine.press(state, 1, 100, empower=True, partner_requests=request())
        self.assertEqual(partners.modifiers(state["exchanges"][ex], 4).surge, "25")
        self.assertEqual(engine.value(state["participants"]["1"], "overextended"), 3)
        engine.reaction(state, 4, f"{ex}:2", "resist")
        engine.press(state, 1, 100)
        self.assertEqual(partners.modifiers(state["exchanges"][ex], 4).surge, "0")
        engine.reaction(state, 4, f"{ex}:3", "resist")
        self.assertEqual(synergy.pool(state, first), 150)
        self.assertEqual(state["participants"]["1"]["clock"], 1)

    def test_pressed_packet_cancel_refunds_even_after_executed_opener(self):
        state, first, _second = teams()
        fund(state, first, 200)
        token = declare(state, burst=True)
        ex = token.split(":")[0]
        engine.reaction(state, 4, token, "resist")
        engine.press(state, 1, 100, partner_requests=request())
        engine.cancel(state, 4, f"{ex}:2")
        self.assertEqual(synergy.pool(state, first), 210)
        self.assertEqual(rules.data(state)["surges"][f"{ex}:2"]["status"], "refunded")

    def test_cover_keeps_surge_and_damage_award_follows_actual_coverer_party(self):
        state, first, second = teams()
        fund(state, first)
        rules.formation(state, 4, "back", cover=True)
        rules.formation(state, 5, "front")
        token = declare(state, burst=True, partner_requests=request())
        engine.redirect(state, token, 4, 5, "resist")
        ex = state["exchanges"][token.split(":")[0]]
        self.assertEqual(partners.modifiers(ex, 5).surge, "25")
        self.assertEqual(rules.data(state)["surges"][token]["status"], "executed")
        self.assertEqual(synergy.pool(state, second), F(ex["outcomes"][0]["damage"], 4))
        engine.press(state, 1, 100)
        self.assertEqual(partners.modifiers(ex, 5).surge, "0")

    def test_revival_decline_refunds_accept_heals_and_recovery_never_earns(self):
        for accept in (False, True):
            state, first, _second = teams()
            fund(state, first)
            state["participants"]["2"].update(hp=0, return_required=True)
            token = declare(
                state,
                target=2,
                move=Move(action="assist", kind="improvised", effects=("heal",)),
                partner_requests=request(2),
            )
            self.assertEqual(synergy.pool(state, first), 100)
            if accept:
                engine.accept_revival(state, 2, token)
                self.assertEqual(state["participants"]["2"]["hp"], 19)
                self.assertEqual(synergy.pool(state, first), 110)
                engine.pass_action(state, 2)
                self.assertEqual(synergy.pool(state, first), 110)
            else:
                engine.cancel(state, 2, token)
                self.assertEqual(synergy.pool(state, first), 200)
            self.assertEqual(state["participants"]["2"]["turns"], int(accept))

    def test_uninstall_execution_and_cancel_settle_without_retroactive_awards(self):
        for canceled in (False, True):
            state, first, _second = teams(boss=3)
            fund(state, first, 200)
            token = declare(state, partner_requests=request())
            retained = deepcopy(state["partners"]["party"])
            with override_settings(RP_COMBAT_PARTNERS={}):
                if canceled:
                    engine.cancel(state, 4, token)
                else:
                    self.assertEqual(
                        partners.modifiers(state["exchanges"][token.split(":")[0]], 4).surge, "0"
                    )
                    engine.reaction(state, 4, token, "resist")
                self.assertEqual(state["partners"]["party"], retained)
            changed(state)
            self.assertEqual(synergy.pool(state, first), 200 if canceled else 100)
            state["participants"]["1"]["pose"] = False
            if canceled:
                declare(state, partner_requests=request())
            else:
                with self.assertRaisesRegex(CombatError, "this personal turn"):
                    declare(state, partner_requests=request())

    def test_invalid_configuration_is_a_system_check_error(self):
        for name, value in (
            ("RP_PARTY_DAMAGE_SYNERGY", 0.25),
            ("RP_PARTY_SURGE_COST", "0"),
            ("RP_PARTY_SURGE_POINTS", "101"),
        ):
            with override_settings(**{name: value}):
                self.assertEqual(
                    [error.id for error in checks.check_configuration()], ["rp_party.E001"]
                )

    def test_dissolution_discards_balance_but_keeps_fight_wide_use_marker(self):
        state, first, _second = teams(boss=3)
        fund(state, first, 200)
        token = declare(state, partner_requests=request())
        engine.reaction(state, 4, token, "resist")
        state["participants"]["1"]["pose"] = False
        for ident in (2, 3):
            engine.fade(state, ident)
        self.assertEqual(rules.dissolve(state, 1, first), "dissolved")
        self.assertEqual(rules.data(state)["parties"][first]["synergy"], "0")
        new = rules.create(state, 1, "New identity")
        fund(state, new, 100)
        with self.assertRaisesRegex(CombatError, "this personal turn"):
            declare(state, partner_requests=request())

    def test_cap_shrink_honors_reservations_and_cancellation_never_overfills(self):
        state, first, _second = teams()
        fund(state, first, 300)
        token = declare(state, partner_requests=request())
        engine.fade(state, 2)
        engine.fade(state, 3)
        changed(state)
        self.assertEqual((synergy.pool(state, first), synergy.held(state, first)), (0, 100))
        engine.cancel(state, 4, token)
        self.assertEqual((synergy.pool(state, first), synergy.held(state, first)), (100, 0))

    def test_status_projects_absent_refund_without_writing_its_input(self):
        from . import providers

        state, first, _second = teams()
        fund(state, first, 100)
        token = declare(state, partner_requests=request())
        with override_settings(RP_COMBAT_PARTNERS={}):
            engine.cancel(state, 4, token)
        before = deepcopy(state)
        self.assertIn("Synergy 100 available, 0 reserved", " ".join(providers.status(state, "1")))
        self.assertEqual(state, before)

    def test_unexecuted_packet_regains_frozen_surge_after_reinstall(self):
        state, first, _second = teams()
        fund(state, first, 100)
        token = declare(state, partner_requests=request())
        retained = deepcopy(state["partners"]["party"])
        with override_settings(RP_COMBAT_PARTNERS={}):
            changed(state)
            self.assertEqual(partners.modifiers(engine.get_exchange(state, token), 4).surge, "0")
            self.assertEqual(state["partners"]["party"], retained)
        self.assertEqual(partners.modifiers(engine.get_exchange(state, token), 4).surge, "25")
        self.assertEqual(synergy.held(state, first), 100)
        engine.reaction(state, 4, token, "resist")
        self.assertEqual(rules.data(state)["surges"][token]["status"], "executed")
        self.assertEqual(synergy.pool(state, first), 10)

    def test_recovery_cap_and_unaffordable_pressed_hit_cannot_spend(self):
        state, first, _second = teams()
        fund(state, first, 100)
        for change in ({"recovering": True}, {"turns": 4}):
            candidate = deepcopy(state)
            candidate["participants"]["1"].update(change)
            before = deepcopy(candidate)
            with self.assertRaises(CombatError):
                declare(candidate, partner_requests=request())
            self.assertEqual(candidate, before)
        token = declare(state, burst=True, move=Move(kind="improvised", power=1))
        engine.reaction(state, 4, token, "resist")
        state["participants"]["1"]["reserves"] = 0
        before = deepcopy(state)
        with self.assertRaisesRegex(CombatError, "cannot be afforded"):
            engine.press(state, 1, 100, partner_requests=request())
        self.assertEqual(state, before)

    def test_earned_healing_can_fund_only_actual_further_hostile_loss(self):
        state, first, _second = teams(boss=3)
        healing = Move(action="assist", kind="improvised", effects=("heal",))
        damage = 0
        restored = 0
        for _ in range(3):
            state["participants"]["4"]["pose"] = False
            token = declare(state, actor=4, target=2)
            engine.reaction(state, 2, token, "resist")
            damage += state["exchanges"][token.split(":")[0]]["outcomes"][0]["damage"]
            state["participants"]["1"]["pose"] = False
            token = declare(state, actor=1, target=2, move=healing)
            restored += state["exchanges"][token.split(":")[0]]["outcomes"][0]["healing"]
            state["participants"]["1"]["pose"] = False
            token = declare(state)
            engine.reaction(state, 4, token, "resist")  # Earn Reserves for the next Heal.
        self.assertGreater(restored, 0)
        self.assertEqual(synergy.pool(state, first), 60 + F(damage, 4))
        before = synergy.pool(state, first)
        state["participants"]["2"]["hp"] = 100  # OOC correction, not hostile damage
        changed(state)
        self.assertEqual(synergy.pool(state, first), before)


@override_settings(RP_COMBAT_PARTNERS=REGISTRY, RP_COMBAT_REVEALED=True, RP_PARTY_REVEALED=True)
class TestSynergyCoordinator(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char2.location = self.char1.location
        source = patch("evennia_rp_combat.services.snapshot", return_value=build())
        source.start()
        self.addCleanup(source.stop)
        combat.setup(self.char1)
        combat.join(self.char1, "one")
        combat.join(self.char2, "two")
        self.key = services.change(self.char1, "create", "Surge team")
        combat.execute(self.char1, "fixture balance", lambda state: fund(state, self.key, 100))

    def test_commands_reserve_refund_retry_and_public_journal_announcements(self):
        self.call(CmdSurge(), "", "Surge armed.")
        self.call(CmdAction(), f"{self.char2.key}=balanced", "1.1")
        fight = combat.open_fight(self.char1.location)
        entry = fight.entries.latest("sequence")
        self.assertIn("reserved 100 Synergy", entry.summary)
        self.assertNotIn("notices", fight.state)
        combat.control(self.char2, "cancel", argument="1.1:1")
        fight.refresh_from_db()
        self.assertIn("refunded 100", fight.entries.latest("sequence").summary)
        ex = services.surge(self.char1, [self.char2], operation_id="surge-retry")
        before = combat.state_for(self.char1)
        self.assertEqual(services.surge(self.char1, [self.char2], operation_id="surge-retry"), ex)
        self.assertEqual(combat.state_for(self.char1), before)
        combat.control(self.char2, "cancel", argument=f"{ex}:1")
        self.char1.permissions.add("Builder")
        sequence = fight.entries.get(operation="surge-retry").sequence
        combat.rollback(self.char1, sequence, "restore before reservation")
        state = combat.state_for(self.char1)
        self.assertEqual(synergy.pool(state, self.key), 100)
        with self.assertRaisesRegex(CombatError, "superseded"):
            services.surge(self.char1, [self.char2], operation_id="surge-retry")

    def test_frozen_pause_other_pc_and_auto_act_do_not_spend(self):
        before = combat.state_for(self.char1)
        for settings in ({"RP_PARTY_FROZEN": True}, {"RP_PARTY_REVEALED": False}):
            with override_settings(**settings), self.assertRaises(CombatError):
                services.surge(self.char1, [self.char2])
            self.assertEqual(combat.state_for(self.char1), before)
        with self.assertRaises(CombatError):
            services.surge(self.char1, [self.char2], subject=self.char2)
        combat.auto_act(self.char1)
        state = combat.state_for(self.char1)
        self.assertFalse(rules.data(state)["surges"])
        self.assertEqual(synergy.pool(state, self.key), 100)
        # Auto-Act picks at random; a Dispirit resolves with nothing incoming.
        for token in state["participants"][str(self.char2.pk)]["incoming"]:
            combat.control(self.char2, "cancel", argument=token)
        combat.storyteller(self.char1, "pause")
        with self.assertRaisesRegex(CombatError, "paused"):
            services.surge(self.char1, [self.char2])

    def test_armed_surge_cannot_bypass_later_freeze_or_reveal_changes(self):
        combat.arm(self.char1, "surge", "")
        before = combat.state_for(self.char1)
        for settings in ({"RP_PARTY_FROZEN": True}, {"RP_PARTY_REVEALED": False}):
            with override_settings(**settings), self.assertRaises(CombatError):
                combat.declare(self.char1, [self.char2])
            self.assertEqual(combat.state_for(self.char1), before)
        with override_settings(RP_PARTY_FROZEN=True):
            combat.arm(self.char1, "surge", off=True)
        self.assertEqual(
            engine.participant(combat.state_for(self.char1), self.char1.pk)["armed"], {}
        )

    def test_shelving_cancels_pending_surge_and_retains_refund_for_rejoin(self):
        ex = services.surge(self.char1, [self.char2])
        fight = combat.open_fight(self.char1.location)
        combat.shelve(self.char1, "continue later")
        fight.refresh_from_db()
        state = combat.load(fight)
        self.assertEqual(synergy.pool(state, self.key), 100)
        self.assertEqual(synergy.held(state, self.key), 0)
        self.assertEqual(rules.data(state)["surges"][f"{ex}:1"]["status"], "refunded")
        combat.unshelve(self.char1, fight.pk)
        combat.join(self.char1, "one")
        combat.join(self.char2, "two")
        combat.storyteller(self.char1, "resume", reason="ready after rejoining")
        services.surge(self.char1, [self.char2])

    def test_improvised_draft_and_armed_surge_reserve_in_one_transaction(self):
        for args in ("/new Improvised", "/wording First, then", "/finish"):
            self.call(CmdImprov(), args, "Improvised")
        self.call(CmdSurge(), "", "Surge armed.")
        self.call(CmdImprov(), f"/subtle {self.char2.key}", "1.1")
        state = combat.state_for(self.char1)
        exchange = state["exchanges"]["1.1"]
        self.assertEqual(exchange["move"]["wording"], "First, then")
        self.assertEqual(exchange["bet"], "subtle")
        self.assertEqual(partners.modifiers(exchange, self.char2.pk).surge, "25")
        self.assertEqual(synergy.held(state, self.key), 100)

    def test_armed_surge_survives_pass_cancel_and_spends_on_resolution(self):
        combat.arm(self.char1, "surge", "")
        combat.control(self.char1, "pass")
        state = combat.state_for(self.char1)
        self.assertEqual(synergy.pool(state, self.key), 100)
        self.assertEqual(engine.participant(state, self.char1.pk)["armed"], {"surge": ""})
        combat.control(self.char1, "posed")
        ex = combat.declare(self.char1, [self.char2])
        combat.control(self.char2, "cancel", argument=f"{ex}:1")
        state = combat.state_for(self.char1)
        self.assertEqual(synergy.pool(state, self.key), 100)
        self.assertEqual(engine.participant(state, self.char1.pk)["armed"], {"surge": ""})
        ex = combat.declare(self.char1, [self.char2])
        combat.react(self.char2, f"{ex}:1", "resist")
        state = combat.state_for(self.char1)
        self.assertEqual(engine.participant(state, self.char1.pk)["armed"], {})
        self.assertEqual(synergy.pool(state, self.key), 10)

    def test_populated_schema_one_upgrade_preserves_builds_and_old_checkpoint(self):
        fight = combat.open_fight(self.char1.location)
        legacy = deepcopy(fight.state)
        section = legacy["partners"]["party"]
        section["schema"] = 1
        for field in ("surges", "synergy_awards"):
            section["data"].pop(field)
        for row in section["data"]["parties"].values():
            row.pop("synergy")
        fight.state = legacy
        fight.save(update_fields=["state"])
        hashes = list(fight.builds.values_list("digest", flat=True))
        state = combat.load(fight)
        self.assertEqual(state["partners"]["party"]["schema"], 3)
        self.assertEqual(synergy.pool(state, self.key), 0)
        self.assertEqual(fight.state, legacy)
        combat.execute(self.char1, "upgrade fixture checkpoint", lambda state: None)
        entry = fight.entries.latest("sequence")
        checkpoint = deepcopy(entry.before)
        services.change(self.char1, "formation", "front")
        self.char1.permissions.add("Builder")
        combat.rollback(self.char1, entry.sequence, "restore upgraded checkpoint")
        entry.refresh_from_db()
        self.assertEqual(entry.before, checkpoint)
        self.assertEqual(list(fight.builds.values_list("digest", flat=True)), hashes)
        self.assertEqual(rules.party_id(combat.state_for(self.char1), self.char1.pk), self.key)
