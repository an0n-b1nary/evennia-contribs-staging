# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Tactical state, real combat arithmetic and durable authorized operations."""

import json
from copy import deepcopy
from fractions import Fraction as F
from unittest.mock import PropertyMock, patch

from django.test import SimpleTestCase, override_settings
from evennia.utils.test_resources import EvenniaCommandTest
from evennia_rp_combat import arithmetic, engine, partners
from evennia_rp_combat import services as combat
from evennia_rp_combat.data import Build, CombatError, Move

from . import providers, rules, services
from .commands import CmdParty

REGISTRY = {"party": {"app": "evennia_rp_party", "provider": "evennia_rp_party.providers.PROVIDER"}}
ROLES = ("attack", "attack_defense", "spell", "spell_defense", "dispirit", "will", "agility")


def build(*, abilities=(), effects=(), moves=(), **scores):
    return Build(
        tuple((role, str(scores.get(role, 0))) for role in ROLES),
        moves=moves,
        abilities=abilities,
        effects=effects,
    )


def teams(*, builds=None, boss=1):
    state = engine.new_state()
    for ident in range(1, 7):
        engine.join(
            state,
            ident,
            f"Character {ident}",
            "one" if ident <= 3 else "two",
            (builds or {}).get(ident, build()),
            boss=boss if ident == 1 else 1,
        )
    first = rules.create(state, 1, "First")
    second = rules.create(state, 4, "Second")
    for ident, key in ((2, first), (3, first), (5, second), (6, second)):
        rules.join(state, ident, key)
    return state, first, second


def declare(state, actor=1, target=4, *, move=None, roll=100, **kwargs):
    ident = engine.declaration(state, actor, (target,), move or Move(), roll, **kwargs)
    return f"{ident}:1"


def assist(state, actor=2, target=1, **kwargs):
    return declare(state, actor, target, move=Move(action="assist"), **kwargs)


