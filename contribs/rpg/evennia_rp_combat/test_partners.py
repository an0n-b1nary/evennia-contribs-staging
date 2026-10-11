# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Partner contracts against real packet arithmetic and durable recovery."""

from copy import deepcopy
from dataclasses import fields, replace
from fractions import Fraction as F
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from . import arithmetic, engine, partners, policies, services
from .commands import CmdCombat
from .data import CombatError, Move
from .state import upgrade
from .tests import build, declare, duel

REGISTRY = {
    "demo": {"app": "evennia_rp_combat", "provider": "evennia_rp_combat.test_partners.PROVIDER"}
}


def upgrade_demo(section):
    if section is None:
        return {"schema": 1, "data": {"boost": "30", "surge": "25", "formation": "20"}}
    if section["schema"] != 1:
        raise CombatError("Unsupported demonstration partner version.")
    return section


def snapshot_demo(state, declaration):
    data = state["partners"]["demo"]["data"]
    # Even an accidental input mutation is isolated from the real fight.
    state["participants"][declaration.actor_id]["hp"] = -999
    return partners.PacketModifiers(
        formation_penalty=data["formation"],
        damage_boost=data["boost"],
        surge=data["surge"],
        auto_resolve=data.get("automatic", True),
        facts=(("snapshot", "demonstration"),),
    )


def transition_demo(state, event):
    section = state["partners"]["demo"]
    section["data"].setdefault("events", []).append(event.kind)
    state["participants"].clear()
    return section


PROVIDER = partners.Provider(
    snapshot=snapshot_demo,
    upgrade=upgrade_demo,
    transition=transition_demo,
    status=lambda state, subject: (f"Demo status for {subject}.",),
    help=lambda state, subject: ("Demo help: optional partner commands.",),
)


@override_settings(RP_COMBAT_PARTNERS={})
class TestStateUpgrade(SimpleTestCase):
    def test_upgrade_is_detached_deterministic_and_preserves_old_packets(self):
        old = duel()
        token = declare(old)
        old["schema"] = 1
        old.pop("partners")
        old["exchanges"][token.split(":")[0]].pop("partner_modifiers")
        original = deepcopy(old)
        upgraded = upgrade(old)
        self.assertEqual(old, original)
        self.assertEqual(upgraded["schema"], 2)
        self.assertEqual(upgrade(upgraded), upgraded)
        engine.reaction(upgraded, 2, token, "resist")
        engine.reaction(old, 2, token, "resist")
        self.assertEqual(upgraded["participants"], old["participants"])

    def test_unknown_and_boolean_versions_fail_visibly(self):
        for version in (0, 3, 999, True, "1"):
            with self.subTest(version=version), self.assertRaisesRegex(CombatError, "Unsupported"):
                upgrade({"schema": version})

    def test_absent_partner_state_is_preserved_and_explained(self):
        state = duel()
        section = {"schema": 97, "data": {"pool": "75/2", "nested": [1, {"future": True}]}}
        state["partners"]["party"] = deepcopy(section)
        result = upgrade(state)
        self.assertEqual(result["partners"]["party"], section)
        self.assertIn("unavailable", partners.lines(result, "1")[0])
        self.assertEqual(
            partners.modifiers({"partner_modifiers": {}}, "2"), partners.PacketModifiers()
        )

    def test_invalid_envelope_and_nonfinite_data_fail_closed(self):
        for section in (
            {"schema": True, "data": {}},
            {"schema": 1, "data": []},
            {"schema": 1, "data": {"bad": float("nan")}},
        ):
            state = duel()
            state["partners"]["party"] = section
            with self.assertRaises(CombatError):
                upgrade(state)

    def test_absent_app_is_not_imported(self):
        with (
            override_settings(
                RP_COMBAT_PARTNERS={
                    "party": {
                        "app": "no_such_optional_partner",
                        "provider": "missing.module.PROVIDER",
                    }
                }
            ),
            patch.object(partners, "import_string") as imported,
        ):
            self.assertEqual(partners.registered(), {})
        imported.assert_not_called()

    def test_bad_registration_and_modifier_types_are_rejected(self):
        with (
            override_settings(RP_COMBAT_PARTNERS={"bad": "not a provider"}),
            self.assertRaises(CombatError),
        ):
            partners.registered()
        for value in ("nan", "1/0", True, 1.5, "-1", "101"):
            with self.subTest(value=value), self.assertRaises(CombatError):
                partners.PacketModifiers(damage_boost=value)
        with self.assertRaises(CombatError):
            partners.PacketModifiers(auto_resolve=1)


