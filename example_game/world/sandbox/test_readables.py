# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Journals and editions under the reference game's real command and sale paths."""

from django.apps import apps
from django.core.management import call_command
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest
from evennia_rp_crafting.models import JournalRevision, ReadableEdition
from evennia_rp_crafting.readable_commands import CmdJournal
from evennia_rp_crafting.readables import write
from typeclasses.characters import Character
from typeclasses.rooms import Room

from world.sandbox import crafting


class ReadableSeams(EvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room

    def test_seeded_history_survives_reseed_and_real_gift_transfers_writing(self):
        from commands.default_cmdsets import CharacterCmdSet

        call_command("seed_sandbox", verbosity=0)
        journal = ObjectDB.objects.get(db_key=crafting.JOURNAL_NAME)
        edition = ObjectDB.objects.get(db_key=crafting.EDITION_NAME)
        if apps.is_installed("evennia_rp_equipment"):
            from evennia_rp_equipment.commands import render_info

            cloak = ObjectDB.objects.get(db_key=crafting.CLOAK_NAME)
            self.assertIn("Craft hallmark (OOC):", render_info(cloak, self.char1))
        self.assertIn("+journal", {command.key for command in CharacterCmdSet().commands})
        journal.move_to(self.char1, quiet=True)
        self.call(
            CmdJournal(),
            f"/write {journal.key} = A visitor wrote this.",
            "Journal page 2 saved",
        )
        give = next(command for command in CharacterCmdSet().commands if command.key == "give")
        with self.captureOnCommitCallbacks(execute=True):
            self.call(
                type(give)(), f"{journal.key} = {self.char2.key}", "You give", caller=self.char1
            )
        self.call(
            CmdJournal(),
            f"/revise {journal.key}/2 = Wrong.",
            "You may revise only your own",
            caller=self.char2,
        )
        self.call(
            CmdJournal(),
            f"/write {journal.key} = Another writer.",
            "Journal page 3 saved",
            caller=self.char2,
        )
        self.assertNotIn("visitor", edition.read(self.char2))
        record_id = journal.craft_record.pk
        call_command("seed_sandbox", verbosity=0)
        self.assertEqual(JournalRevision.objects.filter(craft_id=record_id).count(), 3)
        self.assertTrue(ReadableEdition.objects.filter(source_id=record_id).exists())
        replacement = ObjectDB.objects.get(db_key=crafting.JOURNAL_NAME)
        self.assertNotEqual(replacement.craft_record.pk, record_id)

    def test_real_stall_sale_transfers_journal_writing_without_changing_earlier_authors(self):
        if not apps.is_installed("evennia_economy"):
            self.skipTest("Economy absent")
        from evennia_economy.services import credit
        from evennia_economy.stalls import buy, claim, list_stock

        call_command("seed_sandbox", verbosity=0)
        journal = ObjectDB.objects.get(db_key=crafting.JOURNAL_NAME)
        journal.move_to(self.char1, quiet=True)
        first_writer = JournalRevision.objects.get(craft=journal.craft_record).author_id
        self.room1.tags.add("market", category="rp_economy")
        credit(self.char2, 20)
        store = claim(self.char1, name="Journal counter")
        with self.captureOnCommitCallbacks(execute=True):
            listing = list_stock(
                self.char1, store.pk, [{"kind": "item", "key": str(journal.pk), "quantity": 1}], 10
            )
        with self.captureOnCommitCallbacks(execute=True):
            buy(self.char2, listing.pk)
        write(self.char2, journal, "New owner", "Bought at the counter.")
        entries = list(JournalRevision.objects.filter(craft=journal.craft_record))
        self.assertEqual([entry.author_id for entry in entries], [first_writer, self.char2.pk])
