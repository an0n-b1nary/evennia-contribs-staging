# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Single-switch authoring, record-first sharing and explicit page addresses."""

from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.test import override_settings
from evennia.utils.dbserialize import deserialize
from evennia.utils.test_resources import EvenniaCommandTest

from .commands import CmdLore, CmdShare, _lore_submit_save
from .item_commands import CmdLoreCraft, CmdReadTome, CmdTome
from .items import create_tome
from .models import LoreAcquisition, LoreEntry, LoreSceneLink, LoreTag, PlotLoreLink


class LoreSyntaxTests(EvenniaCommandTest):
    def expect(self, command, args, text, **kwargs):
        output = self.call(command, args, **kwargs)
        self.assertIn(text, output)
        return output

    @override_settings(LORE_REQUIRE_APPROVAL=True)
    def test_submit_then_kind_and_scene_work_for_the_author_before_approval(self):
        with patch("evennia_links.editing.EvEditor") as editor:
            self.call(CmdLore(), "/SuB A visitor's story", caller=self.char2)
            editor.assert_called_once()
        _lore_submit_save(self.char2, "An account of the road.")
        entry = LoreEntry.objects.get(title="A visitor's story")
        self.assertEqual(entry.status, LoreEntry.Status.SUBMITTED)
        self.expect(CmdLore(), f"/ki #{entry.entry_number}=rumor", "now a Rumor", caller=self.char2)
        scene = MagicMock()
        scene.objects.get.return_value = SimpleNamespace(pk=55, scene_number=9001)
        with patch("evennia_lore.commands._get_model", return_value=scene):
            self.expect(
                CmdLore(), f"/sc #{entry.entry_number}=9001", "Linked scene", caller=self.char2
            )
        scene.objects.get.assert_called_once_with(scene_number=9001)
        self.assertEqual(LoreSceneLink.objects.get(entry=entry).scene_id, 55)
        entry.refresh_from_db()
        self.assertEqual(entry.kind, "rumor")
        self.assertEqual(entry.status, LoreEntry.Status.SUBMITTED)
        self.assertFalse(LoreAcquisition.objects.filter(entry=entry).exists())

    def test_old_stacked_and_unknown_switches_cannot_open_an_editor_or_add_tags(self):
        entry = LoreEntry.create_entry("An account", self.char1, body="The road.")
        with patch("evennia_links.editing.EvEditor") as editor:
            for args in (
                "/submit/rumor Old rumor",
                "/submit/scene 9001=Old scene",
                "/submit/scene/legend 9001=Old legend",
                "/submit/nope Old title",
                f"/tag/major #{entry.entry_number}=History",
                f"/tag/nope #{entry.entry_number}=History",
                "/notaswitch ignored",
            ):
                with self.subTest(args=args):
                    self.call(CmdLore(), args)
            editor.assert_not_called()
        self.assertIsNone(self.char1.db.links_editing_context)
        self.assertFalse(LoreTag.objects.exists())
        self.assertFalse(entry.tags.exists())

    def test_scene_plot_and_major_are_single_switches_and_keep_permissions(self):
        entry = LoreEntry.create_entry("An account", self.char2, body="The road.")
        number = entry.entry_number
        scene, plot = MagicMock(), MagicMock()
        scene.objects.get.return_value = SimpleNamespace(pk=55)
        plot.objects.get.return_value = SimpleNamespace(pk=66, plot_number=9002)
        with patch("evennia_lore.commands._get_model", side_effect=[scene, plot]):
            self.expect(CmdLore(), f"/scene #{number}=9001", "Linked scene", caller=self.char2)
            self.expect(CmdLore(), f"/plot #{number}=#9002", "Linked entry", caller=self.char2)
        self.expect(CmdLore(), f"/major #{number}=History", "Only staff", caller=self.char2)
        self.assertFalse(LoreTag.objects.exists())
        self.expect(CmdLore(), f"/MA #{number}=History", "created and added")
        self.assertTrue(entry.tags.get().is_major)
        for suffix in ("scene", "plot"):
            self.expect(CmdLore(), f"/link/{suffix} #{number}=9003", "one switch")
        self.assertEqual(LoreSceneLink.objects.get(entry=entry).scene_id, 55)
        self.assertEqual(PlotLoreLink.objects.get(entry=entry).thread_id, 66)

    @override_settings(LORE_REQUIRE_APPROVAL=True)
    def test_other_authors_cannot_configure_unpublished_entries(self):
        entry = LoreEntry.create_entry("A private submission", self.char1, body="A secret.")
        with patch("evennia_lore.commands._get_model") as lookup:
            for switch, value in (("kind", "rumor"), ("scene", "9001"), ("plot", "9002")):
                self.expect(
                    CmdLore(),
                    f"/{switch} #{entry.entry_number}={value}",
                    "No lore entry",
                    caller=self.char2,
                )
            lookup.assert_not_called()
        entry.refresh_from_db()
        self.assertEqual(entry.kind, "fact")
        self.assertFalse(LoreSceneLink.objects.exists())
        self.assertFalse(PlotLoreLink.objects.exists())

    @override_settings(LORE_REQUIRE_APPROVAL=False)
    def test_sharing_is_entry_then_character_and_keeps_holder_and_publication_guards(self):
        entry = LoreEntry.create_entry("A shared account", self.char1, body="The road.")
        number = entry.entry_number
        self.call(CmdShare(), f"{self.char2.key}=#{number}")
        self.assertFalse(LoreAcquisition.objects.exists())
        self.expect(CmdShare(), f"#{number}={self.char1.key}", "don't have", caller=self.char2)
        self.expect(CmdShare(), f"#{number}={self.char2.key}", "Shared")
        acquisition = LoreAcquisition.objects.get(entry=entry, character=self.char2)
        self.assertEqual((acquisition.source, acquisition.shared_by_id), ("shared", self.char1.pk))
        self.expect(CmdShare(), f"#{number}={self.char2.key}", "already has")
        self.expect(CmdShare(), f"#{number}={self.char2.key}", "yourself", caller=self.char2)
        entry.status = LoreEntry.Status.SUBMITTED
        entry.save(update_fields=["status"])
        self.expect(CmdShare(), f"#{number}={self.char1.key}", "No lore entry", caller=self.char2)
        self.assertEqual(LoreAcquisition.objects.count(), 1)

    @override_settings(LORE_REQUIRE_APPROVAL=False)
    def test_read_pages_require_equals_and_do_not_grant_on_old_or_stacked_forms(self):
        entry = LoreEntry.create_entry("An account", self.char1, body="The road.")
        book = create_tome(
            self.char1,
            "Old tome",
            "A book.",
            [{"text": "First."}, {"text": "Last."}],
            [{"entry": entry.pk, "page": 2}],
        )
        book.move_to(self.room1, quiet=True)
        for args in (
            "Old tome 2",
            "/contents/nope Old tome",
            "/nope Old tome=2",
            "/contents Old tome=2",
            "Old tome=invalid",
            "Old tome=0",
        ):
            self.call(CmdReadTome(), args, caller=self.char2)
            self.assertFalse(LoreAcquisition.objects.filter(character=self.char2).exists())
        self.expect(CmdReadTome(), "Old tome=2", "Page 2 of 2", caller=self.char2)
        self.assertEqual(LoreAcquisition.objects.get(character=self.char2).source, "read")
        book.key = "Chronicle 2"
        book.save()
        self.expect(CmdReadTome(), "/CONT Chronicle 2", "Contents (2 pages)", caller=self.char2)
        self.expect(CmdReadTome(), "Chronicle 2=1", "Page 1 of 2", caller=self.char2)
        self.expect(CmdReadTome(), "Chronicle 2", "Page 1 of 2", caller=self.char2)

    def test_item_command_raw_guards_preserve_existing_drafts(self):
        self.call(CmdTome(), "/new Chronicle")
        before = deserialize(self.char1.attributes.get("lore_tome_draft"))
        self.expect(CmdTome(), "/page/nope Preface=Unwanted text.", "one switch")
        self.expect(CmdTome(), "/publish/nope", "one switch")
        self.expect(CmdTome(), "/notaswitch", "Unknown or ambiguous")
        self.expect(CmdTome(), "/desc = Old description", "Usage:")
        self.assertEqual(deserialize(self.char1.attributes.get("lore_tome_draft")), before)
        self.expect(CmdTome(), "/desc A=B: a chronicle", "draft saved")
        self.assertEqual(
            deserialize(self.char1.attributes.get("lore_tome_draft"))["description"],
            "A=B: a chronicle",
        )


