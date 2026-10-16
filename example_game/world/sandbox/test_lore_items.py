# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Actual host page commands, recognition inspection and persistent seed history."""

from unittest import skipUnless

from django.apps import apps
from django.core.management import call_command
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest
from evennia_lore.item_commands import CmdTome
from evennia_lore.models import LoreAcquisition, LoreEntry, LoreTomeRecord
from typeclasses.characters import Character
from typeclasses.rooms import Room

from world.sandbox import crafting


class LoreItemSeams(EvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room

    def test_real_read_command_teaches_only_the_seeded_page_and_unlocks_recognition(self):
        call_command("seed_sandbox", verbosity=0)
        tome = ObjectDB.objects.get(db_key=crafting.TOME_NAME)
        self.char2.move_to(tome.location, quiet=True)
        from commands.default_cmdsets import CharacterCmdSet

        command = type(next(row for row in CharacterCmdSet().commands if row.key == "read"))
        if apps.is_installed("evennia_rp_crafting"):
            from evennia_rp_crafting.errors import CraftingError
            from evennia_rp_crafting.services import craft_cost

            book = ObjectDB.objects.get(db_key=crafting.LORE_BOOK_NAME)
            self.assertNotIn("familiar sign", book.get_display_desc(self.char2))
            author = ObjectDB.objects.get(pk=book.craft_record.crafter_id)
            with self.assertRaisesMessage(CraftingError, "fixed authored pages"):
                craft_cost(
                    author,
                    "writing",
                    "readable",
                    {"journal": 2},
                    facets={"lore_citations": book.craft_record.prose["facets"]["lore_citations"]},
                )
            for name in (crafting.JOURNAL_NAME, crafting.EDITION_NAME):
                output = self.call(command(), f"{name} 1", f"{name}\n", caller=self.char2)
                self.assertIn("Text by (OOC):", output)
            self.assertFalse(LoreAcquisition.objects.filter(character=self.char2).exists())
        self.call(
            command(), f"/contents {tome.key}", f"{tome.key}\nContents (2 pages)", caller=self.char2
        )
        self.call(command(), f"{tome.key} 1", f"{tome.key}\nPage 1 of 2", caller=self.char2)
        self.assertFalse(LoreAcquisition.objects.filter(character=self.char2).exists())
        output = self.call(
            command(), f"{tome.key} 2", f"{tome.key}\nPage 2 of 2", caller=self.char2
        )
        self.assertIn("[Lore] You recognise", output)
        self.assertEqual(LoreAcquisition.objects.get(character=self.char2).source, "read")
        if apps.is_installed("evennia_rp_crafting"):
            self.assertIn("familiar sign", book.get_display_desc(self.char2))
        self.assertIn("+tome", {row.key for row in CharacterCmdSet().commands})
        self.assertFalse(CmdTome().access(self.char2))
        own_entry = LoreEntry.create_entry(
            "A visitor's account", self.char2, body="A visit to the market."
        )
        tome.locks.add("control:false()")
        lore_command = type(next(row for row in CharacterCmdSet().commands if row.key == "+lore"))
        self.call(
            lore_command(),
            f"/object #{own_entry.entry_number}={tome.key}",
            "Only staff or an object controller",
            caller=self.char2,
        )
        self.assertFalse(own_entry.objects_tagged.exists())

    def test_reseed_keeps_published_tome_history_and_replaces_the_visible_book(self):
        call_command("seed_sandbox", verbosity=0)
        tome = ObjectDB.objects.get(db_key=crafting.TOME_NAME)
        record = LoreTomeRecord.objects.get(item_id=tome.pk)
        call_command("seed_sandbox", verbosity=0)
        self.assertTrue(LoreTomeRecord.objects.filter(pk=record.pk).exists())
        new = ObjectDB.objects.get(db_key=crafting.TOME_NAME)
        self.assertNotEqual(LoreTomeRecord.objects.get(item_id=new.pk).pk, record.pk)

    @skipUnless(apps.is_installed("evennia_rp_crafting"), "crafting absent")
    def test_real_draft_commands_clear_stale_citations_before_publishing_a_journal(self):
        call_command("seed_sandbox", verbosity=0)
        book = ObjectDB.objects.get(db_key=crafting.LORE_BOOK_NAME)
        record = book.craft_record
        author = ObjectDB.objects.get(pk=record.crafter_id)
        lore = LoreEntry.objects.get(pk=record.prose["facets"]["lore_citations"][0]["entry"])
        from commands.default_cmdsets import CharacterCmdSet

        commands = {row.key: type(row) for row in CharacterCmdSet().commands}
        for args in ("/new writing/readable = New journal", "/desc = A journal.", "/text = Notes."):
            self.call(commands["+craft"](), args, "Craft draft saved", caller=author)
        self.call(
            commands["+lorecraft"](),
            f"/cite = #{lore.entry_number}",
            "Draft lore facets saved",
            caller=author,
        )
        self.call(commands["+craft"](), "/journal = 2", "Craft draft saved", caller=author)
        self.call(commands["+lorecraft"](), "/uncite 1", "Draft lore facets saved", caller=author)
        self.call(commands["+craft"](), "/resources = timber:2", "Craft draft saved", caller=author)
        self.call(commands["+craft"](), "/finish", "You craft New journal", caller=author)
        journal = ObjectDB.objects.get(db_key="New journal")
        self.assertNotIn("facets", journal.craft_record.prose)
        self.assertIn("no entries", journal.read(self.char2))
