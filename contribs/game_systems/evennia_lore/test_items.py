# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Item knowledge is explicit, published, holder-gated and independent of XP."""

from contextlib import suppress
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import override_settings
from evennia.objects.models import ObjectDB
from evennia.utils.test_resources import EvenniaCommandTest

from .commands import CmdForget, CmdLore
from .item_commands import CmdLoreCraft, CmdReadTome, CmdTome
from .items import LoreItemError, create_tome
from .models import LoreAcquisition, LoreEntry, LoreTomeRecord


def entry(author, title="An old legend", **kwargs):
    return LoreEntry.create_entry(title, author, body="IC account.", kind="legend", **kwargs)


class TomeTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.lore = entry(self.char1, privacy=LoreEntry.Privacy.RESTRICTED)
        self.lore.seal("A staff-only explanation.")

    def tome(self):
        return create_tome(
            self.char1,
            "Old tome",
            "A dusty book.",
            [
                {"title": "First", "text": "An introduction."},
                {"title": "Last", "text": "The legend."},
            ],
            [{"entry": self.lore.pk, "page": 2}],
        )

    def test_tome_read_acquires_only_selected_page_and_forget_is_reversible(self):
        book = self.tome()
        self.assertNotIn("recognise", book.read(self.char2, contents=True))
        self.assertNotIn("recognise", book.read(self.char2, 1))
        self.assertFalse(LoreAcquisition.objects.filter(character=self.char2).exists())
        with self.captureOnCommitCallbacks(execute=True):
            result = book.read(self.char2, 2)
        self.assertIn("[Lore] You recognise: An old legend", result)
        self.assertNotIn("staff-only", result)
        acquired = LoreAcquisition.objects.get(character=self.char2, entry=self.lore)
        self.assertEqual(acquired.source, "read")
        self.call(
            CmdForget(), f"#{self.lore.entry_number}", "You have forgotten", caller=self.char2
        )
        self.assertFalse(LoreAcquisition.objects.filter(pk=acquired.pk).exists())
        book.read(self.char2, 2)
        self.assertEqual(
            LoreAcquisition.objects.filter(character=self.char2, entry=self.lore).count(), 1
        )

    def test_tome_denied_invalid_and_withdrawn_reads_never_grant(self):
        book = self.tome()
        for lock in ("view:false()", "read:false()"):
            book.locks.add(lock)
            with self.assertRaises(ValueError):
                book.read(self.char2, 2)
            book.locks.add("view:all();read:all()")
        with self.assertRaises(ValueError):
            book.read(self.char2, 3)
        self.lore.status = LoreEntry.Status.SUBMITTED
        self.lore.save()
        self.assertNotIn("recognise", book.read(self.char2, 2))
        self.assertFalse(LoreAcquisition.objects.filter(character=self.char2).exists())

    def test_staff_only_fixed_records_ignore_editable_attributes_and_fail_atomically(self):
        with self.assertRaisesMessage(LoreItemError, "Staff only"):
            create_tome(self.char2, "Fake", "Fake.", [{"text": "Fake."}], [])
        book = self.tome()
        book.db.pages = [{"text": "Forged"}]
        book.db.citations = [{"entry": self.lore.pk, "page": 1}]
        self.assertNotIn("Forged", book.read(self.char2, 1))
        self.assertFalse(LoreAcquisition.objects.filter(character=self.char2).exists())
        record = LoreTomeRecord.objects.get(item_id=book.pk)
        with self.assertRaises(ValidationError):
            record.save()
        before = ObjectDB.objects.count()
        with (
            patch.object(LoreTomeRecord, "save", side_effect=ValueError("record failed")),
            self.assertRaises(ValueError),
        ):
            self.tome()
        self.assertEqual(ObjectDB.objects.count(), before)

    def test_staff_tome_draft_and_shared_read_navigation(self):
        for args in (
            "/new Chronicle 2",
            "/desc = An old chronicle.",
            "/page One = First.",
            "/page Two = Last.",
            f"/cite 2 = #{self.lore.entry_number}",
        ):
            self.call(CmdTome(), args, "Tome draft saved")
        self.call(CmdTome(), "", "Tome draft: Chronicle 2")
        self.call(CmdTome(), "/publish", "Published Chronicle 2")
        self.call(CmdReadTome(), "Chronicle 2", "Chronicle 2\nPage 1 of 2: One")
        self.call(CmdReadTome(), "Chronicle 2 = 2", "Chronicle 2\nPage 2 of 2: Two")
        self.call(CmdReadTome(), "/contents Chronicle 2", "Chronicle 2\nContents (2 pages)")

    def test_object_tag_authority_requires_control_of_target(self):
        lore = entry(self.char2, "A personal account")
        self.obj1.locks.add("control:false()")
        self.call(
            CmdLore(),
            f"/object #{lore.entry_number}={self.obj1.key}",
            "Only staff or an object controller",
            caller=self.char2,
        )
        self.assertFalse(lore.objects_tagged.exists())
        self.obj1.locks.add(f"control:id({self.char2.pk})")
        self.call(
            CmdLore(), f"/object #{lore.entry_number}={self.obj1.key}", "Tagged", caller=self.char2
        )
        self.obj1.locks.add("control:false()")
        self.call(
            CmdLore(),
            f"/unobject #{lore.entry_number}={self.obj1.key}",
            "Only staff or an object controller",
            caller=self.char2,
        )
        self.assertTrue(lore.objects_tagged.exists())

    def test_failed_bookmark_write_rolls_back_tome_acquisition(self):
        book = self.tome()
        with (
            patch.object(self.char2.attributes, "add", side_effect=ValueError("bookmark failed")),
            self.assertRaises(ValueError),
        ):
            book.read(self.char2, 2)
        self.assertFalse(LoreAcquisition.objects.filter(character=self.char2).exists())

    def test_tomes_are_readable_while_crafting_is_hidden(self):
        book = self.tome()
        book.move_to(self.room1, quiet=True)
        with override_settings(RP_CRAFTING_REVEALED=False):
            self.call(CmdReadTome(), f"{book.key}=2", f"{book.key}\nPage 2 of 2", caller=self.char2)
        self.assertTrue(
            LoreAcquisition.objects.filter(character=self.char2, source="read").exists()
        )