@override_settings(RP_COMBAT_PARTNERS=REGISTRY)
class TestPartyRules(SimpleTestCase):
    def test_runtime_registration_is_repeatable_when_django_repopulates_apps(self):
        from . import conf

        conf.register_runtime()
        conf.register_runtime()

    def test_multiple_parties_and_unpartied_allies_preserve_personal_and_side_state(self):
        state, first, _second = teams()
        engine.opening(state)
        before = deepcopy(state["participants"]["2"])
        assessment = engine.assessment(state)
        denominator = deepcopy(state["denominators"])
        rules.leave(state, 2)
        third = rules.create(state, 2, "Third")
        rules.join(state, 3, third)
        rules.leave(state, 3)
        self.assertNotEqual(first, third)
        self.assertIsNone(rules.party_id(state, 3))
        self.assertEqual(state["participants"]["2"], before)
        self.assertEqual(engine.assessment(state), assessment)
        self.assertEqual(state["denominators"], denominator)
        with self.assertRaises(CombatError):
            rules.join(state, 4, third)

    def test_members_rename_dissolve_by_agreement_and_cleanup_empty_identity(self):
        state, first, _second = teams()
        rules.rename(state, 2, "Renamed")
        self.assertEqual(rules.party(state, first)["name"], "Renamed")
        self.assertIn("waiting", rules.dissolve(state, 1, first))
        rules.dissolve(state, 2, first, agree=True)
        self.assertEqual(rules.dissolve(state, 3, first, agree=True), "dissolved")
        self.assertTrue(all(rules.party_id(state, ident) is None for ident in (1, 2, 3)))
        empty = rules.prepare(state, "Empty", "one")
        self.assertEqual(rules.dissolve(state, 4, empty), "dissolved")
        newer = rules.create(state, 1, "New")
        self.assertNotEqual(first, newer)

    def test_membership_change_clears_votes_and_pending_exchange_blocks_movement(self):
        state, first, second = teams()
        rules.dissolve(state, 1, first)
        rules.leave(state, 2)
        self.assertNotIn(first, rules.data(state)["proposals"])
        token = declare(state)
        for action in (
            lambda: rules.leave(state, 1),
            lambda: rules.formation(state, 4, "back"),
            lambda: rules.join(state, 4, second),
        ):
            with self.assertRaises(CombatError):
                action()
        engine.cancel(state, 4, token)
        rules.leave(state, 1)

    def test_saved_eligibility_excludes_unavailable_but_not_turn_exhaustion(self):
        for mutation in (
            {"hp": 0},
            {"recovering": True},
            {"status": "faded"},
            {"status": "withdrawn"},
            {"absent": True},
            {"correction": True},
            {"return_required": True},
        ):
            state, first, _second = teams()
            state["participants"]["1"].update(mutation)
            self.assertNotIn("1", rules.counted(state, first))
            self.assertEqual(rules.party_id(state, 1), first)
        state["participants"]["2"]["turns"] = 4
        self.assertIn("2", rules.counted(state, first))

    def test_signed_average_is_clamped_after_independent_support_entries(self):
        state, first, _second = teams()
        for ident in (1, 2, 3):
            state["participants"][str(ident)]["spirit"] = -600
        data = rules.data(state)
        data["support"] = {
            str(ident): {"party": first, "kind": "rally", "points": "5", "exchange": "old"}
            for ident in (2, 3)
        }
        self.assertEqual(rules.average(state, first), -6)
        self.assertEqual(rules.boost(state, first), 4)
        data["support"]["4"] = {"party": first, "kind": "rattle", "points": "5", "exchange": "old"}
        self.assertEqual(rules.boost(state, first), 0)

    def test_wholly_faded_party_retains_sources_and_positions(self):
        state, first, _second = teams()
        assist(state)
        rules.formation(state, 1, "front")
        retained = deepcopy(rules.data(state)["support"])
        for ident in (1, 2, 3):
            engine.fade(state, ident)
        self.assertEqual(rules.boost(state, first), 0)
        self.assertEqual(rules.data(state)["support"], retained)
        for ident in (1, 2, 3):
            engine.join(state, ident, "Ignored new name", "ignored side", build())
        self.assertGreater(rules.boost(state, first), 0)
        self.assertEqual(rules.position(state, 1), "front")

    def test_saved_support_expires_when_actions_complete_with_provider_absent(self):
        for final in (False, True):
            state, first, _second = teams()
            source = state["participants"]["2"]
            if final:
                source["turns"] = source["turn_limit"] - 1
            assist(state)
            retained = deepcopy(rules.data(state)["support"])
            actor = 1 if final else 2
            state["participants"][str(actor)]["pose"] = False
            with override_settings(RP_COMBAT_PARTNERS={}):
                token = declare(state, actor=actor)
                engine.reaction(state, 4, token, "resist")
            self.assertEqual(rules.data(state)["support"], retained)
            self.assertEqual(rules.boost(state, first), max(F(0), rules.average(state, first)))

    def test_supporters_stack_replace_and_expire_without_restarting_repeats(self):
        state, first, second = teams()
        assist(state, 2, 1)
        assist(state, 3, 1)
        self.assertEqual(set(rules.data(state)["support"]), {"2", "3"})
        state["participants"]["2"]["pose"] = False
        declare(state, 2, 4, move=Move(action="dispirit"), roll=1)
        entries = rules.data(state)["support"]
        self.assertEqual(entries["2"]["kind"], "rattle")
        self.assertEqual(entries["2"]["party"], second)
        self.assertEqual(entries["3"]["party"], first)
        state["participants"]["3"]["pose"] = False
        rules.leave(state, 3)
        token = declare(state, 3, 4)
        engine.reaction(state, 4, token, "resist")
        self.assertNotIn("3", rules.data(state)["support"])
        self.assertIn("assist:1", state["participants"]["3"]["support_history"])

    def test_final_rally_expires_after_affected_party_next_exchange(self):
        state, first, _second = teams()
        state["participants"]["2"].update(turn_limit=1)
        assist(state)
        self.assertIn("2", rules.data(state)["support"])
        token = declare(state)
        self.assertEqual(
            partners.modifiers(engine.get_exchange(state, token), 4).damage_boost,
            str(rules.boost(state, first)),
        )
        engine.reaction(state, 4, token, "resist")
        self.assertNotIn("2", rules.data(state)["support"])

    def test_cancellation_and_failed_dispirit_grant_no_entry_or_expiry(self):
        state, _first, _second = teams()
        assist(state)
        retained = deepcopy(rules.data(state)["support"])
        state["participants"]["2"]["pose"] = False
        token = declare(state, 2, 4)
        engine.cancel(state, 4, token)
        self.assertEqual(rules.data(state)["support"], retained)
        declare(state, 3, 4, move=Move(action="dispirit"), roll=100)
        self.assertNotIn("3", rules.data(state)["support"])

    def test_successful_capped_assist_qualifies_and_recovery_expires_without_rewards(self):
        state, _first, _second = teams()
        state["participants"]["1"]["spirit"] = 2000
        assist(state)
        self.assertIn("2", rules.data(state)["support"])
        source = state["participants"]["2"]
        source.update(recovering=True, pose=False)
        resources = source["reserves"], source["transcendence"], source["spirit"]
        engine.pass_action(state, 2)
        self.assertNotIn("2", rules.data(state)["support"])
        self.assertEqual((source["reserves"], source["transcendence"], source["spirit"]), resources)


