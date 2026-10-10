# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Actual host commands, cap collectors, market sales and reseed recovery."""

from django.apps import apps
from django.core.management import call_command
from evennia.utils.test_resources import EvenniaTest
from evennia_rp_crafting import services
from evennia_rp_crafting.models import CraftRecord, NicheDefinition, Workshop
from typeclasses.characters import Character
from typeclasses.rooms import Room


class CraftingSeams(EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def test_host_cmdset_exposes_player_and_staff_crafting_commands(self):
        from commands.default_cmdsets import CharacterCmdSet

        keys = {command.key for command in CharacterCmdSet().commands}
        self.assertTrue({"+workshop", "+craft", "read", "use", "+crafting"} <= keys)

    def test_seed_reseed_preserves_player_workshop_and_restores_demonstration_items(self):
        call_command("seed_sandbox", verbosity=0)
        self.assertTrue(Workshop.objects.exists())
        self.assertTrue(CraftRecord.objects.filter(behaviour="readable").exists())
        from evennia_rp_resources.services import grant

        grant(self.char1, "timber", 3, "staff")
        if apps.is_installed("evennia_economy"):
            from evennia_economy.services import credit

            credit(self.char1, 100)
        services.unlock(self.char1, "writing", {"timber": 3})
        call_command("seed_sandbox", verbosity=0)
        self.assertTrue(Workshop.objects.filter(character=self.char1).exists())
        self.assertEqual(NicheDefinition.objects.count(), 6)
        self.assertTrue(CraftRecord.objects.filter(behaviour="readable").exists())

    def test_real_collectors_raise_caps_and_lower_them_on_abandonment(self):
        from evennia_rp_resources.batch import holdings_cap
        from evennia_rp_resources.catalog import seed_catalog as seed_resources
        from evennia_rp_resources.services import grant

        from evennia_links.runtime import get

        seed_resources()
        from evennia_rp_crafting.catalog import seed_catalog

        seed_catalog()
        grant(self.char1, "timber", 3, "staff")
        if apps.is_installed("evennia_economy"):
            from evennia_economy.batch import money_cap
            from evennia_economy.services import credit

            credit(self.char1, 100)
            money_before = money_cap(self.char1)
        resources_before = holdings_cap(self.char1)
        services.unlock(self.char1, "writing", {"timber": 3})
        self.assertGreaterEqual(
            holdings_cap(self.char1), resources_before + get("RP_CRAFTING_RESOURCE_CAP_RAISE")
        )
        if apps.is_installed("evennia_economy"):
            self.assertGreater(money_cap(self.char1), money_before)
        services.abandon(self.char1, "writing")
        self.assertEqual(holdings_cap(self.char1), resources_before)

    def test_host_consumable_uses_real_typeclass_guards_and_retains_review(self):
        from unittest.mock import patch

        from evennia.objects.models import ObjectDB
        from evennia_rp_crafting.events import use
        from evennia_rp_crafting.models import EventUse
        from typeclasses.craft_items import CraftedConsumable

        call_command("seed_sandbox", verbosity=0)
        item = ObjectDB.objects.get(db_key="a sample spice cake")
        self.assertIsInstance(item, CraftedConsumable)
        item.move_to(self.char1, quiet=True)
        record = item.craft_record
        item_id = item.pk
        with patch.object(self.char2, "msg") as msg, self.captureOnCommitCallbacks(execute=True):
            use(self.char1, item)
        self.assertIn("<EVENT>", msg.call_args.args[0])
        self.assertFalse(ObjectDB.objects.filter(pk=item_id).exists())
        self.assertTrue(CraftRecord.objects.filter(pk=record.pk).exists())
        self.assertTrue(EventUse.objects.filter(craft=record).exists())

    def test_crafted_item_sells_through_real_stall_without_losing_provenance(self):
        if not apps.is_installed("evennia_economy"):
            self.skipTest("economy absent")
        from evennia_economy.services import credit
        from evennia_economy.stalls import buy, claim, directory, list_stock
        from evennia_rp_crafting.catalog import seed_catalog
        from evennia_rp_resources.catalog import seed_catalog as seed_resources
        from evennia_rp_resources.services import grant

        seed_resources()
        seed_catalog()
        grant(self.char1, "timber", 4, "staff")
        credit(self.char1, 100)
        credit(self.char2, 20)
        services.unlock(self.char1, "writing", {"timber": 3})
        book = services.craft(
            self.char1,
            "writing",
            "readable",
            "a trade journal",
            "A bound journal.",
            {"text": "Terms of sale."},
            {"timber": 1},
        )
        self.room1.tags.add("market", category="rp_economy")
        store = claim(self.char1, name="Book counter")
        with self.captureOnCommitCallbacks(execute=True):
            listing = list_stock(
                self.char1, store.pk, [{"kind": "item", "key": str(book.pk), "quantity": 1}], 10
            )
        self.assertEqual([row.pk for row, _ in directory(self.char2, "Scribe")], [store.pk])
        with self.captureOnCommitCallbacks(execute=True):
            buy(self.char2, listing.pk)
        self.assertEqual(book.location, self.char2)
        self.assertIn("Scribe", book.get_display_provenance())
        self.assertEqual(book.read(self.char2), "Terms of sale.")
