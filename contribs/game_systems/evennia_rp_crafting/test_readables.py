# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Journal authority, paid capacity, revision history and honest copy snapshots."""

from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import override_settings
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest

from . import conf
from .commands import DRAFT_KEY, CmdCraft, CmdRead
from .errors import CraftingError
from .models import CraftRecord, JournalRevision, ReadableEdition
from .readable_commands import CmdJournal
from .readables import copy_book, history, snapshot, write
from .test_pages import DeniedReadable, RedactedReadable
from .tests import CraftingFixture


class ReadableTests(CraftingFixture, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.unlock()

    def journal(self, capacity=3):
        return self.book(configuration={"journal": capacity}, selected={"wood": capacity})

    def copy(self, book, **kwargs):
        return copy_book(
            self.char1, book, "writing-0", "Edition", "A bound copy.", {"wood": 1}, **kwargs
        )

    def test_blank_capacity_cost_and_free_writing_without_niche(self):
        before = self.held()
        journal = self.journal()
        record = journal.craft_record
        self.assertEqual(self.held(), before - 3)
        self.assertIn("no entries", journal.read(self.char1))
        with self.assertRaises(CraftingError):
            journal.read(self.char1, 1)
        journal.move_to(self.char2, quiet=True)
        write(self.char2, journal, "First", "A page by the new owner.")
        self.assertIn("Text by (OOC): Char2", journal.read(self.char1))
        self.assertEqual(CraftRecord.objects.get(pk=record.pk).verbs, record.verbs)
        self.assertEqual(self.held(), before - 3)
        self.assertFalse(self.char2.attributes.has(DRAFT_KEY))

    def test_revisions_and_gifts_keep_actual_writers_and_old_text(self):
        journal = self.journal()
        first = write(self.char1, journal, "First", "Original words.")
        revised = write(self.char1, journal, "First revised", "New words.", page=1)
        self.assertEqual((first.revision, revised.revision), (1, 2))
        self.assertIn("Original words.", history(self.char1, journal, 1))
        journal.move_to(self.char2, quiet=True)
        with self.assertRaisesMessage(CraftingError, "only your own"):
            write(self.char2, journal, "Forged", "Replacement.", page=1)
        write(self.char2, journal, "Second", "Other writer.")
        self.char1.key = "Renamed writer"
        self.assertIn("Char", journal.read(self.char2, 1))
        self.assertNotIn("Renamed writer", journal.read(self.char2, 1))
        self.assertIn("Char2", journal.read(self.char2, 2))
        journal.move_to(self.char1, quiet=True)
        write(self.char1, journal, "First again", "Returned to writer.", page=1)
        self.assertEqual(JournalRevision.objects.filter(craft=journal.craft_record).count(), 4)
        with self.assertRaisesMessage(CraftingError, "only your own"):
            write(self.char1, journal, "Wrong", "Other page.", page=2)

    def test_custody_locks_freeze_and_printed_books_refuse_writes(self):
        journal = self.journal()
        for lock in ("view:false()", "read:false()", "write:false()"):
            journal.locks.add(lock)
            with self.assertRaises(CraftingError):
                write(self.char1, journal, "No", "No.")
            journal.locks.add("view:all();read:all();write:all()")
        journal.move_to(self.room1, quiet=True)
        with self.assertRaisesMessage(CraftingError, "Carry"):
            write(self.char1, journal, "No", "No.")
        journal.move_to(self.char1, quiet=True)
        with override_settings(RP_CRAFTING_FROZEN=True), self.assertRaises(CraftingError):
            write(self.char1, journal, "No", "No.")
        with self.assertRaisesMessage(CraftingError, "Only blank journals"):
            write(self.char1, self.book(), "No", "No.")
        self.assertEqual(JournalRevision.objects.count(), 0)

    def test_capacity_total_limits_and_invalid_revisions_leave_history_intact(self):
        journal = self.journal(2)
        write(self.char1, journal, "", "x" * 6000)
        for page in (0, -1, True, "1", 2):
            with self.subTest(page=page), self.assertRaises(CraftingError):
                write(self.char1, journal, "", "No.", page=page)
        with self.assertRaises(CraftingError):
            write(self.char1, journal, "", "x" * 6001)
        write(self.char1, journal, "", "x" * 6000)
        with self.assertRaisesMessage(CraftingError, "unused pages"):
            write(self.char1, journal, "", "One more.")
        with self.assertRaises(CraftingError):
            write(self.char1, journal, "", "x" * 6001, page=1)
        self.assertEqual(JournalRevision.objects.count(), 2)

    def test_malformed_capacity_never_spends(self):
        before = self.held(), CraftRecord.objects.count()
        for value in (0, 101, True, "2", [], None):
            with self.subTest(value=value), self.assertRaises(CraftingError):
                self.book(configuration={"journal": value})
        with self.assertRaises(CraftingError):
            self.book(configuration={"journal": 2, "text": "Not blank"})
        self.assertEqual((self.held(), CraftRecord.objects.count()), before)

    def test_writing_failure_rolls_back_and_history_rows_are_append_only(self):
        journal = self.journal()
        with (
            patch.object(JournalRevision, "save", side_effect=ValueError("history failed")),
            self.assertRaises(ValueError),
        ):
            write(self.char1, journal, "One", "Words.")
        self.assertEqual(JournalRevision.objects.count(), 0)
        self.assertIn("no entries", journal.read(self.char1))
        row = write(self.char1, journal, "One", "Words.")
        for mutate in (row.save, row.delete):
            with self.assertRaises(ValidationError):
                mutate()

    def test_copies_freeze_mixed_authors_and_do_not_clone_journal_capacity(self):
        journal = self.journal()
        write(self.char1, journal, "One", "First writer.")
        journal.move_to(self.char2, quiet=True)
        write(self.char2, journal, "Two", "Second writer.")
        journal.move_to(self.room1, quiet=True)
        copy = copy_book(self.char1, journal, "writing-0", "Edition", "A copy.", {"wood": 2})
        self.assertEqual(copy.craft_record.resources_spent, {"wood": 2})
        self.assertIn("Copied by Char", copy.get_display_provenance())
        self.assertIn("Char2", copy.get_display_provenance())
        self.assertIn("Char2", copy.read(self.char1, 2))
        journal.move_to(self.char2, quiet=True)
        write(self.char2, journal, "Two", "Changed source.", page=2)
        self.assertIn("Second writer.", copy.read(self.char1, 2))
        with self.assertRaisesMessage(CraftingError, "Only blank journals"):
            write(self.char1, copy, "No", "Cannot edit editions.")
        journal.delete()
        self.assertIn("Second writer.", copy.read(self.char1, 2))
        self.assertTrue(ReadableEdition.objects.filter(craft=copy.craft_record).exists())

    def test_copy_of_copy_preserves_writer_instead_of_attributing_to_copier(self):
        original = self.book()
        first = self.copy(original)
        first.craft_record.crafter_name = "Untrusted cached rename"
        edition = self.copy(first)
        self.assertEqual(
            ReadableEdition.objects.get(craft=edition.craft_record).authors[0]["name"], "Char"
        )
        self.assertEqual(
            ReadableEdition.objects.get(craft=edition.craft_record).source_id, first.craft_record.pk
        )
        self.assertEqual(original.read(self.char1), edition.read(self.char1).split("\nText by")[0])
        self.assertIn("hallmark (OOC)", edition.get_display_desc(self.char1))

    def test_copy_respects_access_proximity_and_custom_readers(self):
        source = self.book()
        before = self.held()
        source.locks.add("read:false()")
        with self.assertRaises(CraftingError):
            self.copy(source)
        source.locks.add("read:all()")
        source.move_to(self.room2, quiet=True)
        with self.assertRaises(CraftingError):
            self.copy(source)
        source.move_to(self.char1, quiet=True)
        with (
            override_settings(
                RP_CRAFTING_BEHAVIOURS=conf.DEFAULT_BEHAVIOURS | {"readable": DeniedReadable}
            ),
            self.assertRaises(CraftingError),
        ):
            self.copy(source)
        self.assertEqual(self.held(), before)
        with override_settings(
            RP_CRAFTING_BEHAVIOURS=conf.DEFAULT_BEHAVIOURS | {"readable": RedactedReadable}
        ):
            edition = self.copy(source)
        self.assertEqual(
            edition.craft_record.verb_data[0]["configuration"]["pages"][0]["text"],
            "Only this text is public.",
        )
        self.assertEqual(
            ReadableEdition.objects.get(craft=edition.craft_record).authors[0]["id"], None
        )
        self.assertNotIn("record of the road", edition.read(self.char1))

    def test_copy_keeps_reader_bookmark_and_custom_reader_cannot_leak_journal_history(self):
        from .pages import BOOKMARK_CATEGORY

        source = self.book(
            configuration={"pages": [{"text": "First."}, {"text": "Last."}]},
            selected={"wood": 2},
        )
        source.read(self.char1, 2)
        copy_book(self.char1, source, "writing-0", "Edition", "A copy.", {"wood": 2})
        self.assertEqual(
            self.char1.attributes.get(
                f"craft_{source.craft_record.pk}", category=BOOKMARK_CATEGORY
            ),
            2,
        )
        journal = self.journal()
        write(self.char1, journal, "One", "Earlier private text.")
        write(self.char1, journal, "One", "Current text.", page=1)
        with (
            override_settings(
                RP_CRAFTING_BEHAVIOURS=conf.DEFAULT_BEHAVIOURS | {"readable": RedactedReadable}
            ),
            self.assertRaisesMessage(CraftingError, "does not expose journal history"),
        ):
            history(self.char1, journal, 1)

    def test_copies_pay_current_crafting_fees_and_rollback_the_fee_with_edition_failure(self):
        from django.apps import apps

        if not apps.is_installed("evennia_economy"):
            self.skipTest("Economy absent")
        from evennia_economy.services import balance

        source = self.book()
        before = balance(self.char1)
        with override_settings(RP_ECONOMY_FEE_CRAFT=7):
            edition = self.copy(source)
            self.assertEqual(edition.craft_record.money_spent, 7)
            self.assertEqual(balance(self.char1), before - 7)
            with (
                patch.object(ReadableEdition, "save", side_effect=ValueError("edition failed")),
                self.assertRaises(ValueError),
            ):
                self.copy(source)
            self.assertEqual(balance(self.char1), before - 7)

    def test_copy_source_changes_and_failure_after_payment_leave_no_spend_or_item(self):
        journal = self.journal()
        write(self.char1, journal, "One", "First.")
        expected = snapshot(self.char1, journal)[3]
        write(self.char1, journal, "One", "Updated.", page=1)
        before = self.held(), CraftRecord.objects.count(), ObjectDB.objects.count()
        with self.assertRaisesMessage(CraftingError, "source has changed"):
            self.copy(journal, expected=expected)
        with (
            patch.object(ReadableEdition, "save", side_effect=ValueError("edition failed")),
            self.assertRaises(ValueError),
        ):
            self.copy(journal)
        self.assertEqual(
            (self.held(), CraftRecord.objects.count(), ObjectDB.objects.count()), before
        )
        with self.assertRaisesMessage(CraftingError, "no written pages"):
            self.copy(self.journal())

    def test_journal_commands_and_draft_replacement(self):
        for args in (
            "/new writing-0/readable = Notebook",
            "/desc = A journal.",
            "/journal = 2",
            "/resources = wood:2",
        ):
            self.call(CmdCraft(), args, "Craft draft saved")
        self.call(CmdCraft(), "", "Draft: Notebook")
        output = self.call(CmdCraft(), "/finish", "You craft Notebook")
        self.assertIn("Hallmark (OOC):", output)
        self.call(CmdJournal(), "/write Notebook = Start | We arrived.", "Journal page 1 saved")
        self.call(
            CmdJournal(),
            "/revise Notebook = 1 | Start | We arrived at dawn.",
            "Journal page 1 saved (revision 2)",
        )
        output = self.call(CmdJournal(), "/history Notebook = 1", "Revision 1")
        self.assertIn("We arrived.", output)
        self.assertIn("We arrived at dawn.", output)
        self.call(CmdRead(), "Notebook", "Notebook\nPage 1 of 1: Start\nWe arrived at dawn.")

    def test_copy_draft_preview_finish_and_stale_source_refusal(self):
        journal = self.journal()
        write(self.char1, journal, "One", "First text.")
        self.call(CmdCraft(), f"/copy {journal.key} = writing-0/First edition", "Copy draft saved")
        output = self.call(CmdCraft(), "", "Copy draft: First edition")
        self.assertIn("First text.", output)
        self.assertIn("1 materials", output)
        self.call(CmdCraft(), "/text = Forged text", "Copy drafts allow")
        self.call(CmdCraft(), "/resources = wood:1", "Copy draft saved")
        write(self.char1, journal, "One", "Revised text.", page=1)
        self.call(CmdCraft(), "/finish", "The source has changed")
        self.call(CmdCraft(), f"/copy {journal.key} = writing-0/First edition", "Copy draft saved")
        self.call(CmdCraft(), "/resources = wood:1", "Copy draft saved")
        output = self.call(CmdCraft(), "/finish", "You copy First edition")
        self.assertIn("Hallmark (OOC):", output)
        self.assertFalse(self.char1.attributes.has(DRAFT_KEY))
        self.call(CmdCraft(), "/finish", "Start a draft")

    def test_copy_draft_desc_replaces_the_sources_binding_description(self):
        journal = self.journal()
        write(self.char1, journal, "One", "First text.")
        self.call(CmdCraft(), f"/copy {journal.key} = writing-0/Fair copy", "Copy draft saved")
        self.assertIn("A bound notebook.", self.call(CmdCraft(), "", "Copy draft: Fair copy"))
        self.call(CmdCraft(), "/desc = A slim printed copy.", "Copy draft saved")
        self.assertIn("A slim printed copy.", self.call(CmdCraft(), "", "Copy draft: Fair copy"))
        self.call(CmdCraft(), "/resources = wood:1", "Copy draft saved")
        self.call(CmdCraft(), "/finish", "You copy Fair copy")
        copy = ObjectDB.objects.get(db_key="Fair copy")
        self.assertEqual(copy.craft_record.prose["description"], "A slim printed copy.")
        self.assertEqual(copy.db.desc, "A slim printed copy.")
        self.assertIn("First text.", copy.read(self.char1))