@override_settings(RP_COMBAT_PARTNERS=REGISTRY)
class TestFormationCover(SimpleTestCase):
    def positioned(self, **kwargs):
        state, first, second = teams(**kwargs)
        rules.formation(state, 1, "back")
        rules.formation(state, 2, "front")
        rules.formation(state, 4, "back", cover=True)
        rules.formation(state, 5, "front")
        return state, first, second

    def test_matrix_range_pinpoint_and_own_back_penalty(self):
        for long_range, pinpoint, resistance, expected in (
            (False, False, False, 40),
            (True, False, False, 20),
            (False, True, False, 20),
            (False, True, True, 40),
        ):
            expertise = build(abilities=(("proficiency", "perception", 1),))
            resistant = build(abilities=(("domain-resistance", "perception", 1),))
            state, _first, _second = self.positioned(
                builds={1: expertise, 4: resistant if resistance else build()}
            )
            move = (
                Move(kind="improvised", power=1, effects=("long_range",)) if long_range else Move()
            )
            token = declare(
                state,
                move=move,
                domain="perception" if pinpoint else "",
                domain_effects={"perception": "pinpoint"},
            )
            self.assertEqual(
                F(partners.modifiers(engine.get_exchange(state, token), 4).formation_penalty),
                expected,
            )

    def test_front_loss_changes_only_future_declarations_and_unpartied_is_neutral(self):
        state, _first, _second = self.positioned()
        token = declare(state)
        engine.fade(state, 5)
        self.assertEqual(
            partners.modifiers(engine.get_exchange(state, token), 4).formation_penalty, "40"
        )
        engine.cancel(state, 4, token)
        token = declare(state)
        self.assertEqual(
            partners.modifiers(engine.get_exchange(state, token), 4).formation_penalty, "20"
        )
        engine.cancel(state, 4, token)
        rules.leave(state, 4)
        token = declare(state)
        self.assertEqual(
            partners.modifiers(engine.get_exchange(state, token), 4).formation_penalty, "0"
        )

    def test_cover_opener_preserves_snapshot_then_new_hit_uses_front_and_can_stop(self):
        state, _first, _second = self.positioned()
        token = declare(state, burst=True, bet="subtle")
        before = deepcopy(state)
        view = engine.interception_view(state, token, 4, 5)
        self.assertEqual(view.reactions, ("resist", "overpower"))
        self.assertFalse(view.public_bet)
        self.assertEqual(state, before)
        rules.cover_allowed(state, "5", "4", token)
        engine.redirect(state, token, 4, 5, "resist")
        exchange = state["exchanges"][token.split(":")[0]]
        self.assertEqual(exchange["targets"], ["5"])
        self.assertEqual(partners.modifiers(exchange, 5).formation_penalty, "40")
        self.assertEqual(state["participants"]["4"]["hp"], 100)
        engine.press(state, 1, 100)
        self.assertEqual(partners.modifiers(exchange, 5).formation_penalty, "20")
        engine.reaction(state, 5, f"{exchange['id']}:2", "resist")
        before = engine.value(state["participants"]["1"], "overextended")
        engine.press(state, 1, 100, stop=True)
        self.assertEqual(engine.value(state["participants"]["1"], "overextended"), before)
        self.assertEqual(state["participants"]["1"]["clock"], 1)

    def test_auto_suppression_is_only_for_opted_in_back(self):
        state, _first, _second = self.positioned()
        token = declare(state)
        self.assertFalse(partners.modifiers(engine.get_exchange(state, token), 4).auto_resolve)
        engine.cancel(state, 4, token)
        rules.formation(state, 4, "back", cover=False)
        token = declare(state)
        self.assertTrue(partners.modifiers(engine.get_exchange(state, token), 4).auto_resolve)

    def test_covered_burst_cannot_be_passed_on_after_formation_changes_between_hits(self):
        state, _first, _second = self.positioned()
        token = declare(state, burst=True)
        engine.redirect(state, token, 4, 5, "resist")
        rules.formation(state, 5, "back", cover=True)
        rules.formation(state, 6, "front")
        engine.press(state, 1, 100)
        token = token.replace(":1", ":2")
        before = deepcopy(state)
        for operation in (engine.interception_view, lambda *args: engine.redirect(*args, "resist")):
            with self.assertRaises(CombatError):
                operation(state, token, 5, 6)
            self.assertEqual(state, before)

    def test_later_cover_overpower_breaks_chain_and_unaffordable_counter_is_atomic(self):
        state, _first, _second = self.positioned()
        token = declare(state, burst=True)
        engine.reaction(state, 4, token, "resist")
        engine.press(state, 1, 1)
        token = token.replace(":1", ":2")
        state["participants"]["5"]["reserves"] = 0
        before = deepcopy(state)
        with self.assertRaises(CombatError):
            engine.redirect(
                state, token, 4, 5, "overpower", counter=Move(kind="improvised", power=1)
            )
        self.assertEqual(state, before)
        engine.redirect(state, token, 4, 5, "overpower")
        self.assertEqual(state["exchanges"][token.split(":")[0]]["phase"], "done")

    def test_party_burst_boost_never_enters_transfer_basis_or_counterdamage(self):
        state, _first, _second = teams()
        for ident in (1, 2, 3):
            state["participants"][str(ident)]["spirit"] = 2000
        token = declare(state, burst=True)
        exchange = engine.get_exchange(state, token)
        boost = partners.modifiers(exchange, 4).damage_boost
        self.assertGreater(F(boost), 0)
        original = deepcopy(state)
        engine.reaction(state, 4, token, "resist")
        with override_settings(RP_COMBAT_PARTNERS={}):
            engine.reaction(original, 4, token, "resist")
        expected = original["exchanges"][exchange["id"]]["outcomes"][0]
        actual = exchange["outcomes"][0]
        self.assertGreater(actual["damage"], expected["damage"])
        self.assertEqual(actual["transfer_actual"], expected["transfer_actual"])


