# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Immutable exterior prose, paid draft edits and local private inspection."""

from copy import deepcopy
from unittest.mock import patch

from django.test import override_settings
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTest

from . import conf, services
from .commands import DRAFT_KEY, CmdCraft, CmdListen, CmdSense
from .detail_commands import CmdLook
from .errors import CraftingError
from .item_details import examine, sense
from .models import CraftRecord, EventUse
from .test_events import EventFixture
from .tests import CraftingFixture

FACETS = {
    "details": {"cover": "A stitched map decorates the cover."},
    "senses": {
        "smell": "Dry paper and cedar.",
        "sound": "The binding creaks.",
        "touch": "Soft cloth.",
    },
}


class ItemDetailsTests(CraftingFixture, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.unlock()

    def detailed_book(self, **kwargs):
        return self.book(facets=deepcopy(FACETS), selected={"wood": 5}, **kwargs)

    def test_paid_snapshot_survives_mutation_gifting_and_runtime_changes(self):
        requested = deepcopy(FACETS)
        before = self.held()
        item = self.book(facets=requested, selected={"wood": 5})
        requested["details"]["cover"] = "Changed input."
        item.db.details = {"cover": "Forged detail."}
        item.db.senses = {"smell": "Forged scent."}
        self.assertEqual(self.held(), before - 5)
        self.assertEqual(item.craft_record.resources_spent, {"wood": 5})
        self.assertEqual(examine(self.char1, item, "COVER"), FACETS["details"]["cover"])
        self.assertEqual(sense(self.char1, item, "smell"), FACETS["senses"]["smell"])
        item.move_to(self.char2, quiet=True)
        with override_settings(RP_CRAFTING_FROZEN=True, RP_CRAFTING_FACET_UNIT_COSTS={}):
            self.assertEqual(examine(self.char2, item, "cover"), FACETS["details"]["cover"])
            self.assertEqual(sense(self.char2, item, "sound"), FACETS["senses"]["sound"])
        self.assertIn("Details: cover.", item.get_display_desc(self.char2))
        self.assertIn("Item senses: smell, sound, touch.", item.get_display_desc(self.char2))

    def test_invalid_metadata_and_costs_never_spend_or_create_items(self):
        before = self.held()
        for facets in (
            {"details": []},
            {"details": {"x" * 41: "Text"}},
            {"details": {"ß" * 40: "Text"}},
            {"details": {"": "Text"}},
            {"details": {"a=b": "Text"}},
            {"details": {"Cover": "One", "cover": "Two"}},
            {"details": {str(index): "Text" for index in range(9)}},
            {"details": {"cover": "x" * 1001}},
            {"details": {"cover": "Fake|/line"}},
            {"senses": {"taste": "Sweet"}},
            {"senses": ["smell"]},
            {"senses": {"touch": ""}},
            {"senses": {"sound": "One\nTwo"}},
            {"senses": {"smell": "x" * 401}},
        ):
            with self.subTest(facets=facets), self.assertRaises(CraftingError):
                self.book(facets=facets)
        for value in ({}, {"details": True}, {"details": -1}, {"details": conf.MAX_AMOUNT}):
            with (
                self.subTest(cost=value),
                override_settings(RP_CRAFTING_FACET_UNIT_COSTS=value),
                self.assertRaises(CraftingError),
            ):
                self.book(facets={"details": {"one": "One", "two": "Two"}})
        self.assertEqual(self.held(), before)
        self.assertFalse(CraftRecord.objects.exists())

    def test_preview_cost_is_configurable_and_empty_facets_cost_nothing(self):
        before = self.held()
        with override_settings(RP_CRAFTING_FACET_UNIT_COSTS={"details": 2, "senses": 3}):
            _, composition, _, cost = services.craft_cost(
                self.char1, "writing-0", "readable", {"text": "Text"}, facets=FACETS
            )
        self.assertEqual(cost["resources"], {"materials": 12})
        self.assertEqual(composition.facets, FACETS)
        self.assertEqual(self.held(), before)
        item = self.book(facets={"details": {}, "senses": {}})
        self.assertNotIn("facets", item.craft_record.prose)
        self.assertEqual(item.read(self.char1), "A record of the road.")

    def test_access_and_proximity_checked_before_any_prose_is_exposed(self):
        item = self.detailed_book()
        for lock in ("view:false()", "smell:false()", "listen:false()", "touch:false()"):
            item.locks.add(lock)
            action = "sound" if lock.startswith("listen") else lock.split(":")[0]
            with self.subTest(lock=lock), self.assertRaises(CraftingError):
                if action == "view":
                    examine(self.char1, item, "cover")
                else:
                    sense(self.char1, item, action)
            item.locks.add(f"{lock.split(':')[0]}:all()")
        item.move_to(self.char2, quiet=True)
        with self.assertRaises(CraftingError):
            examine(self.char1, item, "cover")
        item.move_to(self.room2, quiet=True)
        with self.assertRaises(CraftingError):
            sense(self.char1, item, "smell")
        plain = create_object("evennia.objects.objects.DefaultObject", location=self.char1)
        plain.db.details = FACETS["details"]
        with self.assertRaises(CraftingError):
            examine(self.char1, plain, "cover")

    def test_examination_does_not_read_consume_emit_or_move_bookmarks(self):
        item = self.detailed_book()
        attributes = list(self.char1.attributes.all())
        with (
            patch.object(type(item), "read", side_effect=AssertionError("Read invoked")),
            patch.object(type(self.room1), "msg_contents") as emitted,
            patch("evennia_rp_crafting.signals.page_read.send_robust") as read,
        ):
            self.call(CmdLook(), "Field book = cover", "Field book — cover\nA stitched map")
            self.call(CmdSense(), "Field book", "Field book\nDry paper and cedar.")
            self.call(CmdListen(), "Field book", "Field book\nThe binding creaks.")
        emitted.assert_not_called()
        read.assert_not_called()
        self.assertEqual(list(self.char1.attributes.all()), attributes)
        self.assertTrue(ObjectDB.objects.filter(pk=item.pk).exists())

    def test_look_preserves_normal_objects_and_disambiguates_named_details(self):
        self.detailed_book()
        self.call(CmdLook(), "Field book cover", "Field book — cover\nA stitched map")
        self.call(CmdLook(), "Field book = absent", "No such item detail.")
        other = create_object(
            "evennia.objects.objects.DefaultObject", key="Field book cover", location=self.room1
        )
        other.db.desc = "An entirely separate object."
        output = self.call(CmdLook(), "Field book cover")
        self.assertIn("An entirely separate object.", output)
        self.assertNotIn("A stitched map", output)
        self.call(CmdLook(), "Field book = cover", "Field book — cover\nA stitched map")
        other.key = "Field book = cover"
        self.assertIn("An entirely separate object.", self.call(CmdLook(), other.key))
        self.assertIn("Room", self.call(CmdLook(), ""))

    def test_draft_edits_are_repairable_and_paid_only_at_completion(self):
        before = self.held()
        self.call(CmdCraft(), "/new writing-0/readable = Detail book", "Craft draft saved")
        self.call(CmdCraft(), "/desc A notebook.", "Craft draft saved")
        self.call(CmdCraft(), "/text Written text.", "Craft draft saved")
        self.call(CmdCraft(), "/detail Cover = A cloth cover.", "Craft draft saved")
        self.call(CmdCraft(), "/detail Cover = An embroidered cover.", "Craft draft saved")
        self.call(CmdCraft(), "/sense smell = Cedar.", "Craft draft saved")
        self.call(CmdCraft(), "/sense taste = Sweet.", "Choose smell, sound or touch.")
        preview = self.call(CmdCraft(), "")
        self.assertIn("Detail cover: An embroidered cover.", preview)
        self.assertIn("Item sense smell: Cedar.", preview)
        self.assertIn("Cost: 3 materials", preview)
        self.assertEqual(self.held(), before)
        self.call(CmdCraft(), "/undetail cover", "Craft draft saved")
        self.call(CmdCraft(), "/unsense smell", "Craft draft saved")
        self.assertEqual(dict(self.char1.attributes.get(DRAFT_KEY)["facets"]), {})
        self.call(CmdCraft(), "/detail cover = Restored detail.", "Craft draft saved")
        self.call(CmdCraft(), "/resources 1 wood", "Craft draft saved")
        self.call(CmdCraft(), "/finish", "Choose exactly")
        self.assertTrue(self.char1.attributes.has(DRAFT_KEY))
        self.call(CmdCraft(), "/resources 2 wood", "Craft draft saved")
        self.call(CmdCraft(), "/finish", "You craft Detail book")
        self.assertEqual(self.held(), before - 2)

    def test_item_senses_work_with_wave_two_hidden_and_room_senses_keep_their_gate(self):
        self.detailed_book()
        self.room1.db.room_smell = "Rain on stone."
        self.call(CmdSense(), "", "Rain on stone.")
        with override_settings(RP_CRAFTING_WAVE_TWO_REVEALED=False):
            self.call(CmdSense(), "Field book", "Field book\nDry paper and cedar.")
            self.call(CmdSense(), "", "")
        with override_settings(RP_CRAFTING_REVEALED=False), self.assertRaises(CraftingError):
            examine(self.char1, self.obj1, "cover")


class ConsumableDetailTests(EventFixture, EvenniaCommandTest):
    def test_food_and_broadcast_facets_charge_their_own_category_without_consumption(self):
        for kind, niche, resource in (
            ("consumable", "cooking", "grain"),
            ("broadcast", "illusions", "spark"),
        ):
            item = services.craft(
                self.char1,
                niche,
                kind,
                f"Decorated {kind}",
                "A decorated item.",
                {"beats": ["Light blossoms."]},
                {resource: 5},
                facets=deepcopy(FACETS),
            )
            self.assertEqual(sense(self.char1, item, "touch"), "Soft cloth.")
            self.assertEqual(examine(self.char1, item, "cover"), FACETS["details"]["cover"])
            self.assertEqual(item.craft_record.resources_spent, {resource: 5})
            self.assertTrue(ObjectDB.objects.filter(pk=item.pk).exists())
        self.assertFalse(EventUse.objects.exists())
