# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Details and senses through actual host commands, seeds and optional partners."""

from unittest.mock import patch

from django.apps import apps
from django.core.management import call_command
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest
from evennia_rp_crafting.item_details import examine
from evennia_rp_crafting.models import CraftRecord
from typeclasses.characters import Character
from typeclasses.rooms import Room

from world.sandbox import crafting


class ItemDetailSeams(EvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room

    def commands(self):
        from commands.default_cmdsets import CharacterCmdSet

        return {row.key: type(row) for row in CharacterCmdSet().commands}

    def test_seeded_items_use_real_commands_without_reading_or_room_activity(self):
        call_command("seed_sandbox", verbosity=0)
        book = ObjectDB.objects.get(db_key=crafting.BOOK_NAME)
        lute = ObjectDB.objects.get(db_key=crafting.LUTE_NAME)
        self.char1.move_to(book.location, quiet=True)
        commands = self.commands()
        self.assertTrue({"look", "+smell", "+listen", "+touch"} <= set(commands))
        last_pose = self.char1.last_pose_time
        if apps.is_installed("evennia_scenes"):
            from evennia_scenes.models import LogEntry

            logs = LogEntry.objects.count()
        if apps.is_installed("evennia_lore"):
            from evennia_lore.models import LoreAcquisition

            known = LoreAcquisition.objects.filter(character=self.char1).count()
        with patch.object(type(book), "read", side_effect=AssertionError("Unexpected read")):
            output = self.call(commands["look"](), f"{book.key} = cover")
            self.assertIn(crafting.BOOK_DETAILS["cover"], output)
            self.assertIn(crafting.BOOK_SENSES["smell"], self.call(commands["+smell"](), book.key))
            self.assertIn(crafting.LUTE_SENSES["sound"], self.call(commands["+listen"](), lute.key))
            self.assertIn(crafting.LUTE_SENSES["touch"], self.call(commands["+touch"](), lute.key))
        self.assertEqual(self.char1.last_pose_time, last_pose)
        if apps.is_installed("evennia_scenes"):
            self.assertEqual(LogEntry.objects.count(), logs)
        if apps.is_installed("evennia_lore"):
            self.assertEqual(LoreAcquisition.objects.filter(character=self.char1).count(), known)
        self.assertIn("Warm lamplight", self.call(commands["look"](), ""))
        self.assertIn(crafting.FIXTURE_SMELL, self.call(commands["+smell"](), ""))

    def test_gifting_and_reseeding_preserve_original_snapshots(self):
        call_command("seed_sandbox", verbosity=0)
        item = ObjectDB.objects.get(db_key=crafting.BOOK_NAME)
        original = item.craft_record
        self.char1.move_to(item.location, quiet=True)
        item.move_to(self.char1, quiet=True)
        self.char2.move_to(self.char1.location, quiet=True)
        with self.captureOnCommitCallbacks(execute=True):
            self.call(self.commands()["give"](), f"{item.key} = {self.char2.key}", "You give")
        self.assertEqual(examine(self.char2, item, "cover"), crafting.BOOK_DETAILS["cover"])
        call_command("seed_sandbox", verbosity=0)
        original.refresh_from_db()
        self.assertEqual(original.prose["facets"]["details"], crafting.BOOK_DETAILS)
        self.assertTrue(CraftRecord.objects.filter(pk=original.pk).exists())
        replacement = ObjectDB.objects.get(db_key=crafting.BOOK_NAME)
        self.assertNotEqual(replacement.craft_record.pk, original.pk)
        self.assertEqual(replacement.craft_record.resources_spent, {"timber": 4})