@override_settings(RP_COMBAT_PARTNERS=REGISTRY)
class TestEncore(SimpleTestCase):
    def test_spreads_half_spirit_including_actor_but_heals_only_named_target(self):
        mend = Move(key="mend", action="assist", kind="improvised", effects=("heal",))
        performer = build(abilities=(("proficiency", "performance", 1),))
        resistant = build(abilities=(("domain-resistance", "performance", 1),))
        state, first, _second = teams(builds={2: performer, 3: resistant})
        for ident in (1, 2, 3):
            state["participants"][str(ident)]["hp"] = 50
        token = declare(
            state, 2, 1, move=mend, domain="performance", domain_effects={"performance": "encore"}
        )
        self.assertEqual(
            [state["participants"][str(ident)]["spirit"] for ident in (1, 2, 3)], [250, 250, 250]
        )
        self.assertEqual(
            [state["participants"][str(ident)]["hp"] for ident in (1, 2, 3)], [65, 50, 50]
        )
        self.assertEqual(state["participants"]["2"]["clock"], 1)
        self.assertEqual(len(rules.data(state)["support"]), 1)
        self.assertEqual(rules.data(state)["support"]["2"]["party"], first)
        self.assertEqual(state["exchanges"][token.split(":")[0]]["resolved"], 1)
        history = state["participants"]["2"]["support_history"]
        self.assertTrue(all(f"assist:{ident}" in history for ident in (1, 2, 3)))

    def test_skip_unavailable_and_host_denied_recipients_and_repeats_follow_each(self):
        performer = build(abilities=(("proficiency", "performance", 1),))
        state, _first, _second = teams(builds={2: performer})
        state["participants"]["3"]["recovering"] = True
        declare(
            state,
            2,
            1,
            move=Move(action="assist"),
            domain="performance",
            domain_effects={"performance": "encore"},
            support_allowed={"1"},
        )
        self.assertEqual(state["participants"]["2"]["spirit"], 0)
        self.assertEqual(state["participants"]["3"]["spirit"], 0)
        actor = state["participants"]["2"]
        actor["pose"] = False
        state["participants"]["3"]["recovering"] = False
        declare(
            state,
            2,
            3,
            move=Move(action="assist"),
            domain="performance",
            domain_effects={"performance": "encore"},
        )
        self.assertGreater(
            state["participants"]["3"]["spirit"], state["participants"]["1"]["spirit"] - 250
        )

    def test_unpartied_fallback_and_zero_vitality_never_incidentally_revive(self):
        performer = build(abilities=(("proficiency", "performance", 1),))
        state, _first, _second = teams(builds={2: performer})
        state["participants"]["3"]["hp"] = 0
        rules.leave(state, 1)
        assist(state, domain="performance", domain_effects={"performance": "encore"})
        self.assertEqual(state["participants"]["1"]["spirit"], 700)
        self.assertEqual(state["participants"]["3"]["hp"], 0)
        self.assertEqual(state["participants"]["3"]["spirit"], 0)


