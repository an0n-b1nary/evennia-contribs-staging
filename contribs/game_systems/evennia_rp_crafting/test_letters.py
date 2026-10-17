# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Sealed text cannot escape through copies/history; IC stamps prove no identity."""

from copy import deepcopy
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest

from . import conf, letters, services
from .commands import DRAFT_KEY, CmdCraft, CmdCrafting, CmdRead, CraftingCmdSet
from .errors import CraftingError
from .letter_commands import CmdLetter
from .models import CraftRecord, JournalRevision, LetterState, ReadableEdition
from .readables import copy_book, history, snapshot, write
from .test_pages import DeniedReadable, RedactedReadable
from .tests import CraftingFixture


class LetterFixture(CraftingFixture):
    def setUp(self):
        super().setUp()
        self.unlock()
        # A previously crafted signet remains usable when Equipment is absent.
        # Its verified snapshot, rather than typeclass attributes, supplies it.
        self.signet = self.book(name="Old signet")
        record = self.signet.craft_record
        CraftRecord.objects.filter(pk=record.pk).update(
            behaviour="wearable",
            verbs=[],
            prose={
                "configuration": {},
                "facets": {"signet": {"design": "The Courier's Rose", "niche": "weaving"}},
            },
        )

    def letter(self, **kwargs):
        return self.book(facets={"letter": {"addressee": "The Keeper"}}, **kwargs)

    def state(self, item):
        return LetterState.objects.get(craft=item.craft_record)

    def copy(self, item, **kwargs):
        return copy_book(
            self.char1, item, "writing-0", "Letter copy", "A fresh copy.", {"wood": 1}, **kwargs
        )


