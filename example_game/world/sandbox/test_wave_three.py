# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Wave-three services and Companions under real reference-game partners."""

from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.core.management import call_command
from evennia.objects.models import ObjectDB
from evennia.objects.objects import DefaultCharacter
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from evennia_rp_crafting import companions, modifiers, services
from evennia_rp_crafting.models import ActivationUse, CompanionState, ModificationLayer
from evennia_rp_crafting.test_wave_three import WaveThreeFixture
from evennia_rp_crafting.wave_two import activate
from typeclasses.characters import Character
from typeclasses.objects import Object
from typeclasses.rooms import Room


class WaveThreeSeams(WaveThreeFixture, EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    @skipUnless(apps.is_installed("evennia_economy"), "Economy absent")
    def test_ordinary_and_market_handoffs_update_companion_owner(self):
        from evennia_economy.exchange import accept_offer, create_offer, give

        pet = self.pet()
        with self.captureOnCommitCallbacks(execute=True):
            give(self.char1, self.char2, [{"kind": "item", "key": str(pet.pk), "quantity": 1}])
        self.assertEqual(CompanionState.objects.get(item=pet).owner_id, self.char2.pk)
        with self.captureOnCommitCallbacks(execute=True):
            offer = create_offer(
                self.char2,
                self.char1,
                [{"kind": "item", "key": str(pet.pk), "quantity": 1}],
                [{"kind": "money", "key": "", "quantity": 10}],
            )
            accept_offer(self.char1, offer.pk)
        self.assertEqual(CompanionState.objects.get(item=pet).owner_id, self.char1.pk)
        self.assertEqual(CompanionState.objects.get(item=pet).mode, "stay")
        from evennia_economy.stalls import buy, claim, list_stock

        self.room1.tags.add("market", category="rp_economy")
        store = claim(self.char1)
        with self.captureOnCommitCallbacks(execute=True):
            listing = list_stock(
                self.char1, store.pk, [{"kind": "item", "key": str(pet.pk), "quantity": 1}], 10
            )
        with self.captureOnCommitCallbacks(execute=True):
            buy(self.char2, listing.pk)
        self.assertEqual(CompanionState.objects.get(item=pet).owner_id, self.char2.pk)
        self.assertEqual(pet.home, self.char2)

    @skipUnless(apps.is_installed("evennia_economy"), "Economy absent")
    def test_plain_objects_and_character_marks_render_without_base_edits(self):
        item = create_object(Object, key="a plain heirloom", location=self.char2)
        item.db.desc = "An old heirloom."
        offer = self.offer(target=item)
        modifiers.accept(self.char2, offer.pk)
        self.assertEqual(item.db.desc, "An old heirloom.")
        self.assertIn("A silver shimmer.", item.return_appearance(self.char1))
        mark = self.offer(target=self.char2, modifier_key="modifier_mark")
        modifiers.accept(self.char2, mark.pk)
        self.char2.db.desc = "A newly written description."
        self.assertIn("A silver shimmer.", self.char2.get_display_desc(self.char1))

    @skipUnless(
        apps.is_installed("evennia_economy") and apps.is_installed("evennia_rp_equipment"),
        "Equipment/Economy absent",
    )
    def test_worn_plain_gear_keeps_requirements_and_sealed_prose(self):
        from evennia_rp_equipment.typeclasses import Equipment

        item = create_object(Equipment, key="an heirloom cloak", location=self.char2)
        item.db.desc = "Original cloak prose."
        item.worn_line = "a blue cloak"
        item.requirement_data = []
        item.sealed = True
        item.tags.add("worn", category="rp_equipment")
        offer = self.offer(target=item)
        modifiers.accept(self.char2, offer.pk)
        self.assertTrue(item.sealed)
        self.assertEqual(item.requirement_data, [])
        self.assertEqual(item.db.desc, "Original cloak prose.")
        self.assertIn("A silver shimmer", self.char2.get_display_desc(self.char1))

    @skipUnless(apps.is_installed("evennia_scenes"), "Scenes absent")
    def test_owner_pose_is_logged_and_updates_owner_pose_state(self):
        from evennia_scenes.models import LogEntry, Scene, SceneParticipant

        scene = Scene.objects.create(title="A bird's greeting", room=self.room1, creator=self.char1)
        self.room1.active_scene_id = scene.pk
        pet = self.pet()
        with patch.object(self.char1, "record_pose", wraps=self.char1.record_pose) as recorded:
            companions.pose(self.char1, pet, "bows politely.")
        recorded.assert_called_once_with("a brass bird bows politely.", pose_type="emit")
        self.assertEqual(self.char1.last_pose_text, "a brass bird bows politely.")
        log = LogEntry.objects.get(scene=scene)
        self.assertEqual(log.author_id, self.char1.pk)
        self.assertEqual(log.log_type, "emit")
        self.assertEqual(
            SceneParticipant.objects.get(scene=scene, character=self.char1).pose_count, 1
        )

    @skipUnless(apps.is_installed("evennia_accessibility"), "Accessibility absent")
    def test_trick_output_is_muted_ignored_and_never_owner_activity(self):
        from evennia_rp_crafting.models import NicheDefinition

        NicheDefinition.objects.create(
            key="music",
            name="Artisan",
            behaviours=["activatable"],
            input_categories=["materials"],
            unlock_resources={"materials": 3},
            unlock_money=0,
        )
        self.unlock("music")
        pet = services.craft(
            self.char1,
            "pets",
            "companion",
            "a trick bird",
            "A brass bird.",
            {},
            {"wood": 2},
            verbs=[
                {
                    "key": "activatable",
                    "niche": "music",
                    "configuration": {"modes": {"bow": ["The bird bows."]}},
                }
            ],
        )
        companions.set_mode(self.char1, pet, "stay")
        self.account2.db.ignore_list = [self.account.pk]
        before = self.char1.last_pose_time
        if apps.is_installed("evennia_scenes"):
            from evennia_scenes.models import LogEntry, Scene, SceneParticipant

            scene = Scene.objects.create(title="A trick", room=self.room1, creator=self.char2)
        received = []
        with (
            patch.object(
                DefaultCharacter,
                "msg",
                lambda target, text=None, **kwargs: received.append((target.pk, text)),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            activate(self.char1, pet, "bow")
        self.assertFalse(any(target == self.char2.pk for target, _ in received))
        self.assertFalse(pet.access(self.char2, "view"))
        self.assertEqual(self.char1.last_pose_time, before)
        self.assertEqual(ActivationUse.objects.count(), 1)
        if apps.is_installed("evennia_scenes"):
            self.assertEqual(LogEntry.objects.get(scene=scene).author, self.char1)
            self.assertFalse(SceneParticipant.objects.filter(scene=scene).exists())

    @skipUnless(
        apps.is_installed("evennia_scenes") and apps.is_installed("evennia_accessibility"),
        "Scenes and Accessibility required",
    )
    def test_transferred_companion_ambient_logs_current_owner_without_pose_counts(self):
        from evennia import SESSION_HANDLER
        from evennia.server.serversession import ServerSession
        from evennia_scenes.models import LogEntry, Scene, SceneParticipant

        # EvenniaTest connects only the first account. The new owner must be
        # online: offline companions correctly remain silent.
        with patch.dict(SESSION_HANDLER):
            dummy = ServerSession()
            dummy.init_session("telnet", ("localhost", "testmode"), SESSION_HANDLER)
            dummy.sessid = 2
            SESSION_HANDLER.portal_connect(dummy.get_sync_data())
            SESSION_HANDLER.login(
                SESSION_HANDLER.session_from_sessid(2), self.account2, testmode=True
            )
            self.char2.locks.add(f"puppet:pid({self.account2.pk})")
            self.account2.puppet_object(SESSION_HANDLER.session_from_sessid(2), self.char2)
            self.assertTrue(self.char2.has_account)
            pet = self.pet(ambient="A brass feather clicks.")
            pet.move_to(self.char2, quiet=True)
            companions.set_mode(self.char2, pet, "stay")
            self.account.db.ignore_list = [self.account2.pk]
            self.account.options.set("mute_ambient_effects", "False")
            scene = Scene.objects.create(
                title="A new companion owner", room=self.room1, creator=self.char1
            )
            before = self.char2.last_pose_time
            received = []
            with (
                patch.object(
                    DefaultCharacter,
                    "msg",
                    lambda target, text=None, **kw: received.append(target.pk),
                ),
                self.captureOnCommitCallbacks(execute=True),
            ):
                self.assertEqual(companions.ambient_tick(), 1)
            self.assertNotIn(self.char1.pk, received)
            self.assertEqual(LogEntry.objects.get(scene=scene).author, self.char2)
            self.assertFalse(SceneParticipant.objects.filter(scene=scene).exists())
            self.assertEqual(self.char2.last_pose_time, before)

    @skipUnless(
        apps.is_installed("evennia_scenes") and apps.is_installed("evennia_accessibility"),
        "Scenes and Accessibility required",
    )
    def test_companion_arrival_is_ignored_but_logged_without_participation(self):
        from evennia_scenes.models import LogEntry, Scene, SceneParticipant

        pet = self.pet(arrival="A brass bird flutters in.")
        companions.set_mode(self.char1, pet, "follow")
        self.char2.move_to(self.room2, quiet=True)
        self.account2.db.ignore_list = [self.account.pk]
        self.account2.options.set("mute_ambient_effects", "False")
        scene = Scene.objects.create(title="A bird arrives", room=self.room2, creator=self.char2)
        received = []
        with patch.object(
            DefaultCharacter,
            "msg",
            lambda target, text=None, **kw: received.append((target.pk, text)),
        ):
            self.char1.move_to(self.room2, quiet=True)
        self.assertEqual(pet.location, self.room2)
        self.assertFalse(
            any(pk == self.char2.pk and "<EVENT>" in str(text) for pk, text in received)
        )
        self.assertEqual(LogEntry.objects.get(scene=scene).author, self.char1)
        self.assertFalse(SceneParticipant.objects.filter(scene=scene).exists())

    @skipUnless(apps.is_installed("evennia_accessibility"), "Accessibility absent")
    def test_ambients_pause_offline_and_during_real_fights(self):
        pet = self.pet(ambient="A brass feather clicks.")
        companions.set_mode(self.char1, pet, "stay")
        with patch.object(
            DefaultCharacter, "has_account", new_callable=lambda: property(lambda obj: False)
        ):
            self.assertEqual(companions.ambient_tick(), 0)
        if apps.is_installed("evennia_rp_combat"):
            from evennia_rp_combat.models import Fight

            fight = Fight.objects.create(room=self.room1, status=Fight.OPEN, state={})
            self.assertEqual(companions.ambient_tick(), 0)
            fight.status = Fight.ENDED
            fight.save(update_fields=["status"])
        self.assertEqual(companions.ambient_tick(), 1)
        self.assertEqual(companions.ambient_tick(), 0)


class WaveThreeSeedSeams(EvenniaTest):
    def test_seed_exposes_companion_and_modifier_and_reseed_keeps_history(self):
        from world.sandbox import crafting

        call_command("seed_sandbox", verbosity=0)
        pet = ObjectDB.objects.get(db_key=crafting.COMPANION_NAME)
        record = pet.craft_record
        self.assertEqual(CompanionState.objects.get(item=pet).mode, "stay")
        if apps.is_installed("evennia_economy"):
            self.assertTrue(ModificationLayer.objects.exists())
        call_command("seed_sandbox", verbosity=0)
        self.assertEqual(ObjectDB.objects.filter(db_key=crafting.COMPANION_NAME).count(), 1)
        from evennia_rp_crafting.models import CraftRecord

        self.assertTrue(CraftRecord.objects.filter(pk=record.pk).exists())


@skipUnless(apps.is_installed("evennia_economy"), "Economy absent")
class ModifierCommandSeams(WaveThreeFixture, EvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room

    def test_registered_draft_commands_commit_exact_service_on_host_objects(self):
        from commands.default_cmdsets import CharacterCmdSet
        from evennia_economy.services import balance
        from evennia_rp_crafting.models import ModificationOffer

        def command():
            return next(cmd for cmd in CharacterCmdSet().commands if cmd.key == "+modify")

        item = create_object(Object, key="a host heirloom", location=self.char2)
        item.db.desc = "Original host prose."
        before = (balance(self.char1), balance(self.char2), self.held("spark"))
        self.call(
            command(), f"/new #{self.char2.pk}/#{item.pk}=layers/modifier_aura", "Service draft"
        )
        self.call(command(), "/line A shimmer; gold = silver.", "Service draft")
        self.call(command(), "/resources 1 spark", "Service draft")
        self.call(command(), "/price 20", "Service draft")
        listing = self.call(command(), "")
        self.assertIn("Your recent services:", listing)
        self.assertIn("Service draft: a host heirloom.", listing)
        self.assertNotIn("A shimmer; gold = silver.", listing)
        proof = self.call(command(), "/proof")
        self.assertIn("A shimmer; gold = silver.", proof)
        self.assertNotIn("Your recent services:", proof)
        self.call(command(), "/offer/accept", "Use one switch")
        self.call(
            command(),
            f"/offer #{self.char2.pk}/#{item.pk}=layers/modifier_aura ; old ; spark:1 ; 20",
            "Usage:",
        )
        self.assertFalse(ModificationOffer.objects.exists())
        self.assertEqual((balance(self.char1), balance(self.char2), self.held("spark")), before)
        self.call(command(), "/offer", "service #")
        row = ModificationOffer.objects.get()
        self.assertEqual((balance(self.char1), balance(self.char2), self.held("spark")), before)
        self.call(command(), f"/accept {row.pk}", "Service #", caller=self.char2)
        self.assertEqual(item.db.desc, "Original host prose.")
        self.assertIn("A shimmer; gold = silver.", item.return_appearance(self.char1))
        self.assertEqual(
            ModificationLayer.objects.get(service=row).text, "A shimmer; gold = silver."
        )
        self.assertEqual(
            (balance(self.char1), balance(self.char2), self.held("spark")),
            (before[0] + 20, before[1] - 20, before[2] - 1),
        )

    def test_economy_cancellation_is_visible_and_can_be_closed_locally(self):
        from evennia_economy.exchange import cancel_offer
        from evennia_economy.models import Offer
        from evennia_rp_crafting.wave_three_commands import CmdModify

        row = self.offer()
        cancel_offer(self.char2, row.economy_offer_id)
        self.assertIn("[cancelled]", self.call(CmdModify(), "", caller=self.char2))
        self.call(
            CmdModify(), f"/cancel {row.pk}", f"Service #{row.pk} cancelled.", caller=self.char2
        )
        row.refresh_from_db()
        self.assertIsNotNone(row.cancelled_at)
        self.assertEqual(Offer.objects.get(pk=row.economy_offer_id).status, "cancelled")