@override_settings(RP_COMBAT_PARTNERS=REGISTRY)
class TestCombatAbilities(SimpleTestCase):
    def ruled(self, *specs):
        from evennia_rp_combat.modifiers import CombatRule

        return build(
            effects=tuple(
                (
                    f"rule-{index}",
                    json.dumps(CombatRule.from_spec({"kind": "combat_rule", **spec}).frozen()),
                )
                for index, spec in enumerate(specs)
            )
        )

    def test_rally_tempo_and_taunting_survive_cancel_then_cover_handoff(self):
        specialist = self.ruled(
            {"rule": "measured_tempo", "amount": "1/4", "cap": 2},
            {"rule": "taunting_opener", "amount": 300},
        )
        state, first, _second = teams(builds={1: specialist})
        actor = state["participants"]["1"]
        assist(state, actor=1, target=2)
        actor["pose"] = False
        declare(state, move=Move(action="dispirit"), roll=1)
        actor["pose"], actor["spirit"] = False, 1000
        retained = deepcopy(rules.data(state)["support"])
        token = declare(state, burst=True)
        exchange = engine.get_exchange(state, token)
        self.assertEqual(exchange["tempo"], 2)
        self.assertEqual(actor["spirit"], 700)
        engine.cancel(state, 4, token)
        self.assertEqual(
            (actor["tempo"], actor["spirit"], engine.value(actor, "taunting")), (2, 1000, 300)
        )
        self.assertEqual(rules.data(state)["support"], retained)
        rules.formation(state, 4, "back", cover=True)
        rules.formation(state, 5, "front")
        token = declare(state, burst=True)
        self.assertGreater(
            F(partners.modifiers(engine.get_exchange(state, token), 4).damage_boost), 0
        )
        engine.redirect(state, token, 4, 5, "resist")
        actor = state["participants"]["1"]
        engine.press(state, 1, 50, stop=True)
        self.assertEqual((actor["tempo"], engine.value(actor, "taunting")), (0, 0))
        self.assertNotIn("1", rules.data(state)["support"])
        self.assertGreater(rules.average(state, first), 0)

    def test_party_boost_and_bait_do_not_refund_blood_price_or_count_cover_twice(self):
        specialist = self.ruled({"rule": "bait"}, {"rule": "blood_price", "amount": 5})
        state, _first, _second = teams(builds={1: specialist})
        actor = state["participants"]["1"]
        actor["reserves"], actor["spirit"] = 0, 1000
        rules.formation(state, 4, "back", cover=True)
        rules.formation(state, 5, "front")
        token = declare(state, move=Move(kind="improvised", power=1), burst=True)
        self.assertEqual(actor["hp"], 95)
        engine.redirect(state, token, 4, 5, "overpower")
        actor = state["participants"]["1"]
        self.assertEqual((actor["hp"], actor["reserves"]), (95, 1))
        engine.press(state, 1, 100, stop=True)
        self.assertEqual(actor["clock"], 1)
        self.assertEqual(state["participants"]["4"]["hp"], 100)


