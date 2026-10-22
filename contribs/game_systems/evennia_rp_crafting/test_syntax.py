# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Public syntax, refusal without side effects, and reviewed Workshop spending."""

import re
import time
from copy import deepcopy
from unittest.mock import patch

from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from . import services
from .commands import DRAFT_KEY, CmdCraft, CmdRead, CmdWorkshop
from .models import CraftRecord, JournalRevision, NicheDefinition, NicheUnlock, Workshop
from .readable_commands import CmdJournal
from .tests import CraftingFixture


class SyntaxTests(CraftingFixture, EvenniaCommandTest):
    def expect(self, command, args, text=None, **kwargs):
        output = self.call(command, args, **kwargs)
        if text:
            self.assertIn(text, output)
        return output

    def new(self):
        self.expect(CmdCraft(), "/new writing-0/readable=book", "draft saved")

    def preview(self, key="writing-0", amount=3):
        self.expect(CmdWorkshop(), f"/unlock {key}={amount} wood", "selected")
        output = self.expect(CmdWorkshop(), f"/unlock {key}", "Confirm:")
        return re.search(r"Confirm: \+workshop/unlock [^=]+=([^\s]+)", output)[1]

    def test_bare_values_keep_punctuation_and_refuse_old_equals(self):
        self.new()
        self.expect(CmdCraft(), "/desc A=B: a description | with ; punctuation", "draft saved")
        self.assertEqual(
            self.char1.attributes.get(DRAFT_KEY)["description"],
            "A=B: a description | with ; punctuation",
        )
        original = deepcopy(dict(self.char1.attributes.get(DRAFT_KEY)))
        self.expect(CmdCraft(), "/desc = Old form", "Usage:")
        self.expect(CmdCraft(), "/text = Old form", "Usage:")
        self.assertEqual(dict(self.char1.attributes.get(DRAFT_KEY)), original)

    def test_resource_selection_sets_each_key_and_removes_without_spending(self):
        self.new()
        self.expect(CmdCraft(), "/resources 2 wood", "draft saved")
        self.expect(CmdCraft(), "/resources 1 ore", "draft saved")
        self.expect(CmdCraft(), "/resources 3 wood", "draft saved")
        self.assertEqual(
            dict(self.char1.attributes.get(DRAFT_KEY)["selected"]), {"wood": 3, "ore": 1}
        )
        self.expect(CmdCraft(), "/unresource ore", "draft saved")
        self.assertEqual(dict(self.char1.attributes.get(DRAFT_KEY)["selected"]), {"wood": 3})
        original = deepcopy(dict(self.char1.attributes.get(DRAFT_KEY)))
        for value in (
            "= wood:2",
            "wood:2",
            "2 wood,1 ore",
            "0 wood",
            "-1 wood",
            "1.5 wood",
            "1 missing",
        ):
            self.call(CmdCraft(), "/resources " + value)
            self.assertEqual(dict(self.char1.attributes.get(DRAFT_KEY)), original)
        self.assertEqual(self.held(), 200)

    def test_raw_unknown_stacked_and_ambiguous_switches_cannot_mutate(self):
        self.new()
        original = deepcopy(dict(self.char1.attributes.get(DRAFT_KEY)))
        for value in ("/new/nope writing-0/readable=replaced", "/nope/finish", "/nope", "/un x"):
            self.expect(CmdCraft(), value, "switch")
            self.assertEqual(dict(self.char1.attributes.get(DRAFT_KEY)), original)
        self.expect(CmdCraft(), "/DeSc A new description", "draft saved")
        self.assertEqual(self.char1.attributes.get(DRAFT_KEY)["description"], "A new description")

    def test_workshop_selection_and_preview_do_not_pay_and_confirmation_is_single_use(self):
        token = self.preview()
        self.assertEqual(self.held(), 200)
        self.assertFalse(NicheUnlock.objects.exists())
        self.expect(CmdWorkshop(), f"/unlock writing-0={token}", "Unlocked Scribe 0")
        self.assertEqual(self.held(), 197)
        services.abandon(self.char1, "writing-0")
        self.call(CmdWorkshop(), f"/unlock writing-0={token}")
        self.assertEqual(self.held(), 197)
        self.assertEqual(NicheUnlock.objects.count(), 1)

    def test_workshop_old_syntax_tamper_expiry_and_other_actor_do_not_pay(self):
        self.call(CmdWorkshop(), "/unlock writing-0=wood:3")
        self.assertEqual(self.held(), 200)
        self.assertFalse(NicheUnlock.objects.exists())
        token = self.preview()
        self.call(CmdWorkshop(), f"/unlock writing-0={token}bad")
        self.call(CmdWorkshop(), f"/unlock writing-0={token}", caller=self.char2)
        with patch("django.core.signing.time.time", return_value=time.time() + 901):
            self.call(CmdWorkshop(), f"/unlock writing-0={token}")
        self.assertEqual(self.held(), 200)
        self.assertFalse(NicheUnlock.objects.exists())

    def test_workshop_changed_materials_catalog_and_slots_require_new_preview(self):
        token = self.preview()
        self.call(CmdWorkshop(), "/unlock writing-0=2 wood")
        self.call(CmdWorkshop(), f"/unlock writing-0={token}")
        token = self.preview()
        NicheDefinition.objects.filter(key="writing-0").update(unlock_money=101)
        self.call(CmdWorkshop(), f"/unlock writing-0={token}")
        NicheDefinition.objects.filter(key="writing-0").update(unlock_money=100)
        token = self.preview()
        self.unlock("writing-1")
        services.abandon(self.char1, "writing-1")
        self.call(CmdWorkshop(), f"/unlock writing-0={token}")
        self.assertEqual(self.held(), 197)
        self.assertFalse(NicheUnlock.objects.filter(niche__key="writing-0").exists())

    def test_workshop_failure_rolls_back_payment_and_confirmation_can_retry(self):
        token = self.preview()
        with patch.object(NicheUnlock.objects, "create", side_effect=ValueError("failed")):
            self.expect(CmdWorkshop(), f"/unlock writing-0={token}", "failed")
        self.assertEqual(self.held(), 200)
        self.assertEqual(Workshop.objects.get(character=self.char1).invested_money, 0)
        self.expect(CmdWorkshop(), f"/unlock writing-0={token}", "Unlocked")
        self.assertEqual(self.held(), 197)

    def test_journal_field_edits_preserve_other_field_and_history(self):
        self.unlock()
        journal = self.book(configuration={"journal": 3}, selected={"wood": 3})
        self.expect(CmdJournal(), f"/write {journal.key}=Original words.", "page 1 saved")
        self.expect(CmdJournal(), f"/title {journal.key}/1=First visit", "revision 2")
        self.expect(CmdJournal(), f"/revise {journal.key}/1=Revised words.", "revision 3")
        rows = list(JournalRevision.objects.order_by("revision").values_list("title", "text"))
        self.assertEqual(
            rows,
            [
                ("", "Original words."),
                ("First visit", "Original words."),
                ("First visit", "Revised words."),
            ],
        )
        self.expect(CmdJournal(), f"/history {journal.key}/1", "Original words.")
        for args in (
            f"/write {journal.key}=Title | Old body",
            f"/revise {journal.key}=1 | Title | Body",
            f"/history {journal.key}=1",
        ):
            self.call(CmdJournal(), args)
            self.assertEqual(JournalRevision.objects.count(), 3)
        journal.move_to(self.char2, quiet=True)
        self.expect(
            CmdJournal(), f"/title {journal.key}/1=Forged", "only your own", caller=self.char2
        )
        self.assertEqual(JournalRevision.objects.count(), 3)

    def test_read_requires_equals_and_prefers_whole_numeric_item_names(self):
        self.unlock()
        book = self.book(
            name="Volume 2",
            configuration={"pages": [{"text": "Page one"}, {"text": "Page two"}]},
            selected={"wood": 2},
        )
        self.expect(CmdRead(), "Volume 2", "Page one")
        self.expect(CmdRead(), "Volume 2=2", "Page two")
        self.assertNotIn("Page one", self.call(CmdRead(), "Volume 2 1"))
        self.assertEqual(CraftRecord.objects.filter(item_id=book.pk).count(), 1)

    def test_copy_uses_bare_description_and_editable_resource_keys(self):
        self.unlock()
        source = self.book()
        self.expect(CmdCraft(), f"/copy {source.key}=writing-0/Copy", "Copy draft saved")
        self.expect(CmdCraft(), "/desc A=B binding", "Copy draft saved")
        self.expect(CmdCraft(), "/resources 1 ore", "Copy draft saved")
        self.expect(CmdCraft(), "/resources 1 wood", "Copy draft saved")
        self.expect(CmdCraft(), "/unresource ore", "Copy draft saved")
        before = deepcopy(dict(self.char1.attributes.get(DRAFT_KEY)))
        self.expect(CmdCraft(), "/desc = Legacy", "Usage:")
        self.expect(CmdCraft(), "/resources wood:1", "Select one resource")
        self.assertEqual(dict(self.char1.attributes.get(DRAFT_KEY)), before)
        self.expect(CmdCraft(), "/finish", "You copy Copy")
        self.assertEqual(
            CraftRecord.objects.get(prose__name="Copy").prose["description"], "A=B binding"
        )

    def test_workshop_new_preview_cancel_and_runtime_freeze_invalidate_or_block(self):
        token = self.preview()
        newer = self.preview()
        self.call(CmdWorkshop(), f"/unlock writing-0={token}")
        self.assertFalse(NicheUnlock.objects.exists())
        with override_settings(RP_CRAFTING_FROZEN=True):
            self.expect(CmdWorkshop(), f"/unlock writing-0={newer}", "paused")
        self.call(CmdWorkshop(), "/cancel writing-0")
        self.call(CmdWorkshop(), f"/unlock writing-0={newer}")
        self.assertFalse(NicheUnlock.objects.exists())
        self.assertEqual(self.held(), 200)

    def test_workshop_selections_remove_one_key_and_old_syntax_never_overwrites(self):
        self.call(CmdWorkshop(), "/unlock writing-0=2 wood")
        self.call(CmdWorkshop(), "/unlock writing-0=1 ore")
        self.call(CmdWorkshop(), "/unresource writing-0=ore")
        self.call(CmdWorkshop(), "/unlock writing-0=3 wood")
        before = deepcopy(dict(self.char1.attributes.get("rp_workshop_unlock_drafts")))
        for args in (
            "/unlock writing-0=wood:3",
            "/unlock/nope writing-0=1 wood",
            "/unlock writing-0=2 wood,1 ore",
        ):
            self.call(CmdWorkshop(), args)
            self.assertEqual(dict(self.char1.attributes.get("rp_workshop_unlock_drafts")), before)
        self.expect(CmdWorkshop(), "/unlock writing-0", "Confirm:")
        self.assertEqual(self.held(), 200)
