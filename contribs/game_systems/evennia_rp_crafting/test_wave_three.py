# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Consent, atomic rollback, layer history and owner-directed companion seams."""

from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from django.utils import timezone
from evennia.objects.objects import DefaultCharacter, DefaultExit, DefaultObject
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from . import companions, conf, modifiers, services
from .errors import CraftingError
from .models import CompanionState, ModificationLayer, ModificationOffer, NicheDefinition
from .tests import CraftingFixture
from .typeclasses import ModificationDisplayMixin
from .wave_three_commands import CmdModify, CmdPet

HAS_ECONOMY = apps.is_installed("evennia_economy")


class LayeredObject(ModificationDisplayMixin, DefaultObject):
    pass


class CompanionOwner(companions.CompanionCharacterMixin, DefaultCharacter):
    pass


class ClosedRoute(DefaultExit):
    def at_traverse(self, traversing_object, target_location, **kwargs):
        return False


class WaveThreeFixture(CraftingFixture):
    def setUp(self):
        super().setUp()
        overrides = override_settings(
            RP_CRAFTING_WAVE_THREE_REVEALED=True,
            RP_CRAFTING_WAVE_TWO_REVEALED=True,
            RP_CRAFTING_COMBINATIONS=conf.DEFAULT_COMBINATIONS,
            LINKS_ROOM_LIVE=None,
        )
        overrides.enable()
        self.addCleanup(overrides.disable)
        NicheDefinition.objects.create(
            key="layers",
            name="Layer maker",
            behaviours=[
                "modifier_aura",
                "modifier_mark",
                "modifier_dye",
                "modifier_engrave",
                "modifier_undo",
            ],
            input_categories=["materials", "essences"],
            unlock_resources={"materials": 3},
            unlock_money=0,
        )
        NicheDefinition.objects.create(
            key="pets",
            name="Companion Maker",
            behaviours=["companion"],
            input_categories=["materials", "essences"],
            unlock_resources={"materials": 3},
            unlock_money=0,
        )
        self.unlock("pets")
        self.item = create_object(LayeredObject, key="a keepsake", location=self.char2)
        self.item.db.desc = "Original description."
        if HAS_ECONOMY:
            from evennia_economy.services import credit

            credit(self.char2, 100)
            self.unlock("layers")

    def offer(self, **changes):
        params = dict(
            maker=self.char1,
            customer=self.char2,
            target=self.item,
            niche_key="layers",
            modifier_key="modifier_aura",
            configuration={"line": "A silver shimmer."},
            selected={"spark": 1},
            commission=30,
        )
        return modifiers.propose(**(params | changes))

    def pet(self, **config):
        return services.craft(
            self.char1,
            "pets",
            "companion",
            "a brass bird",
            "A clockwork bird.",
            config,
            {"wood": 1, **({"spark": 1} if config.get("ambient") else {})},
        )


