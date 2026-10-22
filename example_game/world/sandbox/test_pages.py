# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real host dispatch, seeded pages and immutable history across reseeding."""

from django.core.management import call_command
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest
from evennia_rp_crafting.commands import CmdRead
from evennia_rp_crafting.models import CraftRecord
from typeclasses.characters import Character
from typeclasses.rooms import Room

from world.sandbox import crafting


class PageSeams(EvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room

    def test_seeded_pages_use_host_read_command_and_reseed_keeps_history(self):
        call_command("seed_sandbox", verbosity=0)
        book = ObjectDB.objects.get(db_key=crafting.PAGED_BOOK_NAME)
        record_id = book.craft_record.pk
        self.assertEqual(
            book.craft_record.verb_data[0]["configuration"], {"pages": crafting.BOOK_PAGES}
        )
        self.char1.move_to(book.location, quiet=True)
        self.call(
            CmdRead(),
            f"/contents {book.key}",
            f"{book.key}\nContents (2 pages):\n1. Market Row\n2. The Common Road",
        )
        self.call(CmdRead(), f"{book.key} 2", "Could not find")
        self.call(CmdRead(), f"{book.key}=2", f"{book.key}\nPage 2 of 2: The Common Road")
        self.call(CmdRead(), book.key, f"{book.key}\nPage 2 of 2: The Common Road")
        self.char1.move_to(self.room1, quiet=True)
        call_command("seed_sandbox", verbosity=0)
        self.assertTrue(CraftRecord.objects.filter(pk=record_id).exists())
        replacement = ObjectDB.objects.get(db_key=crafting.PAGED_BOOK_NAME)
        self.assertNotEqual(replacement.craft_record.pk, record_id)
        self.assertIn("Page 1 of 2", replacement.read(self.char1))

    def test_ordinary_gift_preserves_pages_and_each_readers_position(self):
        call_command("seed_sandbox", verbosity=0)
        book = ObjectDB.objects.get(db_key=crafting.PAGED_BOOK_NAME)
        book.move_to(self.char1, quiet=True)
        provenance = book.get_display_provenance()
        self.assertIn("Page 2 of 2", book.read(self.char1, 2))
        from commands.default_cmdsets import CharacterCmdSet

        give = next(command for command in CharacterCmdSet().commands if command.key == "give")
        with self.captureOnCommitCallbacks(execute=True):
            self.call(type(give)(), f"{book.key} = {self.char2.key}", "You give", caller=self.char1)
        self.assertEqual(book.location, self.char2)
        self.assertIn("Page 1 of 2", book.read(self.char2))
        self.assertEqual(book.get_display_provenance(), provenance)