@override_settings(RP_COMBAT_PARTNERS=REGISTRY)
class TestPartnerPackets(SimpleTestCase):
    def test_snapshot_controls_odds_and_resolution_without_recomputation(self):
        state = duel()
        token = declare(state)
        exchange = engine.get_exchange(state, token)
        view = engine.reaction_view(state, 2, token)
        state["partners"]["demo"]["data"].update(boost="0", formation="0", surge="0")
        self.assertEqual(state["participants"]["1"]["hp"], 100)
        preview = arithmetic.resolve(
            build(),
            view.build,
            Move(),
            "resist",
            100,
            bonus=F(dict(view.bonuses)["resist"]),
            damage_boost=F(view.damage_boost),
            surge=F(view.surge),
        )
        engine.reaction(state, 2, token, "resist")
        actual = exchange["outcomes"][0]
        self.assertEqual((actual["chance"], actual["damage"]), (preview.chance, preview.damage))
        self.assertEqual(actual["damage"], 28)
        self.assertEqual(actual["chance"], 80)
        self.assertEqual(
            state["partners"]["demo"]["data"]["events"], ["declare", "packet", "exchange_end"]
        )
        self.assertNotIn("draw", {field.name for field in fields(partners.Declaration)})
        self.assertNotIn("bet", {field.name for field in fields(partners.Declaration)})
        self.assertEqual(policies.auto_react(view)[0], "evade")

    def test_provider_absence_and_reinstallation_use_only_declared_values(self):
        state = duel()
        token = declare(state)
        exchange = engine.get_exchange(state, token)
        with override_settings(RP_COMBAT_PARTNERS={}):
            self.assertEqual(partners.modifiers(exchange, 2).damage_boost, "0")
            before = deepcopy(state["partners"])
            engine.reaction(state, 2, token, "resist")
            self.assertEqual(state["partners"], before)
            self.assertEqual(exchange["outcomes"][0]["damage"], 18)
            absent = duel()
            absent_token = declare(absent)
        # Reinstall does not invent modifiers for a declaration made absent.
        self.assertEqual(
            partners.modifiers(engine.get_exchange(absent, absent_token), 2).damage_boost, "0"
        )
        self.assertEqual(partners.modifiers(exchange, 2).damage_boost, "30")

    def test_party_boost_changes_actual_damage_and_pressure_not_burst_transfer(self):
        result = arithmetic.resolve(build(), build(), Move(), "resist", 1, damage_boost=30)
        self.assertEqual((result.damage, result.pressure_gain, result.burst_damage), (7, 16, 5))
        state = duel()
        token = declare(state, burst=True)
        expected = arithmetic.burst_transfer(23, 0, -600, 0, 0)
        engine.reaction(state, 2, token, "resist")
        outcome = state["exchanges"][token.split(":")[0]]["outcomes"][0]
        self.assertEqual(outcome["damage"], 28)
        self.assertEqual(outcome["transfer_actual"], expected[-1])

    def test_support_surge_and_empower_are_additive(self):
        base = arithmetic.support_values(build(), build(), "assist", 100)
        empowered = arithmetic.support_values(
            build(), build(), "assist", 100, empower=True, surge=25
        )
        self.assertEqual(empowered[:2], (875, 26))
        self.assertEqual(base[:2], (500, 15))

    def test_damage_event_preserves_eligibility_before_a_defeating_hit(self):
        events = []
        provider = replace(
            PROVIDER,
            transition=lambda state, event: events.append(event) or state["partners"]["demo"],
        )
        with patch(f"{__name__}.PROVIDER", provider):
            state = duel()
            state["participants"]["2"]["hp"] = 1
            token = declare(state)
            engine.reaction(state, 2, token, "resist")
        packet = next(event for event in events if event.kind == "packet")
        self.assertEqual(packet.damage, 1)
        self.assertTrue(packet.target_was_participating)
        self.assertFalse(engine.participating(state["participants"]["2"]))

    def test_support_event_distinguishes_capped_output_from_no_effect(self):
        events = []
        provider = replace(
            PROVIDER,
            transition=lambda state, event: events.append(event) or state["partners"]["demo"],
        )
        with patch(f"{__name__}.PROVIDER", provider):
            state = duel()
            state["participants"]["2"]["side"] = "one"
            engine.join(state, 3, "Opponent", "two", build())
            state["participants"]["2"]["spirit"] = 2000
            declare(state, move=Move(action="assist"))
        packet = next(event for event in events if event.kind == "packet")
        self.assertEqual(packet.spirit, 0)
        self.assertGreater(packet.potential_spirit, 0)