if apps.is_installed("evennia_rp_crafting"):
    from evennia_rp_crafting.tests import CraftingFixture
else:

    class CraftingFixture:
        pass


@skipUnless(apps.is_installed("evennia_rp_crafting"), "crafting absent")
class CraftedLoreTests(CraftingFixture, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.unlock()
        self.lore = entry(self.char1)
        LoreAcquisition.objects.create(entry=self.lore, character=self.char1, source="seed")

    def book_with_lore(self, **kwargs):
        return self.book(
            facets={"lore_citations": [{"entry": self.lore.pk, "page": 2}]},
            configuration={"pages": [{"text": "First."}, {"text": "Last."}]},
            selected={"wood": 2},
            **kwargs,
        )

    def test_only_explicit_canonical_page_reads_grant_knowledge_and_no_xp_links(self):
        from evennia_rp_crafting.composition import invoke
        from evennia_rp_crafting.pages import configuration

        from .models import LoreInspirationCredit, LoreSceneLink

        book = self.book_with_lore()
        configuration(self.char2, book)
        invoke(self.char2, book, "readable")
        book.read(self.char2, contents=True)
        book.read(self.char2, 1)
        self.assertFalse(LoreAcquisition.objects.filter(character=self.char2).exists())
        self.assertIn("[Lore] You recognise", book.read(self.char2, 2))
        self.assertEqual(LoreAcquisition.objects.get(character=self.char2).source, "read")
        book.read(self.char2, 2)
        self.assertEqual(LoreAcquisition.objects.filter(character=self.char2).count(), 1)
        self.assertEqual(
            (LoreSceneLink.objects.count(), LoreInspirationCredit.objects.count()), (0, 0)
        )

    def test_book_wide_citation_applies_to_any_selected_page_without_passive_ceiling(self):
        book = self.book(
            configuration={"pages": [{"text": "One"}, {"text": "Two"}]},
            selected={"wood": 2},
            facets={"lore_citations": [{"entry": self.lore.pk}]},
        )
        with override_settings(LORE_PASSIVE_WEEKLY_CEILING=0):
            self.assertIn("You recognise", book.read(self.char2, 2))

    def test_crafter_must_hold_published_lore_even_when_it_is_public(self):
        from evennia_rp_crafting.errors import CraftingError

        before = self.held()
        LoreAcquisition.objects.filter(character=self.char1).delete()
        with self.assertRaisesMessage(CraftingError, "must hold"):
            self.book_with_lore()
        self.assertEqual(self.held(), before)

    def test_journal_citations_wait_for_revision_scoped_support(self):
        from evennia_rp_crafting.errors import CraftingError
        from evennia_rp_crafting.models import CraftRecord

        before = self.held(), CraftRecord.objects.count()
        with self.assertRaisesMessage(CraftingError, "fixed authored pages"):
            self.book(
                configuration={"journal": 2},
                selected={"wood": 2},
                facets={"lore_citations": [{"entry": self.lore.pk}]},
            )
        self.assertEqual((self.held(), CraftRecord.objects.count()), before)

    def test_custom_redaction_denial_and_failed_reads_cannot_grant(self):
        from evennia_rp_crafting import conf
        from evennia_rp_crafting.test_pages import DeniedReadable, RedactedReadable

        book = self.book_with_lore()
        for implementation in (DeniedReadable, RedactedReadable):
            with (
                override_settings(
                    RP_CRAFTING_BEHAVIOURS=conf.DEFAULT_BEHAVIOURS | {"readable": implementation}
                ),
                suppress(ValueError),
            ):
                book.read(self.char2)
        with self.assertRaises(ValueError):
            book.read(self.char2, 99)
        book.locks.add("read:false()")
        with self.assertRaises(ValueError):
            book.read(self.char2, 2)
        self.assertFalse(LoreAcquisition.objects.filter(character=self.char2).exists())

    def test_recognition_costs_one_input_and_only_holders_or_staff_see_it(self):
        from evennia_rp_crafting.errors import CraftingError

        metadata = {"lore_recognition": [{"entry": self.lore.pk, "text": "A hidden woven sign."}]}
        with self.assertRaises(CraftingError):
            self.book(facets=metadata)
        book = self.book(facets=metadata, selected={"wood": 2})
        book.db.facets = {"lore_recognition": [{"text": "Forged."}]}
        self.assertIn("hidden woven sign", book.get_display_desc(self.char1))
        self.assertNotIn("hidden woven sign", book.get_display_desc(self.char2))
        self.assertFalse(LoreAcquisition.objects.filter(character=self.char2).exists())
        self.char2.permissions.add("Builder")
        self.account2.permissions.add("Builder")
        self.assertIn("recognition gate", book.get_display_desc(self.char2))
        self.char2.permissions.remove("Builder")
        self.account2.permissions.remove("Builder")
        LoreAcquisition.objects.create(entry=self.lore, character=self.char2, source="shared")
        self.assertIn("you recognise this", book.get_display_desc(self.char2))
        self.assertNotIn("hidden", " ".join(book.get_market_keywords(self.char2)))
        self.assertNotIn("hidden", book.get_display_name(self.char2))
        self.lore.delete()
        self.assertNotIn("hidden woven sign", book.get_display_desc(self.char2))
        self.char2.permissions.add("Builder")
        self.account2.permissions.add("Builder")
        self.assertIn("missing lore PK", book.get_display_desc(self.char2))

    def test_draft_citations_recognition_preview_and_finish(self):
        from evennia_rp_crafting.commands import CmdCraft

        for args in ("/new writing-0/readable = Codex", "/desc = A codex.", "/text = An account."):
            self.call(CmdCraft(), args, "Craft draft saved")
        self.call(CmdLoreCraft(), f"/cite = #{self.lore.entry_number}", "Draft lore facets saved")
        self.call(
            CmdLoreCraft(),
            f"/recognise #{self.lore.entry_number}=A hidden sign.",
            "Draft lore facets saved",
        )
        output = self.call(CmdCraft(), "", "Draft: Codex")
        self.assertIn("2 materials", output)
        self.assertIn("hidden sign", output)
        self.call(CmdCraft(), "/resources = wood:2", "Craft draft saved")
        self.call(CmdCraft(), "/finish", "You craft Codex")
        self.assertTrue(ObjectDB.objects.get(db_key="Codex").craft_record.prose["facets"])

    def test_failed_bookmark_write_rolls_back_crafted_page_acquisition(self):
        book = self.book_with_lore()
        with (
            patch.object(self.char2.attributes, "add", side_effect=ValueError("bookmark failed")),
            self.assertRaises(ValueError),
        ):
            book.read(self.char2, 2)
        self.assertFalse(LoreAcquisition.objects.filter(character=self.char2).exists())

    def test_stale_draft_features_can_be_removed_without_revalidating_the_others(self):
        from evennia_rp_crafting.commands import DRAFT_KEY, CmdCraft
        from evennia_rp_crafting.models import CraftRecord

        for args in ("/new writing-0/readable = Codex", "/desc = A codex.", "/text = An account."):
            self.call(CmdCraft(), args, "Craft draft saved")
        self.call(CmdLoreCraft(), f"/cite = #{self.lore.entry_number}", "Draft lore facets saved")
        for line in ("A hidden sign.", "Another sign."):
            self.call(
                CmdLoreCraft(),
                f"/recognise #{self.lore.entry_number}={line}",
                "Draft lore facets saved",
            )
        LoreAcquisition.objects.filter(character=self.char1, entry=self.lore).delete()
        before = self.held(), CraftRecord.objects.count()
        self.call(CmdCraft(), "/finish", "You must hold that lore entry")
        self.call(CmdLoreCraft(), "/uncite 1", "Draft lore facets saved")
        self.call(CmdLoreCraft(), "/unrecognise 1", "Draft lore facets saved")
        self.call(CmdLoreCraft(), "/unrecognise 1", "Draft lore facets saved")
        self.assertEqual(dict(self.char1.attributes.get(DRAFT_KEY)["facets"]), {})
        self.assertEqual((self.held(), CraftRecord.objects.count()), before)
        self.call(CmdCraft(), "/resources = wood:1", "Craft draft saved")
        self.call(CmdCraft(), "/finish", "You craft Codex")

    def test_citations_can_be_cleared_after_changing_a_draft_to_a_journal(self):
        from evennia_rp_crafting.commands import DRAFT_KEY, CmdCraft

        for args in (
            "/new writing-0/readable = Journal",
            "/desc = A journal.",
            "/text = An account.",
        ):
            self.call(CmdCraft(), args, "Craft draft saved")
        self.call(CmdLoreCraft(), f"/cite = #{self.lore.entry_number}", "Draft lore facets saved")
        self.call(CmdCraft(), "/journal = 2", "Craft draft saved")
        self.call(CmdLoreCraft(), "/uncite 1", "Draft lore facets saved")
        self.assertNotIn("lore_citations", self.char1.attributes.get(DRAFT_KEY)["facets"])
        self.call(CmdCraft(), "/resources = wood:2", "Craft draft saved")
        self.call(CmdCraft(), "/finish", "You craft Journal")

    def test_shared_read_command_refuses_hidden_crafts_and_lorecraft_is_hidden(self):
        book = self.book_with_lore()
        book.move_to(self.room1, quiet=True)
        with override_settings(RP_CRAFTING_REVEALED=False):
            self.assertFalse(CmdLoreCraft().access(self.char1))
            self.call(CmdReadTome(), f"{book.key}=2", "Crafting is unavailable.", caller=self.char2)
        self.assertFalse(LoreAcquisition.objects.filter(character=self.char2).exists())

    def test_invalid_facets_and_changed_lore_never_spend(self):
        from evennia_rp_crafting.errors import CraftingError
        from evennia_rp_crafting.models import CraftRecord

        invalid = [
            {"unknown": []},
            {"lore_citations": [{"entry": self.lore.pk, "page": 0}]},
            {"lore_citations": [{"entry": self.lore.pk, "page": True}]},
            {"lore_citations": [{"entry": self.lore.pk, "other": 1}]},
            {"lore_citations": [{"entry": self.lore.pk}] * 2},
            {"lore_recognition": [{"entry": self.lore.pk, "text": ""}]},
            {"lore_recognition": [{"entry": self.lore.pk, "text": "Hidden\nline"}]},
            {
                "lore_recognition": [
                    {"entry": self.lore.pk, "text": "Hidden", "niche": "not-contributing"}
                ]
            },
        ]
        before = self.held(), CraftRecord.objects.count()
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(CraftingError):
                self.book(facets=value)
        self.lore.status = LoreEntry.Status.SUBMITTED
        self.lore.save()
        with self.assertRaises(CraftingError):
            self.book_with_lore()
        self.assertEqual((self.held(), CraftRecord.objects.count()), before)

    @skipUnless(apps.is_installed("evennia_rp_equipment"), "equipment absent")
    def test_recognition_on_equipment_uses_viewer_sensitive_inspection(self):
        from evennia_rp_crafting import services
        from evennia_rp_equipment.commands import render_info

        self.unlock("weaving")
        item = services.craft(
            self.char1,
            "weaving",
            "wearable",
            "Cloak",
            "A cloak.",
            {},
            {"wood": 2},
            facets={"lore_recognition": [{"entry": self.lore.pk, "text": "The hidden pattern."}]},
        )
        self.assertIn("hidden pattern", render_info(item, self.char1))
        self.assertNotIn("hidden pattern", render_info(item, self.char2))
