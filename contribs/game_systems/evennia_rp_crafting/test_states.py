# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Wearable states preserve immutable prose, guards and existing presentation."""

from copy import deepcopy
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest

from . import services, states
from .commands import DRAFT_KEY, CmdCraft, CraftingCmdSet
from .errors import CraftingError
from .models import CraftRecord
from .state_commands import CmdAdjust
from .tests import CraftingFixture

FACET = {
    "default": "down",
    "variants": {
        "down": {"worn_line": "a cloak, hood down"},
        "up": {"worn_line": "a cloak, hood up", "description": "A cloak with a raised hood."},
    },
}


class StateValidationTests(CraftingFixture, EvenniaCommandTest):
    def test_invalid_definitions_fail_without_payment_or_records(self):
        self.unlock()
        before = self.held(), CraftRecord.objects.count()
        for value in ({}, FACET):
            with self.assertRaisesMessage(CraftingError, "Wearable lifecycle"):
                self.book(facets={"states": value})
        self.assertEqual((self.held(), CraftRecord.objects.count()), before)
        for value in (
            {"default": "absent", "variants": FACET["variants"]},
            {"default": "x", "variants": {"x": {"slot": "head"}}},
            {"default": "x", "variants": {"x": {"worn_line": "|rforged"}}},
            {"default": "x", "variants": {"x": {"description": "two\nlines"}}},
            {"default": "x", "variants": {"x": {"worn_line": "x"}, "X": {"worn_line": "y"}}},
            {"default": "0", "variants": {str(i): {"worn_line": "x"} for i in range(9)}},
        ):
            with self.subTest(value=value), self.assertRaises(CraftingError):
                states.validate(value)

    def test_command_is_registered_even_without_equipment(self):
        self.assertIn("+adjust", {cmd.key for cmd in CraftingCmdSet().commands})

    def test_previously_crafted_states_render_without_equipment(self):
        # A persisted wearable must remain inspectable with its optional partner absent.
        self.unlock()
        item = self.book()
        row = item.craft_record
        prose = deepcopy(row.prose)
        prose["facets"] = {"states": FACET}
        CraftRecord.objects.filter(pk=row.pk).update(behaviour="wearable", verbs=[], prose=prose)
        item.swap_typeclass("evennia_rp_crafting.wearables.Wearable", clean_attributes=False)
        self.assertEqual(states.select(self.char1, item, "up"), "up")
        self.assertEqual(item.get_worn_line(self.char2), "a cloak, hood up")
        self.assertIn("raised hood", item.get_display_desc(self.char2))
        self.assertEqual(item.db.desc, "A bound notebook.")


