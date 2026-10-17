# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Actual host display, build locks, outfits, market transfer and optional partners."""

from copy import deepcopy

from django.apps import apps
from django.core.management import call_command
from django.test import override_settings
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaTest
from evennia_rp_crafting import states
from evennia_rp_crafting.errors import CraftingError
from evennia_rp_crafting.models import CraftRecord
from typeclasses.characters import Character


class StateSeams(EvenniaTest):
    character_typeclass = Character

    def test_seeded_cloak_state_survives_outfit_changes_and_a_real_market_sale(self):
        if not apps.is_installed("evennia_rp_equipment"):
            self.skipTest("Equipment absent")
        from evennia_rp_equipment import outfits
        from evennia_rp_equipment import services as gear

        from world.sandbox.crafting import CLOAK_NAME

        call_command("seed_sandbox", verbosity=0)
        cloak = ObjectDB.objects.get(db_key=CLOAK_NAME)
        cloak.move_to(self.char1, quiet=True)
        record = cloak.craft_record
        original = deepcopy(record.prose)
        states.select(self.char1, cloak, "hood up")
        gear.wear(self.char1, cloak)
        outfits.save(self.char1, "Hooded")
        self.assertIn("hood raised", self.char1.get_display_desc(self.char2))
        gear.remove(self.char1, cloak)
        outfits.apply(self.char1, "Hooded")
        self.assertIn("hood raised", self.char1.get_display_desc(self.char2))
        gear.remove(self.char1, cloak)
        if apps.is_installed("evennia_economy"):
            from evennia_economy.services import credit
            from evennia_economy.stalls import buy, claim, list_stock

            credit(self.char2, 20)
            self.room1.tags.add("market", category="rp_economy")
            stall = claim(self.char1)
            listing = list_stock(
                self.char1, stall.pk, [{"kind": "item", "key": str(cloak.pk), "quantity": 1}], 10
            )
            with self.captureOnCommitCallbacks(execute=True):
                buy(self.char2, listing.pk)
        else:
            cloak.move_to(self.char2, quiet=True, move_type="give")
        self.assertEqual(cloak.location, self.char2)
        cloak.attributes.reset_cache()
        self.assertEqual(states.current(cloak, states.configuration(cloak)), "hood up")
        states.select(self.char2, cloak, "hood down")
        self.assertEqual(CraftRecord.objects.get(pk=record.pk).prose, original)

    def test_real_chargen_lock_blocks_worn_selection_until_unlock(self):
        if not apps.is_installed("evennia_rp_equipment"):
            self.skipTest("Equipment absent")
        from evennia_rp_chargen import locks
        from evennia_rp_chargen import services as chargen
        from evennia_rp_chargen.stats import StatHandler
        from evennia_rp_equipment import services as gear

        from evennia_rp_rules.ruleset import reset_ruleset_cache
        from evennia_rp_rules.testing import TEST_RULESET
        from world.sandbox.crafting import CLOAK_NAME

        call_command("seed_sandbox", verbosity=0)
        cloak = ObjectDB.objects.get(db_key=CLOAK_NAME)
        cloak.move_to(self.char1, quiet=True)
        with override_settings(
            RP_RULES_RULESET=TEST_RULESET, RP_CHARGEN_LOCK_SCOPES=("pips", "loadout")
        ):
            reset_ruleset_cache()
            self.addCleanup(reset_ruleset_cache)
            chargen.ensure_build(self.char1)
            handler = StatHandler(self.char1)
            for key in ("brawn", "brains", "charm"):
                handler.set(key, handler.ruleset.parse_rating("Low"))
            chargen.finalize(self.char1)
            gear.wear(self.char1, cloak)
            locks.lock(self.char1)
            with self.assertRaises(CraftingError):
                states.select(self.char1, cloak, "hood up")
            locks.unlock(self.char1)
            states.select(self.char1, cloak, "hood up")
            self.assertIn("hood raised", self.char1.get_display_desc(self.char2))