@override_settings(RP_COMBAT_PARTNERS=REGISTRY, RP_COMBAT_REVEALED=True, RP_PARTY_REVEALED=True)
class TestPartyCoordinator(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char2.location = self.char1.location
        source = patch("evennia_rp_combat.services.snapshot", return_value=build())
        source.start()
        self.addCleanup(source.stop)
        combat.setup(self.char1)
        combat.join(self.char1, "one")
        combat.join(self.char2, "one")

    def test_commands_invitations_and_idempotent_journal_operations(self):
        self.call(CmdParty(), "/create Team", "Party create: 1.1.")
        services.change(self.char1, "invite", target=self.char2)
        self.assertIsNone(rules.party_id(combat.state_for(self.char1), self.char2.pk))
        services.change(self.char1, "rename", "Renamed")
        services.change(self.char2, "accept", operation_id="party-accept")
        before = combat.state_for(self.char2)
        services.change(self.char2, "accept", operation_id="party-accept")
        self.assertEqual(combat.state_for(self.char2), before)
        services.change(self.char1, "dissolve")
        self.assertEqual(services.change(self.char2, "agree"), "dissolved")

    def test_chat_never_writes_state_or_journal_even_during_pause(self):
        key = services.change(self.char1, "create", "Chat")
        services.change(self.char2, "join", key)
        combat.storyteller(self.char1, "pause")
        fight = combat.open_fight(self.char1.location)
        before = deepcopy(fight.state)
        entries = fight.entries.count()
        with patch(
            "evennia.accounts.accounts.DefaultAccount.is_connected",
            new_callable=PropertyMock,
            return_value=True,
        ):
            # Routing is checked separately with real sessions in the sandbox.
            services.chat(self.char1, "private phrase for no stored history")
        fight.refresh_from_db()
        self.assertEqual(fight.state, before)
        self.assertEqual(fight.entries.count(), entries)
        self.assertNotIn("private phrase", json.dumps(fight.state))

    def test_shelving_rollback_and_missing_provider_preserve_party_section(self):
        key = services.change(self.char1, "create", "Retained")
        services.change(self.char2, "join", key)
        services.change(self.char1, "formation", "front")
        services.change(self.char2, "formation", "back", cover=True)
        fight = combat.open_fight(self.char1.location)
        entry = fight.entries.latest("sequence")
        self.char1.permissions.add("Builder")
        combat.rollback(self.char1, entry.sequence, "restore formation checkpoint")
        state = combat.state_for(self.char1)
        self.assertEqual(rules.position(state, self.char2.pk), "flex")
        self.assertEqual(rules.party_id(state, self.char2.pk), key)
        retained = deepcopy(state["partners"]["party"])
        with override_settings(RP_COMBAT_PARTNERS={}):
            self.assertIn("party: partner rules unavailable", combat.render(self.char1))
            combat.shelve(self.char1, "continue later with provider unavailable")
        fight.refresh_from_db()
        self.assertEqual(fight.state["partners"]["party"], retained)

    def test_other_pc_control_is_refused_and_no_party_created(self):
        with self.assertRaises(CombatError):
            services.change(self.char1, "create", "Unwanted", subject=self.char2)
        self.assertFalse(rules.data(combat.state_for(self.char1))["parties"])