class LetterTests(LetterFixture, EvenniaCommandTest):
    def test_addressee_is_descriptive_and_first_read_breaks_once(self):
        item = self.letter()
        record = item.craft_record
        prose = deepcopy(record.prose)
        letters.seal(self.char1, item, self.signet)
        self.assertIn("intact", item.get_display_desc(self.char2))
        self.assertNotIn("record of the road", item.get_display_desc(self.char2))
        # A different character, not named by the addressee, can read it.
        result = item.read(self.char2)
        self.assertIn("You break the seal: The Courier's Rose", result)
        self.assertIn("A record of the road.", result)
        state = self.state(item)
        self.assertIsNotNone(state.first_opened_at)
        self.assertFalse(state.intact)
        later = item.read(self.char1)
        self.assertNotIn("You break the seal", later)
        self.assertIn("Addressed to (IC): The Keeper", later)
        self.assertIn("Seal (IC): The Courier's Rose — broken.", later)
        self.assertIn("broken", item.get_display_desc(self.char1))
        self.assertEqual(self.state(item).first_opened_at, state.first_opened_at)
        self.assertEqual(CraftRecord.objects.get(pk=record.pk).prose, prose)

    def test_contents_invalid_pages_and_failed_reads_do_not_open_or_expose_text(self):
        item = self.letter()
        letters.seal(self.char1, item, self.signet)
        self.assertIn("sealed", item.read(self.char1, contents=True))
        for number in (0, 2, -1, True):
            with self.subTest(number=number), self.assertRaises(CraftingError):
                item.read(self.char1, number)
        item.locks.add("read:false()")
        with self.assertRaises(CraftingError):
            item.read(self.char1)
        item.locks.add("read:all()")
        with (
            override_settings(
                RP_CRAFTING_BEHAVIOURS=conf.DEFAULT_BEHAVIOURS | {"readable": DeniedReadable}
            ),
            self.assertRaises(CraftingError),
        ):
            item.read(self.char1)
        self.assertTrue(self.state(item).intact)
        self.assertIsNone(self.state(item).first_opened_at)

    def test_copy_drafts_previews_and_paid_copy_cannot_open_or_leak_a_sealed_letter(self):
        item = self.letter()
        letters.seal(self.char1, item, self.signet)
        before = self.held(), CraftRecord.objects.count(), ObjectDB.objects.count()
        for action in (lambda: snapshot(self.char1, item), lambda: self.copy(item)):
            with self.assertRaisesMessage(CraftingError, "break the intact seal first"):
                action()
        output = self.call(CmdCraft(), f"/copy {item.key} = writing-0/Copy", "Read a page")
        self.assertNotIn("record of the road", output)
        self.assertFalse(self.char1.attributes.has(DRAFT_KEY))
        self.assertTrue(self.state(item).intact)
        self.assertEqual(
            (self.held(), CraftRecord.objects.count(), ObjectDB.objects.count()), before
        )

    def test_copies_retain_editable_addressee_and_honest_authors_but_no_stamp_or_lore(self):
        item = self.letter()
        letters.seal(self.char1, item, self.signet)
        item.read(self.char1)
        copy = self.copy(item)
        state = self.state(copy)
        self.assertEqual(state.addressee, "The Keeper")
        self.assertEqual(state.seal_number, 0)
        self.assertIsNone(state.signet)
        self.assertNotIn("signet", copy.craft_record.prose["facets"])
        self.assertIn("Copied by Char; text by Char", copy.get_display_provenance())
        self.assertEqual(
            ReadableEdition.objects.get(craft=copy.craft_record).source_id, item.craft_record.pk
        )
        letters.address(self.char1, copy, "Someone Else")
        self.assertEqual(self.state(item).addressee, "The Keeper")
        letters.seal(self.char1, copy, self.signet)
        self.assertNotIn("Previously opened", copy.get_display_desc(self.char1))

    def test_resealing_retains_history_and_never_thaws_journal_or_addressee(self):
        item = self.letter(configuration={"journal": 2}, selected={"wood": 2})
        write(self.char1, item, "Before", "First version.")
        write(self.char1, item, "Before", "Frozen version.", page=1)
        letters.seal(self.char1, item, self.signet)
        before = JournalRevision.objects.count()
        with self.assertRaisesMessage(CraftingError, "intact seal"):
            history(self.char1, item, 1)
        for opened in (False, True):
            if opened:
                item.read(self.char1)
            for page in (None, 1):
                with self.assertRaisesMessage(CraftingError, "permanently freezes"):
                    write(self.char1, item, "After", "Tampered.", page=page)
            with self.assertRaisesMessage(CraftingError, "permanently freezes"):
                letters.address(self.char1, item, "New recipient")
        self.assertIn("First version.", history(self.char1, item, 1))
        first_opened = self.state(item).first_opened_at
        letters.seal(self.char1, item, self.signet)
        self.assertIn(
            "Previously opened; resealed (impression 2)", item.get_display_desc(self.char1)
        )
        self.assertTrue(self.state(item).intact)
        with self.assertRaisesMessage(CraftingError, "intact seal"):
            history(self.char1, item, 1)
        self.assertIn("Frozen version.", item.read(self.char2))
        self.assertEqual(self.state(item).first_opened_at, first_opened)
        self.assertEqual(JournalRevision.objects.count(), before)

    def test_custody_access_frozen_runtime_and_plain_items_cannot_supply_a_signet(self):
        item = self.letter()
        for lock in ("view:false()", "read:false()", "write:false()"):
            item.locks.add(lock)
            with self.assertRaises(CraftingError):
                letters.seal(self.char1, item, self.signet)
            item.locks.add("view:all();read:all();write:all()")
        item.move_to(self.room1, quiet=True)
        with self.assertRaisesMessage(CraftingError, "Carry the letter"):
            letters.seal(self.char1, item, self.signet)
        item.move_to(self.char1, quiet=True)
        self.signet.move_to(self.char2, quiet=True)
        with self.assertRaisesMessage(CraftingError, "Carry a signet"):
            letters.seal(self.char1, item, self.signet)
        self.signet.move_to(self.char1, quiet=True)
        self.signet.locks.add("use:false()")
        with self.assertRaisesMessage(CraftingError, "Carry a signet"):
            letters.seal(self.char1, item, self.signet)
        self.signet.locks.add("use:all()")
        item.db.signet = {"design": "Not provenance"}
        with self.assertRaisesMessage(CraftingError, "no crafted signet design"):
            letters.seal(self.char1, item, item)
        with override_settings(RP_CRAFTING_FROZEN=True), self.assertRaises(CraftingError):
            letters.seal(self.char1, item, self.signet)
        with override_settings(RP_CRAFTING_REVEALED=False), self.assertRaises(CraftingError):
            letters.address(self.char1, item, "Hidden")
        self.assertEqual(self.state(item).seal_number, 0)

    def test_empty_journal_and_duplicate_seal_are_rejected_and_failed_reads_roll_back(self):
        blank = self.letter(configuration={"journal": 1})
        with self.assertRaisesMessage(CraftingError, "at least one page"):
            letters.seal(self.char1, blank, self.signet)
        item = self.letter()
        letters.seal(self.char1, item, self.signet)
        with self.assertRaisesMessage(CraftingError, "already has an intact seal"):
            letters.seal(self.char1, item, self.signet)
        with (
            patch(
                "evennia_rp_crafting.facets.read_lines", side_effect=RuntimeError("failed output")
            ),
            self.assertRaises(RuntimeError),
        ):
            item.read(self.char1)
        self.assertTrue(self.state(item).intact)
        self.assertEqual(self.state(item).seal_number, 1)

    def test_source_resealing_invalidates_preview_and_even_reopened_copy_drafts(self):
        item = self.letter()
        expected = snapshot(self.char1, item)[3]
        self.call(CmdCraft(), f"/copy {item.key} = writing-0/Copy", "Copy draft saved")
        letters.seal(self.char1, item, self.signet)
        self.call(CmdCraft(), "", "Read a page")
        self.call(CmdCraft(), "/finish", "Read a page")
        item.read(self.char1)
        self.call(CmdCraft(), "/finish", "The source has changed")
        before = self.held()
        with self.assertRaisesMessage(CraftingError, "source has changed"):
            self.copy(item, expected=expected)
        self.assertEqual(self.held(), before)
        self.assertFalse(ReadableEdition.objects.exists())

    def test_copy_rechecks_access_and_source_addressee_and_rolls_back_letter_state(self):
        item = self.letter()
        expected = snapshot(self.char1, item)[3]
        item.locks.add("read:false()")
        with self.assertRaises(CraftingError):
            self.copy(item, expected=expected)
        item.locks.add("read:all()")
        letters.address(self.char1, item, "Changed")
        with self.assertRaisesMessage(CraftingError, "source has changed"):
            self.copy(item, expected=expected)
        before = self.held(), LetterState.objects.count(), CraftRecord.objects.count()
        with (
            patch.object(ReadableEdition, "save", side_effect=RuntimeError("failed edition")),
            self.assertRaises(RuntimeError),
        ):
            self.copy(item)
        self.assertEqual(
            (self.held(), LetterState.objects.count(), CraftRecord.objects.count()), before
        )

    def test_custom_reader_redaction_is_preserved_and_dispatch_uses_successful_read(self):
        item = self.letter()
        letters.seal(self.char1, item, self.signet)
        with override_settings(
            RP_CRAFTING_BEHAVIOURS=conf.DEFAULT_BEHAVIOURS | {"readable": RedactedReadable}
        ):
            result = item.read(self.char1)
            self.assertIn("Only this text is public.", result)
            self.assertNotIn("record of the road", result)
            copy = self.copy(item)
            self.assertIsNone(ReadableEdition.objects.get(craft=copy.craft_record).authors[0]["id"])
        letters.seal(self.char1, item, self.signet)
        from .composition import invoke

        self.assertIn("You break the seal", invoke(self.char1, item, "readable"))

    def test_signet_loss_and_user_attributes_do_not_change_the_impression(self):
        item = self.letter()
        letters.seal(self.char1, item, self.signet)
        self.signet.db.seal_design = "Forged cached design"
        self.signet.delete()
        item.db.seal_design = "Forged letter design"
        self.assertIn("The Courier's Rose", item.get_display_desc(self.char1))
        self.assertNotIn("Forged", item.get_display_desc(self.char1))
        self.assertIn("The Courier's Rose", item.read(self.char1))
        self.assertTrue(self.state(item).signet_id)

    def test_staff_can_review_seal_provenance_after_the_physical_letter_is_deleted(self):
        item = self.letter()
        state = letters.seal(self.char1, item, self.signet)
        record_id = item.craft_record.pk
        item.read(self.char1)
        item.delete()
        self.call(CmdCrafting(), f"/review {record_id}", "Staff only.")
        self.char1.permissions.add("Builder")
        self.account.permissions.add("Builder")
        output = self.call(CmdCrafting(), f"/review {record_id}", f"Craft #{record_id}")
        self.assertIn(f"signet craft #{state.signet_id}", output)
        self.assertIn("sealed by Char", output)
        self.assertIn("intact False", output)

    def test_commands_cover_authoring_sealing_copy_readdressing_and_cmdset(self):
        self.assertIn("+letter", {row.key for row in CraftingCmdSet().commands})
        for arg in (
            "/new writing-0/readable = Message",
            "/desc = A folded letter.",
            "/text = Come at dawn.",
            "/addressee = The Keeper",
            "/resources = wood:1",
        ):
            self.call(CmdCraft(), arg, "Craft draft saved")
        self.call(CmdCraft(), "/finish", "You craft Message")
        self.call(CmdLetter(), "/seal Message = Old signet", "You seal Message")
        self.call(CmdRead(), "/contents Message", "Message\nThe letter is sealed")
        self.call(CmdRead(), "Message", "Message\nYou break the seal")
        self.call(CmdCraft(), "/copy Message = writing-0/New letter", "Copy draft saved")
        self.call(CmdCraft(), "/addressee = A Friend", "Copy draft saved")
        output = self.call(CmdCraft(), "", "Copy draft: New letter")
        self.assertIn("A Friend", output)
        self.call(CmdCraft(), "/resources = wood:1", "Copy draft saved")
        self.call(CmdCraft(), "/finish", "You copy New letter")
        copy = ObjectDB.objects.get(db_key="New letter")
        self.assertEqual(self.state(copy).addressee, "A Friend")
        self.call(
            CmdLetter(),
            "/address New letter = Another Friend",
            "Letter addressed to (IC): Another Friend",
        )
        self.assertEqual(self.state(copy).seal_number, 0)

    def test_letter_facet_and_addressee_validation_leave_no_spend(self):
        before = self.held(), CraftRecord.objects.count()
        for value in (
            "not a mapping",
            {},
            {"addressee": "ok", "permission": "private"},
            {"addressee": "x\ny"},
            {"addressee": "|rRed"},
            {"addressee": "x" * 256},
        ):
            with self.subTest(value=value), self.assertRaises(CraftingError):
                self.book(facets={"letter": value})
        self.assertEqual((self.held(), CraftRecord.objects.count()), before)

    def test_blank_draft_addressee_clears_the_letter_facet(self):
        self.call(CmdCraft(), "/new writing-0/readable = Message", "Craft draft saved")
        self.call(CmdCraft(), "/addressee = The Keeper", "Craft draft saved")
        self.assertIn("letter", self.char1.attributes.get(DRAFT_KEY)["facets"])
        self.call(CmdCraft(), "/addressee =", "Craft draft saved")
        self.assertNotIn("letter", self.char1.attributes.get(DRAFT_KEY)["facets"])