@override_settings(RP_COMBAT_PARTNERS={})
class TestAtomicInterception(SimpleTestCase):
    def state(self, **kwargs):
        state = duel(**kwargs)
        engine.join(state, 3, "Coverer", "two", build())
        return state

    def test_opener_handoff_keeps_draw_ante_count_and_original_defender_safe(self):
        state = self.state()
        token = declare(state, burst=True)
        engine.redirect(state, token, 2, 3, "resist")
        exchange = state["exchanges"][token.split(":")[0]]
        self.assertEqual(exchange["targets"], ["3"])
        self.assertEqual((exchange["draw"], exchange["hit"], exchange["paid_ante"]), (100, 1, 600))
        self.assertEqual(state["participants"]["2"]["hp"], 100)
        self.assertEqual(state["participants"]["2"]["incoming"], [])
        self.assertEqual(exchange["phase"], "press")
        engine.press(state, 1, 100)
        second = f"{exchange['id']}:2"
        self.assertEqual(
            engine.reaction_view(state, 3, second).reactions, ("evade", "resist", "overpower")
        )
        engine.reaction(state, 3, second, "resist")
        engine.press(state, 1, 100)
        engine.reaction(state, 3, f"{exchange['id']}:3", "resist")
        self.assertEqual((exchange["hit"], exchange["phase"]), (3, "done"))
        self.assertEqual(state["participants"]["1"]["clock"], 1)

    def test_later_handoff_can_stop_without_more_overextension(self):
        state = self.state()
        token = declare(state, burst=True)
        engine.reaction(state, 2, token, "resist")
        engine.press(state, 1, 100)
        engine.redirect(state, token.replace(":1", ":2"), 2, 3, "resist")
        before = engine.value(state["participants"]["1"], "overextended")
        engine.press(state, 1, 100, stop=True)
        self.assertEqual(engine.value(state["participants"]["1"], "overextended"), before)
        self.assertEqual(state["participants"]["1"]["clock"], 1)

    def test_invalid_evade_and_unaffordable_counter_leave_everything_untouched(self):
        for kind, counter in (
            ("evade", None),
            ("overpower", Move(key="special", kind="improvised", power=1)),
        ):
            state = self.state()
            state["participants"]["3"]["reserves"] = 0
            token = declare(state)
            before = deepcopy(state)
            with self.assertRaises(CombatError):
                engine.redirect(state, token, 2, 3, kind, counter=counter)
            self.assertEqual(state, before)

    def test_partial_multitarget_acceptance_closes_interception(self):
        state = self.state(boss=2)
        engine.join(state, 4, "Other target", "two", build())
        token = declare(state, targets=(2, 4))
        engine.reaction(state, 2, token, "resist")
        before = deepcopy(state)
        with self.assertRaises(CombatError):
            engine.redirect(state, token, 4, 3, "resist")
        self.assertEqual(state, before)

    def test_same_exchange_target_cannot_intercept(self):
        state = self.state(boss=2)
        token = declare(state, targets=(2, 3))
        with self.assertRaises(CombatError):
            engine.redirect(state, token, 2, 3, "resist")


@override_settings(RP_COMBAT_REVEALED=True, RP_COMBAT_PARTNERS=REGISTRY)
class TestPartnerCoordinator(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.char2.location = self.char1.location
        source = patch("evennia_rp_combat.services.snapshot", return_value=build())
        source.start()
        self.addCleanup(source.stop)
        services.setup(self.char1)
        services.join(self.char1, "one")
        services.join(self.char2, "two")

    def test_legacy_rows_and_journal_snapshots_upgrade_without_rewriting(self):
        fight = services.open_fight(self.char1.location)
        legacy = deepcopy(fight.state)
        legacy["schema"] = 1
        legacy.pop("partners")
        fight.state = legacy
        fight.save(update_fields=["state"])
        self.assertEqual(services.state_for(self.char1)["schema"], 2)
        fight.refresh_from_db()
        self.assertEqual(fight.state, legacy)
        services.storyteller(self.char1, "pause")
        entry = fight.entries.latest("sequence")
        # Retained old snapshots may still be schema 1 after upgrading.
        checkpoint = deepcopy(entry.before)
        checkpoint["schema"] = 1
        checkpoint.pop("partners")
        entry.before = checkpoint
        entry.save(update_fields=["before"])
        old_builds = list(fight.builds.values_list("digest", "build"))
        self.char1.permissions.add("Builder")
        services.rollback(self.char1, entry.sequence, "restore old checkpoint")
        self.assertEqual(services.state_for(self.char1)["schema"], 2)
        entry.refresh_from_db()
        self.assertEqual(entry.before, checkpoint)
        self.assertEqual(list(fight.builds.values_list("digest", "build")), old_builds)

    def test_status_help_and_missing_provider_notice_use_plain_text_seams(self):
        self.assertIn("Demo status", services.render(self.char1))
        self.call(CmdCombat(), "/help", "Use help +combat for core commands.")
        self.assertIn("Demo help", services.help_for(self.char1))
        with override_settings(RP_COMBAT_PARTNERS={}):
            self.assertIn("partner rules unavailable", services.render(self.char1))
            services.shelve(self.char1, "continue without optional partner")
        fight = services._fights().objects.latest("pk")
        self.assertIn("demo", fight.state["partners"])

    def test_duplicate_delivery_does_not_duplicate_partner_events(self):
        services.declare(self.char1, [self.char2], operation_id="partner-declaration")
        before = services.state_for(self.char1)["partners"]
        services.declare(self.char1, [self.char2], operation_id="partner-declaration")
        self.assertEqual(services.state_for(self.char1)["partners"], before)
