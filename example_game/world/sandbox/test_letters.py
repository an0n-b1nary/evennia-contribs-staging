# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Letters through real host commands, equipment, gifts and optional lore."""

from unittest import skipUnless

from django.apps import apps
from django.core.management import call_command
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest
from evennia_rp_crafting import services
from evennia_rp_crafting.errors import CraftingError
from evennia_rp_crafting.letters import seal
from evennia_rp_crafting.models import LetterState
from evennia_rp_resources.services import grant
from typeclasses.characters import Character
from typeclasses.rooms import Room

from world.sandbox import crafting


class LetterSeams(EvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room

    def commands(self):
        from commands.default_cmdsets import CharacterCmdSet

        return {row.key: type(row) for row in CharacterCmdSet().commands}

    def test_seeded_letter_uses_host_read_and_copy_commands_without_an_identity_gate(self):
        call_command("seed_sandbox", verbosity=0)
        commands = self.commands()
        self.assertIn("+letter", commands)
        letter = ObjectDB.objects.get(db_key=crafting.LETTER_NAME)
        state = LetterState.objects.get(craft=letter.craft_record)
        self.char2.move_to(letter.location, quiet=True)
        if not apps.is_installed("evennia_rp_equipment"):
            self.assertEqual(state.seal_number, 0)
            self.assertIn(crafting.LETTER_TEXT, letter.read(self.char2))
            return
        self.assertTrue(state.intact)
        self.call(
            commands["+craft"](),
            f"/copy {letter.key} = writing/Copy",
            "Read a page",
            caller=self.char2,
        )
        self.call(
            commands["read"](),
            f"/contents {letter.key}",
            f"{letter.key}\nThe letter is sealed",
            caller=self.char2,
        )
        state.refresh_from_db()
        self.assertTrue(state.intact)
        output = self.call(
            commands["read"](), letter.key, f"{letter.key}\nYou break the seal", caller=self.char2
        )
        self.assertIn(crafting.LETTER_TEXT, output)
        self.assertIn("broken", letter.get_display_desc(self.char2))
        old_record = letter.craft_record.pk
        call_command("seed_sandbox", verbosity=0)
        self.assertTrue(
            LetterState.objects.filter(craft_id=old_record, opened_at__isnull=False).exists()
        )
        replacement = ObjectDB.objects.get(db_key=crafting.LETTER_NAME)
        self.assertTrue(LetterState.objects.get(craft=replacement.craft_record).intact)

    @skipUnless(apps.is_installed("evennia_rp_equipment"), "Equipment absent")
    def test_gifted_signet_needs_no_workshop_and_real_worn_item_can_stamp(self):
        call_command("seed_sandbox", verbosity=0)
        commands = self.commands()
        signet = ObjectDB.objects.get(db_key=crafting.SIGNET_NAME)
        letter = ObjectDB.objects.get(db_key=crafting.LETTER_NAME)
        signet.move_to(self.char1, quiet=True)
        letter.move_to(self.char1, quiet=True)
        letter.read(self.char1)
        # Equipment wearing does not hide the carried signet from sealing.
        self.call(commands["+wear"](), signet.key, "You put on")
        self.call(
            commands["+letter"](), f"/seal {letter.key} = {signet.key}", f"You seal {letter.key}"
        )
        self.assertIn("Previously opened; resealed", letter.get_display_desc(self.char1))
        with self.captureOnCommitCallbacks(execute=True):
            self.call(commands["give"](), f"{letter.key} = {self.char2.key}", "You give")
        with self.assertRaisesMessage(CraftingError, "permanently freezes"):
            from evennia_rp_crafting.letters import address

            address(self.char2, letter, "A replacement addressee")
        self.call(
            commands["read"](), letter.key, f"{letter.key}\nYou break the seal", caller=self.char2
        )
        self.assertIn("broken", letter.get_display_desc(self.char1))

    @skipUnless(
        apps.is_installed("evennia_rp_equipment") and apps.is_installed("evennia_lore"),
        "Equipment or Lore absent",
    )
    def test_seal_opening_and_lore_grant_share_the_successful_page_read(self):
        from evennia_lore.models import LoreAcquisition
        from evennia_rp_crafting.readables import copy_book

        call_command("seed_sandbox", verbosity=0)
        source = ObjectDB.objects.get(db_key=crafting.LORE_BOOK_NAME)
        author = ObjectDB.objects.get(pk=source.craft_record.crafter_id)
        grant(author, "timber", 10, "staff", note="Letter seam inputs")
        citations = source.craft_record.prose["facets"]["lore_citations"]
        book = services.craft(
            author,
            "writing",
            "readable",
            "Cited letter",
            "A folded field report.",
            {"pages": crafting.BOOK_PAGES},
            {"timber": 2},
            facets={"letter": {"addressee": "The Keeper"}, "lore_citations": citations},
        )
        signet = ObjectDB.objects.get(db_key=crafting.SIGNET_NAME)
        signet.move_to(author, quiet=True)
        seal(author, book, signet)
        book.move_to(self.char2, quiet=True)
        read = self.commands()["read"]
        self.call(
            read(), f"/contents {book.key}", f"{book.key}\nThe letter is sealed", caller=self.char2
        )
        self.call(read(), f"{book.key} = 99", "Choose a page", caller=self.char2)
        self.assertTrue(LetterState.objects.get(craft=book.craft_record).intact)
        self.assertFalse(LoreAcquisition.objects.filter(character=self.char2).exists())
        output = self.call(
            read(), f"{book.key} = 2", f"{book.key}\nYou break the seal", caller=self.char2
        )
        self.assertIn("[Lore] You recognise", output)
        self.assertEqual(LoreAcquisition.objects.get(character=self.char2).source, "read")
        self.assertFalse(LetterState.objects.get(craft=book.craft_record).intact)
        book.move_to(author, quiet=True)
        edition = copy_book(
            author, book, "writing", "Letter edition", "A fresh copy.", {"timber": 2}
        )
        self.assertNotIn("lore_citations", edition.craft_record.prose.get("facets", {}))
        self.assertEqual(LetterState.objects.get(craft=edition.craft_record).seal_number, 0)
