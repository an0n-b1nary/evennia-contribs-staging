"""Combat seams under the real host ruleset and optional installed partners."""

from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from world.sandbox.test_rp_partners import RPSeedMixin

FOUNDATION_PROVIDER = None  # Assigned only within the extension seam test.


@skipUnless(apps.is_installed("evennia_rp_combat"), "Combat partner absent")
class TestCombatPlayground(RPSeedMixin, EvenniaCommandTest):
    def test_partner_snapshots_use_real_frozen_sheets_and_survive_absence(self):
        from evennia_rp_combat import partners, services

        provider = partners.Provider(
            upgrade=lambda section: section or {"schema": 1, "data": {"retained": True}},
            snapshot=lambda state, declaration: partners.PacketModifiers(
                damage_boost="20", facts=(("target", declaration.target_id),)
            ),
            status=lambda state, subject: ("Foundation partner active.",),
        )
        registry = {
            "foundation": {
                "app": "evennia_rp_combat",
                "provider": "world.sandbox.test_combat.FOUNDATION_PROVIDER",
            }
        }
        first, second = self.samples[:2]
        with (
            patch("world.sandbox.test_combat.FOUNDATION_PROVIDER", provider),
            override_settings(RP_COMBAT_PARTNERS=registry),
        ):
            services.setup(first)
            services.join(first, "one")
            services.join(second, "two")
            exchange_id = services.declare(first, [second])
            state = services.state_for(first)
            saved = state["exchanges"][exchange_id]["partner_modifiers"][str(second.pk)]
            self.assertEqual(saved["foundation"]["damage_boost"], "20")
            self.assertTrue(state["participants"][str(first.pk)]["build"]["scores"])
            self.assertIn("Foundation partner active", services.render(first))
            with override_settings(RP_COMBAT_PARTNERS={}):
                services.react(second, f"{exchange_id}:1", "resist")
                self.assertIn("partner rules unavailable", services.render(first))
            reloaded = services.state_for(first)
            self.assertEqual(reloaded["partners"]["foundation"]["data"], {"retained": True})
            self.assertEqual(
                reloaded["exchanges"][exchange_id]["partner_modifiers"][str(second.pk)], saved
            )

    def test_seeded_signatures_tactics_and_command_registration(self):
        from commands.default_cmdsets import CharacterCmdSet
        from evennia_rp_chargen.models import SignatureMove
        from evennia_rp_combat.models import Tactics

        self.assertTrue(
            SignatureMove.objects.filter(
                character=self.samples[0], equipped_order__isnull=False
            ).exists()
        )
        self.assertTrue(Tactics.objects.filter(character=self.samples[0], active=True).exists())
        cmdset = CharacterCmdSet(self.char1)
        keys = {cmd.key for cmd in cmdset.commands}
        self.assertTrue(
            {
                "+combat",
                "+combatstory",
                "+tactics",
                "+moves",
                "+attack",
                "+spell",
                "+pass",
                "+react",
                "+surge",
                "+cover",
                "+improv",
                "+bosscheck",
            }
            <= keys
        )

    def test_active_sheets_freeze_and_fade_releases_without_changing_the_fight(self):
        from evennia_rp_chargen import locks, moves
        from evennia_rp_chargen import services as chargen
        from evennia_rp_chargen.services import ChargenError
        from evennia_rp_combat import services

        first, second = self.samples[:2]

        def fight_moves():
            row = services.state_for(first)["participants"][str(first.pk)]
            return {m["key"] for m in row["build"]["moves"]}

        services.setup(first)
        services.join(first, "one")
        services.join(second, "two")
        with self.assertRaisesRegex(ChargenError, "combat build correction"):
            locks.unlock(first)
        with self.assertRaisesRegex(ChargenError, "combat build is frozen"):
            chargen.set_edge(first, "strength", 1)
        # Fading releases the real sheet (e.g. for another fight) ...
        services.control(first, "fade")
        moves.equip(first, "ready-guard", equipped=False)
        # ... and rejoining restores the build frozen for this fight.
        services.join(first)
        self.assertIn("ready-guard", fight_moves())
        with self.assertRaisesRegex(ChargenError, "combat build is frozen"):
            moves.equip(first, "ready-guard")
        # An announced correction adopts the current sheet.
        services.control(first, "unlock")
        locks.note_ic_action(first)
        services.control(first, "relock")
        self.assertNotIn("ready-guard", fight_moves())

    @skipUnless(apps.is_installed("evennia_rp_equipment"), "Equipment partner absent")
    def test_combat_correction_covers_real_abilities_pips_signatures_and_gear(self):
        from evennia_rp_chargen import abilities, locks, moves
        from evennia_rp_chargen import services as chargen
        from evennia_rp_chargen.services import ChargenError
        from evennia_rp_combat import services
        from evennia_rp_equipment import services as gear
        from evennia_rp_equipment.services import GearError

        first, second = self.samples
        services.setup(first)
        services.join(first, "one")
        services.join(second, "two")
        for change in (
            lambda: chargen.set_edge(first, "strength", 1),
            lambda: abilities.unequip(first, "calling-the-shot"),
            lambda: moves.equip(first, "ready-guard", equipped=False),
            lambda: gear._check_unfrozen(first),
        ):
            with self.assertRaises((ChargenError, GearError)):
                change()
        with (
            patch("evennia_rp_combat.services.emit") as announce,
            self.captureOnCommitCallbacks(execute=True),
        ):
            services.control(first, "unlock", reason="private arsenal choice")
        text = str(announce.call_args_list)
        self.assertIn("unlocked their combat build", text)
        self.assertNotIn("private arsenal", text)
        locks.note_ic_action(first)
        chargen.set_edge(first, "strength", 1)
        abilities.unequip(first, "calling-the-shot")
        moves.equip(first, "ready-guard", equipped=False)
        gear._check_unfrozen(first)
        services.control(first, "relock")
        with self.assertRaises(ChargenError):
            abilities.equip(first, "calling-the-shot")

    def test_combat_abilities_validate_freeze_and_call_a_public_shot(self):
        from evennia_rp_chargen.catalog import definition_problems
        from evennia_rp_chargen.models import AbilityDefinition
        from evennia_rp_combat import services
        from evennia_rp_combat.modifiers import rules
        from evennia_rp_combat.sources import snapshot

        from world.ruleset import COMBAT_ABILITIES

        for entry in COMBAT_ABILITIES:
            row = AbilityDefinition.objects.get(key=entry["key"])
            self.assertEqual(definition_problems(row), [], entry["key"])
        first, second = self.samples[:2]
        self.assertIn("calling_the_shot", rules(snapshot(first)))
        self.assertIn("bait", rules(snapshot(second)))
        services.setup(first)
        services.join(first, "one")
        services.join(second, "two")
        exchange_id = services.declare(first, [second], bet="reaching", public=True)
        state = services.state_for(first)
        self.assertTrue(state["exchanges"][exchange_id]["public_bet"])
        self.assertIn("reaching bet publicly", services.odds(second, f"{exchange_id}:1"))
        services.control(second, "cancel", argument=f"{exchange_id}:1")
        with self.assertRaisesRegex(ValueError, "Calling the Shot"):
            services.declare(second, [first], bet="subtle", public=True)

    def test_mechanics_system_entries_do_not_create_rp_activity(self):
        if not apps.is_installed("evennia_scenes"):
            self.skipTest("optional scenes partner absent")
        from evennia_rp_combat import services
        from evennia_scenes.models import LogEntry, Scene

        first = self.samples[0]
        scene = Scene.objects.create(
            title="Combat seam", room=self.grounds, privacy="public", status="open", creator=first
        )
        self.grounds.active_scene_id = scene.pk
        with (
            patch("evennia_rptracker.tracker.record_rp_activity") as activity,
            self.captureOnCommitCallbacks(execute=True),
        ):
            services.setup(first)
        entry = LogEntry.objects.filter(scene=scene).last()
        self.assertEqual(entry.log_type, "system")
        activity.assert_not_called()

    def test_real_npc_permissions_stat_source_and_independent_pc(self):
        if not apps.is_installed("evennia_npcs"):
            self.skipTest("optional NPC partner absent")
        from evennia_npcs import services as npcs
        from evennia_rp_chargen.models import CharacterBuild
        from evennia_rp_combat import services

        actor = self.samples[0]
        blueprint = npcs.create_blueprint(
            actor,
            name="Combat Practice Partner",
            kind="template",
            stat_block={
                k: "B"
                for k in (
                    "strength",
                    "endurance",
                    "intellect",
                    "intuition",
                    "presence",
                    "resolve",
                    "agility",
                )
            },
        )
        record = npcs.spawn(actor, blueprint)
        npc = npcs.control(actor, record)
        services.setup(actor)
        services.join(actor, "one")
        services.join(actor, "two", subject=npc)
        state = services.state_for(actor)
        self.assertNotEqual(
            state["participants"][str(actor.pk)]["id"], state["participants"][str(npc.pk)]["id"]
        )
        self.assertFalse(CharacterBuild.objects.filter(character=npc).exists())
        services.auto_act(actor, subject=npc)
        with override_settings(NPCS_FROZEN=True), self.assertRaisesRegex(ValueError, "paused"):
            services.auto_act(actor, subject=npc)
        npcs.release(actor)
        with self.assertRaisesRegex(ValueError, "control"):
            services.auto_act(actor, subject=npc)

    def test_templates_batches_and_profiles_preserve_player_consent(self):
        if not apps.is_installed("evennia_npcs"):
            self.skipTest("optional NPC partner absent")
        from evennia_npcs import services as npcs
        from evennia_rp_combat import services

        from evennia_rp_rules.ruleset import get_ruleset

        actor, target = self.samples[:2]
        blueprint = npcs.create_blueprint(
            actor,
            name="Batch Practice Partner",
            kind="template",
            stat_block={key: "B" for key in get_ruleset().stats},
        )
        with override_settings(NPCS_COMBAT_PROFILES_REVEALED=True):
            npcs.edit_profile(
                actor,
                blueprint,
                {
                    "target_policy": "lowest_vitality",
                    "reaction_policy": {"appetite": "cautious", "rps_appetite": "bold"},
                    "action_weights": {"standard": 1},
                },
            )
        services.setup(actor)
        services.join(target, "opposition")
        first = services.template(actor, blueprint, "practice", boss=2)
        second = services.template(actor, blueprint, "practice")
        state = services.state_for(actor)
        self.assertNotIn(str(actor.pk), state["participants"])
        self.assertEqual(state["participants"][str(first.pk)]["max_hp"], 200)
        self.assertEqual(state["templates"]["practice"], [blueprint.pk, blueprint.pk])
        services.auto_batch(actor, [second, actor, first])
        state = services.state_for(actor)
        self.assertEqual(len(state["participants"][str(target.pk)]["incoming"]), 2)
        self.assertEqual(npcs.record_for(first).controller_id, None)
        with self.assertRaisesRegex(ValueError, "control"):
            services.auto_act(target, subject=first)
        with override_settings(NPCS_COMBAT_PROFILES_REVEALED=True):
            npcs.edit_profile(actor, blueprint, {"boss_check_schedule": [2]})
        with self.assertRaisesRegex(ValueError, "not supported"):
            services.template(actor, blueprint, "practice")

    def test_combat_guide_renders_and_runtime_hide_applies(self):
        if not apps.is_installed("evennia_guides"):
            self.skipTest("optional guides partner absent")
        from django.test import Client

        response = Client().get("/guide/combat/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Consent and corrections", response.content.decode())
        with override_settings(RP_COMBAT_REVEALED=False):
            for key in ("combat", "combat-moves", "combat-storytelling"):
                self.assertEqual(Client().get(f"/guide/{key}/").status_code, 404)