@skipUnless(HAS_ECONOMY, "Economy absent: services unavailable")
class ModifierTests(WaveThreeFixture, EvenniaTest):
    def test_consent_payment_resources_and_layer_commit_once(self):
        from evennia_economy.services import balance

        before = (balance(self.char1), balance(self.char2), self.held("spark"))
        offer = self.offer()
        self.assertEqual((balance(self.char1), balance(self.char2), self.held("spark")), before)
        self.assertFalse(ModificationLayer.objects.exists())
        modifiers.accept(self.char2, offer.pk)
        self.assertEqual(
            (balance(self.char1), balance(self.char2), self.held("spark")),
            (before[0] + 30, before[1] - 30, before[2] - 1),
        )
        self.assertEqual(self.item.db.desc, "Original description.")
        self.assertIn("A silver shimmer", self.item.get_display_desc(self.char2))
        with self.assertRaises(ValueError):
            modifiers.accept(self.char2, offer.pk)
        self.assertEqual(ModificationLayer.objects.count(), 1)

    def test_changed_base_or_target_ownership_refuses_without_spending(self):
        offer = self.offer()
        self.item.db.desc = "A changed description."
        before = self.held("spark")
        with self.assertRaisesMessage(CraftingError, "changed"):
            modifiers.accept(self.char2, offer.pk)
        self.assertEqual(self.held("spark"), before)
        self.item.db.desc = "Original description."
        self.item.move_to(self.char1, quiet=True)
        with self.assertRaisesMessage(CraftingError, "own"):
            modifiers.accept(self.char2, offer.pk)
        self.assertFalse(ModificationLayer.objects.exists())

    def test_payment_failure_rolls_back_applied_layer_and_resources(self):
        from evennia_economy.services import balance

        offer = self.offer()
        before = (balance(self.char1), balance(self.char2), self.held("spark"))
        with (
            patch(
                "evennia_economy.exchange.journal", side_effect=RuntimeError("journal unavailable")
            ),
            self.assertRaisesMessage(RuntimeError, "journal unavailable"),
        ):
            modifiers.accept(self.char2, offer.pk)
        self.assertEqual((balance(self.char1), balance(self.char2), self.held("spark")), before)
        self.assertFalse(ModificationLayer.objects.exists())
        self.assertIsNone(ModificationOffer.objects.get(pk=offer.pk).applied_at)

    def test_hiding_replacement_and_selected_undo_preserve_history(self):
        first = self.offer()
        modifiers.accept(self.char2, first.pk)
        layer = ModificationLayer.objects.get(service=first)
        with self.assertRaises(CraftingError):
            modifiers.set_hidden(self.char1, layer.pk, True)
        modifiers.set_hidden(self.char2, layer.pk, True)
        self.assertEqual(modifiers.display(self.item), "")
        modifiers.set_hidden(self.char2, layer.pk, False)
        with self.assertRaisesMessage(CraftingError, "replace"):
            self.offer()
        second = self.offer(configuration={"line": "A golden shimmer.", "layer_id": layer.pk})
        modifiers.accept(self.char2, second.pk)
        layer.refresh_from_db()
        self.assertEqual(layer.removed_by_id, second.pk)
        active = ModificationLayer.objects.get(service=second)
        undo = self.offer(modifier_key="modifier_undo", configuration={"layer_id": active.pk})
        modifiers.accept(self.char2, undo.pk)
        self.assertEqual(modifiers.display(self.item), "")
        self.assertEqual(self.item.db.desc, "Original description.")
        self.assertEqual(ModificationLayer.objects.count(), 2)

    def test_cancel_expiry_wrong_customer_freeze_and_fee_changes(self):
        offer = self.offer()
        with self.assertRaises(CraftingError):
            modifiers.accept(self.char1, offer.pk)
        with override_settings(RP_CRAFTING_FROZEN=True), self.assertRaises(CraftingError):
            modifiers.accept(self.char2, offer.pk)
        with (
            override_settings(RP_ECONOMY_FEE_CRAFT=5),
            self.assertRaisesMessage(CraftingError, "fee changed"),
        ):
            modifiers.accept(self.char2, offer.pk)
        with (
            override_settings(RP_ECONOMY_FEE_TRADE=5),
            self.assertRaisesMessage(CraftingError, "trade fee changed"),
        ):
            modifiers.accept(self.char2, offer.pk)
        modifiers.cancel(self.char2, offer.pk)
        with self.assertRaises(ValueError):
            modifiers.accept(self.char2, offer.pk)
        next_offer = self.offer()
        ModificationOffer.objects.filter(pk=next_offer.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(CraftingError):
            modifiers.accept(self.char2, next_offer.pk)

    def test_service_asset_cannot_be_reoffered_to_bypass_price(self):
        from evennia_economy.exchange import accept_offer, create_offer, give

        offer = self.offer()
        asset = [{"kind": "service", "key": str(offer.pk), "quantity": 1}]
        impostor = create_offer(self.char1, self.char2, asset)
        with self.assertRaisesMessage(CraftingError, "original service"):
            accept_offer(self.char2, impostor.pk)
        with self.assertRaises(CraftingError):
            give(self.char1, self.char2, asset)
        self.assertFalse(ModificationLayer.objects.exists())

    def test_self_service_still_requires_acceptance_and_mark_survives_description_edit(self):
        offer = self.offer(
            customer=self.char1, target=self.char1, modifier_key="modifier_mark", commission=0
        )
        self.assertFalse(ModificationLayer.objects.exists())
        modifiers.accept(self.char1, offer.pk)
        self.char1.db.desc = "New base."
        self.assertIn("silver shimmer", modifiers.display(self.char1))

    def test_host_can_require_specific_undoing_resource_keys(self):
        with (
            override_settings(
                RP_CRAFTING_MODIFIER_RESOURCE_KEYS={"modifier_aura": ["other-essence"]}
            ),
            self.assertRaisesMessage(CraftingError, "resource keys"),
        ):
            self.offer()

    def test_quoted_trade_and_craft_fees_are_paid_atomically(self):
        from evennia_economy.services import balance

        before = (balance(self.char1), balance(self.char2))
        with override_settings(RP_ECONOMY_FEE_CRAFT=2, RP_ECONOMY_FEE_TRADE=3):
            offer = self.offer()
            self.assertEqual(offer.snapshot["trade_fees"], {"maker": 3, "customer": 3})
            modifiers.accept(self.char2, offer.pk)
        self.assertEqual(
            (balance(self.char1), balance(self.char2)), (before[0] + 25, before[1] - 33)
        )


class CompanionTests(WaveThreeFixture, EvenniaTest):
    character_typeclass = CompanionOwner

    def test_follow_does_not_bypass_a_host_exit_traversal_hook(self):
        for path in self.room1.exits:
            path.destination = None
        create_object(ClosedRoute, key="closed route", location=self.room1, destination=self.room2)
        pet = self.pet()
        companions.set_mode(self.char1, pet, "follow")
        self.char1.move_to(self.room2, quiet=True)
        self.assertEqual(pet.location, self.room1)

    def test_follow_stay_and_blocked_exit(self):
        pet = self.pet()
        create_object(
            "evennia.objects.objects.DefaultExit",
            key="north",
            location=self.room1,
            destination=self.room2,
        )
        companions.set_mode(self.char1, pet, "follow")
        self.char1.move_to(self.room2, quiet=True)
        self.assertEqual(pet.location, self.room2)
        companions.set_mode(self.char1, pet, "stay")
        self.char1.move_to(self.room1, quiet=True)
        self.assertEqual(pet.location, self.room2)
        pet.move_to(self.char1, quiet=True)
        companions.set_mode(self.char1, pet, "follow")
        for path in self.room1.exits:
            if path.destination == self.room2:
                path.locks.add("traverse:false()")
        self.char1.move_to(self.room2, quiet=True)
        self.assertEqual(pet.location, self.room1)

    def test_handoff_changes_owner_and_old_owner_loses_control(self):
        pet = self.pet()
        pet.move_to(self.char2, quiet=True, move_type="give")
        self.assertEqual(CompanionState.objects.get(item=pet).owner_id, self.char2.pk)
        self.assertEqual(pet.home, self.char2)
        with self.assertRaises(CraftingError):
            companions.set_mode(self.char1, pet, "follow")
        companions.set_mode(self.char2, pet, "stay")
        self.assertFalse(pet.at_pre_get(self.char1))

    def test_companion_cannot_hold_items(self):
        pet = self.pet()
        before = self.item.location
        # Refused before arrival, so give/put report failure instead of success.
        self.assertFalse(self.item.move_to(pet, quiet=True))
        self.assertEqual(self.item.location, before)

    def test_only_owner_written_pose_enters_posing(self):
        pet = self.pet()
        with patch.object(self.char1, "record_pose", create=True) as recorder:
            companions.pose(self.char1, pet, "bows politely.")
        recorder.assert_called_once_with("a brass bird bows politely.", pose_type="emit")

    def test_tricks_reach_the_room_without_accessibility(self):
        from .wave_two import activate

        NicheDefinition.objects.create(
            key="tricks",
            name="Trick maker",
            behaviours=["activatable"],
            input_categories=["materials"],
            unlock_resources={"materials": 3},
            unlock_money=0,
        )
        self.unlock("tricks")
        pet = services.craft(
            self.char1,
            "pets",
            "companion",
            "a quiet bird",
            "A brass bird.",
            {},
            {"wood": 2},
            verbs=[
                {
                    "key": "activatable",
                    "niche": "tricks",
                    "configuration": {"modes": {"bow": ["The bird bows."]}},
                }
            ],
        )
        installed = apps.is_installed
        received = []
        with (
            patch.object(
                apps,
                "is_installed",
                lambda name: name != "evennia_accessibility" and installed(name),
            ),
            patch.object(
                DefaultCharacter,
                "msg",
                lambda target, text=None, **kwargs: received.append((target.pk, str(text))),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            activate(self.char1, pet, "bow")
        self.assertIn(self.char2.pk, {pk for pk, text in received if "The bird bows." in text})

    def test_arrivals_share_the_room_event_limit(self):
        if not apps.is_installed("evennia_accessibility"):
            self.skipTest("Accessibility absent: arrivals unavailable")
        for source, destination in ((self.room1, self.room2), (self.room2, self.room1)):
            create_object(DefaultExit, key="path", location=source, destination=destination)
        pet = self.pet(arrival="A brass bird flutters in.")
        companions.set_mode(self.char1, pet, "follow")
        received = []
        with (
            patch("evennia_accessibility.mutes_ambient", return_value=False),
            patch.object(
                DefaultCharacter,
                "msg",
                lambda target, text=None, **kwargs: received.append((target.pk, str(text))),
            ),
        ):
            for room in (self.room2, self.room1, self.room2):
                self.char1.move_to(room, quiet=True)
        self.assertEqual(pet.location, self.room2)
        # The return within the room cooldown moves the bird without another EVENT.
        arrivals = [pk for pk, text in received if "flutters in" in text]
        self.assertEqual(arrivals.count(self.char1.pk), 2)

    def test_hidden_wave_blocks_actions_and_absent_economy_keeps_companions(self):
        pet = self.pet()
        with (
            override_settings(RP_CRAFTING_WAVE_THREE_REVEALED=False),
            self.assertRaises(CraftingError),
        ):
            companions.set_mode(self.char1, pet, "follow")
        if not HAS_ECONOMY:
            with self.assertRaisesMessage(CraftingError, "require Economy"):
                self.offer()


class WaveThreeCommandTests(WaveThreeFixture, EvenniaCommandTest):
    def test_companion_commands_are_registered_and_have_plain_output(self):
        pet = self.pet()
        self.call(CmdPet(), f"/stay {pet.key}", "a brass bird: stay.")
        self.call(CmdPet(), "", "Your Companions:")

    @skipUnless(HAS_ECONOMY, "Economy absent")
    def test_modify_offer_accept_and_visibility(self):
        self.call(
            CmdModify(),
            f"/new {self.char2.key}/{self.item.key}=layers/modifier_aura",
            "Service draft",
        )
        self.call(CmdModify(), "/line A silver shimmer; motes drift.")
        self.call(CmdModify(), "/resources 1 spark")
        self.call(CmdModify(), "/price 30")
        self.call(CmdModify(), "/offer", "service #")
        row = ModificationOffer.objects.latest("pk")
        self.call(
            CmdModify(), f"/accept {row.pk}", f"Service #{row.pk} completed.", caller=self.char2
        )
        layer = ModificationLayer.objects.get(service=row)
        self.assertEqual(layer.text, "A silver shimmer; motes drift.")
        self.call(
            CmdModify(), f"/hide {layer.pk}", f"Layer #{layer.pk}: hidden (OOC).", caller=self.char2
        )
        self.call(
            CmdModify(),
            f"/new {self.char2.key}/{self.item.key}=layers/modifier_aura",
            "Service draft",
        )
        self.call(CmdModify(), "/line A new; golden shimmer.")
        self.call(CmdModify(), "/resources 1 spark")
        self.call(CmdModify(), "/price 10")
        self.call(CmdModify(), f"/replace {layer.pk}")
        self.call(CmdModify(), "/offer", "service #")
        replacement = ModificationOffer.objects.latest("pk")
        self.assertEqual(
            replacement.configuration, {"line": "A new; golden shimmer.", "layer_id": layer.pk}
        )
