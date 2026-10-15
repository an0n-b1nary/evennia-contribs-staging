# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Pages retain authored boundaries, provenance, price and personal progress."""

from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from . import conf
from .behaviours import Readable
from .commands import DRAFT_KEY, CmdCraft, CmdRead
from .errors import CraftingError
from .models import CraftRecord
from .pages import BOOKMARK_CATEGORY, read, validate
from .tests import CraftingFixture

PAGES = [
    {"title": "Departure", "text": "The road begins.\n\nA second paragraph."},
    {"title": "Arrival", "text": "The market is quiet."},
]


class RedactedReadable(Readable):
    def invoke(self, actor, item, config):
        return "Only this text is public."


class DeniedReadable(Readable):
    def invoke(self, actor, item, config):
        raise CraftingError("The host denies this read.")


class PageTests(CraftingFixture, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.unlock()

    def paged_book(self, **kwargs):
        return self.book(configuration={"pages": PAGES}, selected={"wood": 2}, **kwargs)

    def test_cost_snapshot_and_mutable_item_text_cannot_rewrite_pages(self):
        before = self.held()
        book = self.paged_book()
        record = book.craft_record
        self.assertEqual(self.held(), before - 2)
        self.assertEqual(record.verb_data[0]["configuration"], {"pages": PAGES})
        book.db.pages = [{"text": "Forged"}]
        book.db.text = "Forged"
        self.assertEqual(book.read(self.char1, 2), "Page 2 of 2: Arrival\nThe market is quiet.")
        self.assertEqual(book.craft_record.hallmark, record.hallmark)
        self.assertNotIn("Forged", book.read(self.char1, contents=True))

    def test_bookmarks_are_reader_specific_persistent_and_follow_the_item_identity(self):
        book = self.paged_book()
        self.assertIn("Page 2 of 2", read(self.char1, book, 2))
        book.key = "Renamed volume"
        self.assertIn("Page 1 of 2", read(self.char2, book))
        self.assertIn("Contents (2 pages)", read(self.char1, book, table=True))
        self.char1.attributes.reset_cache()
        self.assertIn("Page 2 of 2", read(self.char1, book))
        book.move_to(self.char2, quiet=True)
        self.assertIn("Page 1 of 2", read(self.char2, book))
        key = f"craft_{book.craft_record.pk}"
        self.assertEqual(self.char1.attributes.get(key, category=BOOKMARK_CATEGORY), 2)

    def test_contents_and_invalid_or_denied_reads_do_not_advance_bookmark(self):
        book = self.paged_book()
        self.assertEqual(
            read(self.char1, book, table=True), "Contents (2 pages):\n1. Departure\n2. Arrival"
        )
        key = f"craft_{book.craft_record.pk}"
        self.assertFalse(self.char1.attributes.has(key, category=BOOKMARK_CATEGORY))
        for number in (0, -1, 3, True, "2"):
            with self.subTest(number=number), self.assertRaises(CraftingError):
                read(self.char1, book, number)
        for lock in ("read:false()", "view:false()"):
            book.locks.add(lock)
            with self.assertRaisesMessage(CraftingError, "cannot read"):
                read(self.char1, book, 2)
            with self.assertRaises(CraftingError):
                read(self.char1, book, table=True)
            book.locks.add("read:all();view:all()")
        self.assertFalse(self.char1.attributes.has(key, category=BOOKMARK_CATEGORY))

    def test_legacy_and_composition_books_keep_text_output_and_original_delimiters(self):
        prose = "Old text.\n---PAGE---\nThis was prose before paging existed."
        book = self.book()
        record = book.craft_record
        # Simulate the original shipped record shape without rewriting migrations.
        CraftRecord.objects.filter(pk=record.pk).update(
            behaviour="readable", verbs=[], prose={"configuration": {"text": prose}}
        )
        with override_settings(RP_CRAFTING_COMBINATIONS={}):
            self.assertEqual(book.read(self.char1), prose)
        self.assertEqual(book.read(self.char1, contents=True), "Contents (1 page):\n1. Page 1")
        self.assertEqual(
            CraftRecord.objects.get(pk=record.pk).prose["configuration"]["text"], prose
        )

    def test_delimited_new_text_becomes_explicit_pages_at_craft_time(self):
        book = self.book(
            configuration={"text": "First.\n---PAGE---\nSecond."}, selected={"wood": 2}
        )
        self.assertEqual(book.read(self.char1, 2), "Page 2 of 2\nSecond.")
        self.assertEqual(len(book.craft_record.verb_data[0]["configuration"]["pages"]), 2)
        self.assertEqual(
            book.read(self.char1, contents=True), "Contents (2 pages):\n1. Page 1\n2. Page 2"
        )

    def test_invalid_pages_never_spend_and_keep_limits_on_total_text(self):
        invalid = [
            {"pages": []},
            {"pages": "text"},
            {"pages": [None]},
            {"pages": [{"text": ""}]},
            {"pages": [{"text": "x", "other": 1}]},
            {"pages": [{"text": "x", "title": "line\nbreak"}]},
            {"pages": [{"text": "x", "title": "x" * 81}]},
            {"pages": [{"text": "x" * 6001}] * 2},
            {"pages": [{"text": "x"}] * 101},
            {"pages": PAGES, "text": "ambiguous"},
            {"text": "First\n---PAGE---\n"},
        ]
        before = self.held(), CraftRecord.objects.count()
        for config in invalid:
            with self.subTest(config=str(config)[:100]), self.assertRaises(CraftingError):
                self.book(configuration=config)
        self.assertEqual((self.held(), CraftRecord.objects.count()), before)

    def test_page_cost_is_configured_and_failed_record_rolls_back(self):
        rules = conf.DEFAULT_COSTS | {
            "readable": {"base": {"materials": 1}, "extra_page": {"materials": 3}}
        }
        with override_settings(RP_CRAFTING_COSTS=rules):
            before = self.held()
            book = self.book(configuration={"pages": PAGES}, selected={"wood": 4})
            self.assertEqual(book.craft_record.resources_spent, {"wood": 4})
            with (
                patch.object(CraftRecord, "save", side_effect=ValueError("failed snapshot")),
                self.assertRaises(ValueError),
            ):
                self.book(configuration={"pages": PAGES}, selected={"wood": 4})
            self.assertEqual(self.held(), before - 4)
        with override_settings(RP_CRAFTING_COSTS={"readable": {"base": {"materials": 1}}}):
            self.book()
            with self.assertRaisesMessage(CraftingError, "extra-page"):
                self.paged_book()

    def test_draft_append_remove_preview_finish_and_read_navigation(self):
        self.call(CmdCraft(), "/new writing-0/readable = travel book", "Craft draft saved")
        self.call(CmdCraft(), "/desc = A travel book.", "Craft draft saved")
        self.call(CmdCraft(), "/page Departure = First.", "Craft draft saved")
        self.call(CmdCraft(), "/page Arrival = Second.", "Craft draft saved")
        output = self.call(CmdCraft(), "", "Draft: travel book")
        self.assertIn("1. Departure", output)
        self.assertIn("First.", output)
        self.assertIn("2 materials", output)
        self.call(CmdCraft(), "/unpage 3", "No such draft page.")
        self.call(CmdCraft(), "/unpage 1", "Craft draft saved")
        self.call(CmdCraft(), "/page Return = Third.", "Craft draft saved")
        self.call(CmdCraft(), "/resources = wood:2", "Craft draft saved")
        self.call(CmdCraft(), "/finish", "You craft travel book")
        self.call(CmdRead(), "travel book 2", "travel book\nPage 2 of 2: Return\nThird.")
        self.call(
            CmdRead(),
            "/contents travel book",
            "travel book\nContents (2 pages):\n1. Arrival\n2. Return",
        )
        self.call(CmdRead(), "travel book", "travel book\nPage 2 of 2: Return\nThird.")
        self.call(CmdRead(), "travel book = 1", "travel book\nPage 1 of 2: Arrival\nSecond.")

    def test_text_replaces_draft_pages_and_failed_validation_keeps_draft(self):
        self.call(CmdCraft(), "/new writing-0/readable = notes", "Craft draft saved")
        self.call(CmdCraft(), "/text = First.\n---PAGE---\nSecond.", "Craft draft saved")
        self.assertEqual(len(self.char1.attributes.get(DRAFT_KEY)["configuration"]["pages"]), 2)
        self.call(CmdCraft(), "/page Empty = ", "Page text must contain")
        self.assertEqual(len(self.char1.attributes.get(DRAFT_KEY)["configuration"]["pages"]), 2)
        self.call(CmdCraft(), "/text = Replacement.", "Craft draft saved")
        self.assertEqual(
            dict(self.char1.attributes.get(DRAFT_KEY)["configuration"]), {"text": "Replacement."}
        )
        self.call(CmdCraft(), "/unpage 1", "Craft draft saved")
        self.assertEqual(dict(self.char1.attributes.get(DRAFT_KEY)["configuration"]), {})

    def test_exact_numeric_item_names_win_and_remote_or_plain_items_cannot_read(self):
        book = self.paged_book(name="chapter 2")
        self.call(CmdRead(), "chapter 2", "chapter 2\nPage 1 of 2: Departure")
        self.call(CmdRead(), "chapter 2 = 2", "chapter 2\nPage 2 of 2: Arrival")
        self.call(CmdRead(), "chapter 2 = 0", "Choose a page from 1 to 2.")
        book.move_to(self.room2, quiet=True)
        self.call(CmdRead(), "chapter 2", "Could not find")
        self.obj1.db.pages = PAGES
        self.call(CmdRead(), self.obj1.key, "There is nothing written here.")

    def test_validation_produces_an_independent_snapshot(self):
        config = {"pages": [{"title": "One", "text": "Text."}]}
        normalized = validate(config)
        config["pages"][0]["text"] = "Changed"
        self.assertEqual(normalized["pages"][0]["text"], "Text.")

    @skipUnless(apps.is_installed("evennia_rp_equipment"), "equipment absent")
    def test_pages_on_a_composed_draft_preserve_lifecycle_fields_and_combined_price(self):
        self.unlock("weaving")
        with override_settings(RP_CRAFTING_COMBINATIONS={"wearable": [["readable"]]}):
            for args in (
                "/new weaving/wearable = book pendant",
                "/desc = A small book-shaped pendant.",
                "/line = a small silver book pendant",
                "/verb writing-0/readable",
                "/page First = An opening.",
                "/page Last = A closing.",
                "/resources = wood:3",
            ):
                self.call(CmdCraft(), args, "Craft draft saved")
            output = self.call(CmdCraft(), "", "Draft: book pendant")
            self.assertIn("3 materials", output)
            self.assertIn("2. Last", output)
            self.call(CmdCraft(), "/finish", "You craft book pendant")
        from evennia.objects.models import ObjectDB

        pendant = ObjectDB.objects.get(db_key="book pendant")
        self.assertEqual(pendant.worn_line, "a small silver book pendant")
        self.assertEqual(pendant.craft_record.resources_spent, {"wood": 3})
        self.assertEqual(pendant.read(self.char1, 2), "Page 2 of 2: Last\nA closing.")

    def test_contents_checks_access_without_performing_a_full_text_read(self):
        book = self.paged_book()
        from .behaviours import Readable

        with patch.object(Readable, "invoke", side_effect=AssertionError("full read")):
            self.assertIn("1. Departure", book.read(self.char1, contents=True))
        book.locks.add("read:false()")
        with self.assertRaises(CraftingError):
            book.read(self.char1, contents=True)

    def test_custom_read_dispatch_cannot_be_bypassed_by_page_or_contents_reads(self):
        book = self.paged_book()
        with override_settings(
            RP_CRAFTING_BEHAVIOURS=conf.DEFAULT_BEHAVIOURS | {"readable": RedactedReadable}
        ):
            self.assertEqual(book.read(self.char1), "Only this text is public.")
            self.assertNotIn("Departure", book.read(self.char1, contents=True))
        with override_settings(
            RP_CRAFTING_BEHAVIOURS=conf.DEFAULT_BEHAVIOURS | {"readable": DeniedReadable}
        ):
            for kwargs in ({}, {"contents": True}, {"page": 1}):
                with (
                    self.subTest(kwargs=kwargs),
                    self.assertRaisesMessage(CraftingError, "host denies"),
                ):
                    book.read(self.char1, **kwargs)