@skipUnless(apps.is_installed("evennia_rp_equipment"), "Equipment absent")
class WearableStateTests(CraftingFixture, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.unlock("weaving")

    def cloak(self, **kwargs):
        return services.craft(
            self.char1,
            "weaving",
            "wearable",
            "state cloak",
            "Original cloak prose.",
            kwargs.pop("configuration", {"worn_line": "an ordinary cloak", "slot": "cloak"}),
            kwargs.pop("selected", {"wood": 3}),
            facets={"states": deepcopy(FACET)},
            **kwargs,
        )

    def test_default_selection_and_transfer_keep_record_requirements_and_base_prose(self):
        from evennia_rp_equipment import services as gear

        cloak = self.cloak()
        original = deepcopy(cloak.craft_record.prose)
        self.assertEqual(cloak.get_worn_line(self.char2), "a cloak, hood down")
        self.assertIn("Original cloak prose", cloak.get_display_desc(self.char2))
        self.assertEqual(cloak.craft_record.resources_spent, {"wood": 3})
        states.select(self.char1, cloak, "UP")
        cloak.attributes.reset_cache()
        self.assertEqual(states.current(cloak, FACET), "up")
        self.assertEqual(cloak.get_worn_line(self.char2), "a cloak, hood up")
        self.assertIn("raised hood", cloak.get_display_desc(self.char2))
        cloak.move_to(self.char2, quiet=True, move_type="give")
        self.assertTrue(cloak.sealed)
        self.assertEqual(states.current(cloak, FACET), "up")
        states.select(self.char2, cloak, "down")
        with self.assertRaises(gear.GearError):
            gear.set_worn_line(self.char2, cloak, "rewritten")
        self.assertEqual(cloak.db.desc, "Original cloak prose.")
        self.assertEqual(cloak.worn_line, "an ordinary cloak")
        self.assertEqual(CraftRecord.objects.get(pk=cloak.craft_record.pk).prose, original)

    def test_selected_state_keeps_aura_and_modifier_exactly_once(self):
        cloak = self.cloak(
            configuration={"worn_line": "base", "aura_line": "soft sparks"},
            selected={"wood": 3, "spark": 1},
        )
        states.select(self.char1, cloak, "up")
        with patch("evennia_rp_crafting.modifiers.display", return_value="A silver shimmer."):
            worn = cloak.get_worn_line(self.char2)
            desc = cloak.get_display_desc(self.char2)
        self.assertEqual(worn.count("A silver shimmer."), 1)
        self.assertEqual(desc.count("A silver shimmer."), 1)
        self.assertEqual(worn.count("soft sparks"), 1)
        self.assertIn("raised hood", desc)
        self.assertIn("Craft hallmark (OOC)", desc)

    def test_authority_locks_and_unknown_state_never_change_selection(self):
        cloak = self.cloak()
        for actor, key in ((self.char2, "up"), (self.char1, "missing")):
            with self.assertRaises(CraftingError):
                states.select(actor, cloak, key)
        cloak.locks.add("adjust:false()")
        with self.assertRaises(CraftingError):
            states.select(self.char1, cloak, "up")
        cloak.locks.add("adjust:all();view:false()")
        with self.assertRaises(CraftingError):
            states.select(self.char1, cloak, "up")
        self.assertEqual(states.current(cloak, FACET), "down")
        self.assertFalse(cloak.attributes.has(states.STATE_KEY, category=states.STATE_CATEGORY))

    def test_worn_build_lock_and_crafting_pause_refuse_selection(self):
        cloak = self.cloak()
        cloak.tags.add("worn", category="rp_equipment")
        with (
            patch("evennia_rp_chargen.locks.frozen", return_value=True),
            self.assertRaises(CraftingError),
        ):
            states.select(self.char1, cloak, "up")
        cloak.tags.remove("worn", category="rp_equipment")
        with patch("evennia_rp_chargen.locks.frozen", return_value=True):
            states.select(self.char1, cloak, "up")
        with override_settings(RP_CRAFTING_FROZEN=True), self.assertRaises(CraftingError):
            states.select(self.char1, cloak, "down")
        self.assertEqual(states.current(cloak, FACET), "up")

    def test_fresh_location_is_checked_after_cached_item_moves(self):
        cloak = self.cloak()
        ObjectDB.objects.filter(pk=cloak.pk).update(db_location_id=self.char2.pk)
        with self.assertRaisesMessage(CraftingError, "carrying"):
            states.select(self.char1, cloak, "up")

    def test_commands_edit_preview_clear_and_select_without_activity(self):
        for args in (
            "/new weaving/wearable = drafted cloak",
            "/desc = A cloak.",
            "/detail hem = Blue stitches line the hem.",
            "/sense touch = Soft woven cloth.",
            "/state down = a hooded cloak",
            "/state up = a raised hood",
            "/statedesc up = A raised hood.",
            "/defaultstate up",
            "/resources = wood:5",
        ):
            self.call(CmdCraft(), args, "Craft draft saved")
        preview = self.call(CmdCraft(), "", "Draft:")
        self.assertIn("a raised hood", preview)
        self.assertIn("5 materials", preview)
        self.call(CmdCraft(), "/finish", "You craft")
        item = ObjectDB.objects.get(db_key="drafted cloak")
        self.call(CmdAdjust(), item.key, "drafted cloak: up.")
        with patch.object(self.room1, "msg_contents") as room_output:
            self.call(CmdAdjust(), f"{item.key} = down", "You adjust")
        room_output.assert_not_called()
        self.assertEqual(states.current(item, FACET), "down")
        from .item_details import examine, sense

        self.assertEqual(item.craft_record.resources_spent, {"wood": 5})
        for selected in ("up", "down"):
            self.call(CmdAdjust(), f"{item.key} = {selected}", "You adjust")
            self.assertEqual(examine(self.char1, item, "hem"), "Blue stitches line the hem.")
            self.assertEqual(sense(self.char1, item, "touch"), "Soft woven cloth.")
        self.call(CmdCraft(), "/new weaving/wearable = plain", "Craft draft saved")
        self.call(CmdCraft(), "/state only = a cloak", "Craft draft saved")
        self.call(CmdCraft(), "/unstate only", "Craft draft saved")
        self.assertNotIn("states", self.char1.attributes.get(DRAFT_KEY)["facets"])

    def test_invalid_unit_cost_and_insufficient_payment_do_not_create_item(self):
        before = self.held(), CraftRecord.objects.count()
        with override_settings(RP_CRAFTING_STATE_UNIT_COST=0), self.assertRaises(CraftingError):
            self.cloak()
        with self.assertRaises(CraftingError):
            self.cloak(selected={"wood": 1})
        self.assertEqual((self.held(), CraftRecord.objects.count()), before)

    def test_selected_key_reads_committed_values_despite_a_stale_attribute_instance(self):
        cloak = self.cloak()
        states.select(self.char1, cloak, "up")
        self.assertEqual(
            cloak.attributes.get(states.STATE_KEY, category=states.STATE_CATEGORY), "up"
        )
        cloak.db_attributes.filter(
            db_key=states.STATE_KEY, db_category=states.STATE_CATEGORY
        ).update(db_value="down")
        self.assertEqual(
            cloak.attributes.get(states.STATE_KEY, category=states.STATE_CATEGORY), "up"
        )
        self.assertEqual(states.current(cloak, states.configuration(cloak)), "down")
        self.assertEqual(cloak.get_worn_line(self.char2), "a cloak, hood down")

    def test_stale_negative_cache_does_not_duplicate_the_selected_attribute(self):
        from evennia.typeclasses.attributes import AttributeHandler, ModelAttributeBackend

        cloak = self.cloak()
        self.assertIsNone(cloak.attributes.get(states.STATE_KEY, category=states.STATE_CATEGORY))
        # A separate handler models a worker committing after this reader cached absence.
        other_worker = AttributeHandler(cloak, ModelAttributeBackend)
        other_worker.add(states.STATE_KEY, "up", category=states.STATE_CATEGORY)
        self.assertIsNone(cloak.attributes.get(states.STATE_KEY, category=states.STATE_CATEGORY))
        states.select(self.char1, cloak, "down")
        self.assertEqual(
            cloak.db_attributes.filter(
                db_key=states.STATE_KEY, db_category=states.STATE_CATEGORY
            ).count(),
            1,
        )
        self.assertEqual(states.current(cloak, states.configuration(cloak)), "down")