@skipUnless(
    apps.is_installed("evennia_rp_equipment"),
    "Equipment absent; existing signets are covered above",
)
class SignetCraftTests(CraftingFixture, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.unlock("weaving")
        override = override_settings(RP_CRAFTING_SIGNET_NICHES=["weaving"])
        override.enable()
        self.addCleanup(override.disable)

    def signet(self, **overrides):
        params = {
            "actor": self.char1,
            "key": "weaving",
            "behaviour_key": "wearable",
            "name": "Rose signet",
            "description": "An engraved ring.",
            "configuration": {"worn_line": "a signet ring", "slot": "finger"},
            "selected": {"wood": 2},
            "facets": {"signet": {"design": "The Courier's Rose"}},
        }
        return services.craft(**(params | overrides))

    def test_signet_pays_its_niche_cost_and_stamp_is_forgeable_ic(self):
        before = self.held()
        first = self.signet()
        second = self.signet()
        self.assertEqual(self.held(), before - 4)
        self.assertEqual(
            first.craft_record.prose["facets"]["signet"]["design"],
            second.craft_record.prose["facets"]["signet"]["design"],
        )
        self.assertIn("Signet design (IC): The Courier's Rose", first.get_display_desc(self.char1))
        self.assertIn("Made by Char", first.get_display_provenance())

    def test_signet_requires_permitted_contribution_valid_design_cost_and_unlock(self):
        before = self.held(), CraftRecord.objects.count()
        for value in (
            {"design": ""},
            {"design": "x\ny"},
            {"design": "|rRed"},
            {"design": "Rose", "niche": "writing-0"},
            {"design": "Rose", "unknown": True},
        ):
            with self.subTest(value=value), self.assertRaises(CraftingError):
                self.signet(facets={"signet": value})
        with override_settings(RP_CRAFTING_SIGNET_NICHES=[]), self.assertRaises(CraftingError):
            self.signet()
        with (
            override_settings(
                RP_CRAFTING_COSTS=conf.DEFAULT_COSTS | {"signet": {"base": {"provisions": 1}}}
            ),
            self.assertRaises(CraftingError),
        ):
            self.signet()
        self.assertEqual((self.held(), CraftRecord.objects.count()), before)
        services.abandon(self.char1, "weaving")
        with self.assertRaisesMessage(CraftingError, "Unlock that niche"):
            self.signet()

    def test_signet_command_draft_can_be_corrected_before_spending(self):
        for arg in (
            "/new weaving/wearable = New ring",
            "/desc = A ring.",
            "/line = a ring",
            "/signet = A Rose",
        ):
            self.call(CmdCraft(), arg, "Craft draft saved")
        self.call(CmdCraft(), "", "Draft: New ring")
        self.call(CmdCraft(), "/unsignet", "Craft draft saved")
        self.assertNotIn("signet", self.char1.attributes.get(DRAFT_KEY)["facets"])
        self.call(CmdCraft(), "/signet = Another Rose", "Craft draft saved")
        self.call(CmdCraft(), "/resources = wood:2", "Craft draft saved")
        self.call(CmdCraft(), "/finish", "You craft New ring")