if apps.is_installed("evennia_rp_crafting"):
    from evennia_rp_crafting.tests import CraftingFixture
else:

    class CraftingFixture:
        pass


@skipUnless(apps.is_installed("evennia_rp_crafting"), "crafting absent")
class RecognitionSyntaxTests(CraftingFixture, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.unlock()
        with override_settings(LORE_REQUIRE_APPROVAL=False):
            self.lore = LoreEntry.create_entry("A sign", self.char1, body="An account.")
        LoreAcquisition.objects.create(entry=self.lore, character=self.char1, source="seed")
        from evennia_rp_crafting.commands import CmdCraft

        for args in ("/new writing-0/readable = Codex", "/desc A codex.", "/text An account."):
            self.call(CmdCraft(), args)

    def test_recognition_addresses_entry_and_optional_contributing_niche(self):
        from evennia_rp_crafting.commands import DRAFT_KEY
        from evennia_rp_crafting.services import craft_cost

        for address in (f"#{self.lore.entry_number}", f"#{self.lore.entry_number}/writing-0"):
            result = self.call(CmdLoreCraft(), f"/RECO {address}=A familiar sign.")
            self.assertIn("Draft lore facets saved", result)
        draft = deserialize(self.char1.attributes.get(DRAFT_KEY))
        rows = draft["facets"]["lore_recognition"]
        self.assertEqual(
            rows,
            [
                {"entry": self.lore.pk, "text": "A familiar sign."},
                {"entry": self.lore.pk, "text": "A familiar sign.", "niche": "writing-0"},
            ],
        )
        cost = craft_cost(
            self.char1,
            draft["niche"],
            draft["behaviour"],
            draft["configuration"],
            facets=draft["facets"],
        )
        self.assertEqual(sum(cost[3]["resources"].values()), 3)

    def test_old_invalid_and_stacked_recognition_never_changes_draft_or_resources(self):
        from evennia_rp_crafting.commands import DRAFT_KEY

        before = deserialize(self.char1.attributes.get(DRAFT_KEY)), self.held()
        for args in (
            f"/recognise = #{self.lore.entry_number} | Old sign.",
            f"/recognise writing-0 = #{self.lore.entry_number} | Old sign.",
            f"/recognise/nope #{self.lore.entry_number}=Old sign.",
            f"/recognise #{self.lore.entry_number}/writing-0/other=Bad address.",
            f"/recognise #{self.lore.entry_number}/=Bad address.",
            f"/recognise #{self.lore.entry_number}/not-contributing=Bad niche.",
            f"/recognise #{self.lore.entry_number}=",
            f"/recognise #{self.lore.entry_number}=Hidden\nline",
        ):
            with self.subTest(args=args):
                self.call(CmdLoreCraft(), args)
                self.assertEqual(
                    (deserialize(self.char1.attributes.get(DRAFT_KEY)), self.held()), before
                )
        LoreAcquisition.objects.filter(character=self.char1).delete()
        self.call(CmdLoreCraft(), f"/recognise #{self.lore.entry_number}=Unheld sign.")
        self.assertEqual(deserialize(self.char1.attributes.get(DRAFT_KEY)), before[0])
