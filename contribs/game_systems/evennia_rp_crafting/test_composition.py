# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Composition contracts: closed production, immutable provenance and verb dispatch."""

from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest

from . import conf, services
from .behaviours import Readable
from .commands import DRAFT_KEY, CmdCraft, CmdCrafting, CmdRead
from .errors import CraftingError
from .models import CraftRecord, NicheDefinition
from .tests import CraftingFixture


class Echo(Readable):
    """Test-only second verb to distinguish whole-set from pairwise permission."""


class CompositionTests(CraftingFixture, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.unlock()

    def test_books_are_carried_with_a_readable_verb_at_the_existing_price(self):
        before = self.held()
        book = self.book()
        record = book.craft_record
        self.assertEqual(record.behaviour, "carried")
        self.assertEqual(
            record.verbs,
            [
                {
                    "key": "readable",
                    "niche": "writing-0",
                    "configuration": {"text": "A record of the road."},
                }
            ],
        )
        self.assertEqual(self.held(), before - 1)
        self.assertEqual(
            record.contributors,
            [
                {
                    "key": "writing-0",
                    "name": "Scribe 0",
                    "behaviours": ["readable"],
                }
            ],
        )

    def test_closed_combinations_reject_without_spending_or_creating(self):
        before = (self.held(), ObjectDB.objects.count(), CraftRecord.objects.count())
        with self.assertRaises(CraftingError):
            self.book(behaviour_key="carried", configuration={}, verbs=[])
        self.assertEqual(
            (self.held(), ObjectDB.objects.count(), CraftRecord.objects.count()), before
        )

    def test_allow_list_change_does_not_disable_an_existing_book(self):
        book = self.book()
        with override_settings(RP_CRAFTING_COMBINATIONS={}):
            self.call(CmdRead(), book.key, f"{book.key}\nA record of the road.")
            with self.assertRaises(CraftingError):
                self.book()

    def test_complete_verb_sets_do_not_imply_permission_for_their_union(self):
        NicheDefinition.objects.filter(key="writing-0").update(behaviours=["readable", "echo"])
        extra = [{"key": "echo", "niche": "writing-0", "configuration": {"text": "Echo."}}]
        rules = conf.DEFAULT_COSTS | {"echo": {"base": {"materials": 1}}}
        registry = conf.DEFAULT_BEHAVIOURS | {"echo": Echo}
        with override_settings(
            RP_CRAFTING_BEHAVIOURS=registry,
            RP_CRAFTING_COSTS=rules,
            RP_CRAFTING_COMBINATIONS={"carried": [["readable"], ["echo"]]},
        ):
            before = self.held()
            with self.assertRaises(CraftingError):
                self.book(verbs=extra, selected={"wood": 2})
            self.assertEqual(self.held(), before)
            with override_settings(RP_CRAFTING_COMBINATIONS={"carried": [["echo", "readable"]]}):
                from .composition import specifications

                specifications("writing-0", "carried", {}, extra, partial=True)
                with self.assertRaises(CraftingError):
                    specifications("writing-0", "carried", {}, extra)
                book = self.book(verbs=extra, selected={"wood": 2})
            self.assertEqual(self.held(), before - 2)
            self.assertEqual(
                book.craft_record.contributors,
                [
                    {
                        "key": "writing-0",
                        "name": "Scribe 0",
                        "behaviours": ["echo", "readable"],
                    }
                ],
            )

    def test_bad_verb_shapes_duplicates_and_second_lifecycle_cannot_spend(self):
        before = self.held()
        for verbs in (
            {},
            [None],
            [{"key": []}],
            [{"key": "wearable", "niche": "writing-0", "configuration": {}}],
            [{"key": "readable", "niche": "writing-0", "configuration": {"text": "Again."}}],
        ):
            with self.subTest(verbs=verbs), self.assertRaises(CraftingError):
                self.book(verbs=verbs)
        self.assertEqual(self.held(), before)

    def test_canonical_carried_api_needs_no_separate_carried_niche(self):
        book = self.book(
            behaviour_key="carried",
            configuration={},
            verbs=[
                {
                    "key": "readable",
                    "niche": "writing-0",
                    "configuration": {"text": "Canonical."},
                }
            ],
        )
        self.assertEqual(book.read(self.char2), "Canonical.")

    def test_book_draft_still_finishes_after_persistent_reload(self):
        self.call(CmdCraft(), "/new writing-0/readable = notes", "Craft draft saved")
        self.call(CmdCraft(), "/desc = Bound notes.", "Craft draft saved")
        self.call(CmdCraft(), "/text = Keep these.", "Craft draft saved")
        self.call(CmdCraft(), "/resources = wood:1", "Craft draft saved")
        # Fetch from the database-backed Attribute handler, rather than retaining
        # a command instance or an in-memory draft object between invocations.
        self.assertTrue(self.char1.attributes.has(DRAFT_KEY))
        self.call(CmdCraft(), "", "Draft: notes")
        self.call(CmdCraft(), "/finish", "You craft notes")
        self.assertEqual(CraftRecord.objects.get().behaviour_keys, ["carried", "readable"])

    @skipUnless(apps.is_installed("evennia_rp_equipment"), "equipment absent")
    def test_readable_wearable_uses_each_niche_and_preserves_equipment_guards(self):
        from evennia_rp_equipment import services as equipment

        self.unlock("weaving")
        verbs = [{"key": "readable", "niche": "writing-0", "configuration": {"text": "A secret."}}]
        with override_settings(RP_CRAFTING_COMBINATIONS={"wearable": [["readable"]]}):
            item = services.craft(
                self.char1,
                "weaving",
                "wearable",
                "locket",
                "A small locket.",
                {"slot": "neck"},
                {"wood": 2},
                verbs=verbs,
            )
        self.call(CmdRead(), "locket", "locket\nA secret.")
        self.assertEqual(item.craft_record.resources_spent, {"wood": 2})
        self.assertIn("Weaver", item.get_display_provenance())
        self.assertIn("Scribe 0", item.get_display_provenance())
        self.assertIn("readable", item.get_market_keywords())
        equipment.wear(self.char1, item)
        self.assertFalse(item.at_pre_give(self.char1, self.char2))
        equipment.remove(self.char1, item)
        item.move_to(self.char2, quiet=True, move_type="give")
        self.assertTrue(item.sealed)
        self.assertEqual(item.read(self.char2), "A secret.")

    @skipUnless(apps.is_installed("evennia_rp_equipment"), "equipment absent")
    def test_missing_or_abandoned_contributing_niche_rolls_back(self):
        self.unlock("weaving")
        verbs = [{"key": "readable", "niche": "writing-1", "configuration": {"text": "Text."}}]
        before = self.held()
        with override_settings(RP_CRAFTING_COMBINATIONS={"wearable": [["readable"]]}):
            with self.assertRaisesMessage(CraftingError, "Unlock"):
                services.craft(
                    self.char1,
                    "weaving",
                    "wearable",
                    "locket",
                    "Small.",
                    {},
                    {"wood": 2},
                    verbs=verbs,
                )
            self.unlock("writing-1")
            services.abandon(self.char1, "writing-1")
            before = self.held()
            with self.assertRaisesMessage(CraftingError, "Unlock"):
                services.craft(
                    self.char1,
                    "weaving",
                    "wearable",
                    "locket",
                    "Small.",
                    {},
                    {"wood": 2},
                    verbs=verbs,
                )
        self.assertEqual(self.held(), before)
        self.assertFalse(CraftRecord.objects.exists())

    @skipUnless(apps.is_installed("evennia_rp_equipment"), "equipment absent")
    def test_composed_draft_preview_review_and_failed_finish(self):
        self.unlock("weaving")
        self.call(CmdCraft(), "/new weaving/wearable = locket", "Craft draft saved")
        self.call(
            CmdCraft(),
            "/verb writing-0/readable",
            "That lifecycle and verb combination is unavailable.",
        )
        with override_settings(RP_CRAFTING_COMBINATIONS={"wearable": [["readable"]]}):
            for args in (
                "/verb writing-0/readable",
                "/desc = Small.",
                "/text = A secret.",
                "/resources = wood:2",
            ):
                self.call(CmdCraft(), args, "Craft draft saved")
            output = self.call(CmdCraft(), "", "Draft: locket")
            self.assertIn("Weaver", output)
            self.assertIn("Scribe 0", output)
            self.assertIn("2 materials", output)
            before = self.held()
            with patch(
                "evennia_rp_crafting.models.CraftRecord.objects.create",
                side_effect=ValueError("record failed"),
            ):
                self.call(CmdCraft(), "/finish", "record failed")
            self.assertEqual(self.held(), before)
            self.assertTrue(self.char1.attributes.has(DRAFT_KEY))
            self.call(CmdCraft(), "/finish", "You craft locket")
        self.char1.permissions.add("Builder")
        self.account.permissions.add("Builder")
        record = CraftRecord.objects.get()
        NicheDefinition.objects.filter(key="writing-0").update(name="Renamed")
        output = self.call(CmdCrafting(), f"/review {record.pk}", f"Craft #{record.pk}")
        self.assertIn("A secret.", output)
        self.assertIn("Scribe 0", output)
        self.assertIn("readable", output)

    @skipUnless(apps.is_installed("evennia_rp_equipment"), "equipment absent")
    def test_each_component_keeps_its_own_input_categories_and_one_craft_fee(self):
        self.unlock("weaving")
        verbs = [{"key": "readable", "niche": "writing-0", "configuration": {"text": "Text."}}]
        rules = conf.DEFAULT_COSTS | {"readable": {"base": {"essences": 1}}}
        contexts = []

        def policy(kind, actor, context):
            if kind == "craft":
                contexts.append(context)
                return 7
            return 0

        with override_settings(RP_CRAFTING_COMBINATIONS={"wearable": [["readable"]]}):
            with (
                override_settings(RP_CRAFTING_COSTS=rules),
                self.assertRaisesMessage(CraftingError, "input category"),
            ):
                services.craft(
                    self.char1,
                    "weaving",
                    "wearable",
                    "locket",
                    "Small.",
                    {},
                    {"wood": 1, "spark": 1},
                    verbs=verbs,
                )
            with override_settings(RP_ECONOMY_FEE_POLICY=policy):
                item = services.craft(
                    self.char1,
                    "weaving",
                    "wearable",
                    "locket",
                    "Small.",
                    {},
                    {"wood": 2},
                    verbs=verbs,
                )
        self.assertEqual(
            item.craft_record.money_spent, 7 if apps.is_installed("evennia_economy") else 0
        )
        if contexts:
            self.assertEqual(len(contexts), 1)
            self.assertEqual(contexts[0]["verbs"], verbs)
            self.assertEqual(
                [row["key"] for row in contexts[0]["contributors"]], ["weaving", "writing-0"]
            )

    def test_persisted_composed_wearable_can_be_read_without_equipment(self):
        if apps.is_installed("evennia_rp_equipment"):
            self.skipTest("requires physically absent equipment")
        from evennia.utils.create import create_object

        item = create_object(
            "evennia_rp_crafting.wearables.Wearable", key="old locket", location=self.char1
        )
        CraftRecord.objects.create(
            crafter_id=self.char1.pk,
            crafter_name=self.char1.key,
            niche=NicheDefinition.objects.get(key="writing-0"),
            niche_name="Scribe 0",
            behaviour="wearable",
            item_id=item.pk,
            verbs=[
                {"key": "readable", "niche": "writing-0", "configuration": {"text": "Still here."}}
            ],
            prose={"configuration": {}},
            hallmark="Made by Char (Weaver, Scribe 0)",
        )
        self.call(CmdRead(), item.key, "old locket\nStill here.")
