# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Public syntax preserves plot access, thread lifecycle and XP boundaries."""

import unittest
from decimal import Decimal
from unittest.mock import patch

from django.apps import apps
from evennia.utils import create
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_plots import commands, threads
from evennia_plots.models import (
    PlotArc,
    PlotParticipant,
    PlotThread,
    PlotUpdate,
    StoryThread,
    ThreadLink,
)


class TestPlotSyntax(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.plot = PlotThread.create_thread(name="Harbour Mystery", creator=self.char2)
        self.plot.activate()
        self.ref = f"#{self.plot.plot_number}"

    def invoke(self, cls, args, caller=None):
        return self.call(cls(), args, caller=caller or self.char2)

    def test_thread_new_view_and_explicit_reveal(self):
        self.assertIn("Added thread", self.invoke(commands.CmdThread, f"/new {self.ref}=Who rang?"))
        thread = self.plot.story_threads.get()
        self.invoke(commands.CmdThread, f"/seal {thread.ref}=The ferryman")
        self.assertNotIn("The ferryman", self.invoke(commands.CmdThread, thread.ref))
        self.invoke(commands.CmdThread, f"/resolve {thread.ref}=We solved it")
        thread.refresh_from_db()
        self.assertEqual(thread.status, StoryThread.Status.RESOLVED)
        self.assertFalse(thread.sealed_answer_revealed)
        self.assertIn("We solved it", self.invoke(commands.CmdThread, thread.ref))
        self.invoke(commands.CmdThread, f"/reveal {thread.ref}")
        self.assertIn("The ferryman", self.invoke(commands.CmdThread, thread.ref))

    def test_all_commands_reject_stacked_and_unknown_switches_without_mutation(self):
        for cls, args in (
            (commands.CmdPlot, f"/owner/remove {self.ref}={self.char2.key}"),
            (commands.CmdPlot, "/create/garbage Unwanted"),
            (commands.CmdArc, "/create/garbage Unwanted"),
            (commands.CmdHook, f"/garbage {self.ref}={self.char2.key}"),
        ):
            out = self.invoke(cls, args, self.char1)
            self.assertTrue("one switch" in out or "Unknown" in out, out)
        self.assertTrue(self.plot.is_owner(self.char2))
        self.assertFalse(PlotThread.objects.filter(name="Unwanted").exists())
        self.assertFalse(PlotArc.objects.filter(name="Unwanted").exists())
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.hook_log, [])

    def test_retired_thread_forms_and_combined_reveal_are_refused(self):
        out = self.invoke(commands.CmdPlot, f"/thread {self.ref}=Unwanted")
        self.assertIn("Unknown", out)
        self.assertFalse(self.plot.story_threads.exists())
        thread = threads.add_thread(self.plot, self.char2, "A question")
        threads.seal(thread, self.char2, "Secret")
        for args in (f"/resolve/reveal {thread.ref}=Solved", f"/drop/reveal {thread.ref}"):
            self.assertIn("one switch", self.invoke(commands.CmdThread, args))
        thread.refresh_from_db()
        self.assertEqual(thread.status, StoryThread.Status.OPEN)
        self.assertFalse(thread.sealed_answer_revealed)

    def test_thread_view_respects_requests_and_private_plots(self):
        self.plot.thread_policy = "request"
        self.plot.save()
        stranger = create.create_object("evennia.objects.objects.DefaultCharacter", key="Stranger")
        request = threads.add_thread(self.plot, stranger, "A pending question")
        self.assertIn("A pending question", self.invoke(commands.CmdThread, request.ref))
        self.assertIn("A pending question", self.invoke(commands.CmdThread, request.ref, stranger))
        viewer = create.create_object("evennia.objects.objects.DefaultCharacter", key="Viewer")
        self.assertNotIn("A pending question", self.invoke(commands.CmdThread, request.ref, viewer))
        other = PlotThread.create_thread(name="Private", creator=self.char1, privacy="private")
        other.activate()
        secret = threads.add_thread(other, self.char1, "Hidden question")
        self.assertNotIn("Hidden question", self.invoke(commands.CmdThread, secret.ref))
        self.assertIn("No plot", self.invoke(commands.CmdThread, secret.ref))

    def test_note_revise_major_unowner_and_related_accept(self):
        self.invoke(commands.CmdPlot, f"/note {self.ref}=An OOC note")
        block = self.plot.updates.get()
        self.assertEqual(block.update_type, "ooc")
        with patch.object(commands, "EvEditor") as editor:
            self.invoke(commands.CmdPlot, f"/revise {self.ref}/{block.block_number}")
        editor.assert_called_once()
        self.assertTrue(commands._update_save(self.char2, "A revision"))
        commands._update_quit(self.char2)
        block.refresh_from_db()
        self.assertEqual(block.content, "A revision")
        self.invoke(commands.CmdPlot, f"/major {self.ref}=Mystery", self.char1)
        self.assertTrue(self.plot.tags.get().is_major)
        self.invoke(commands.CmdPlot, f"/owner {self.ref}={self.char1.key}")
        self.invoke(commands.CmdPlot, f"/unowner {self.ref}={self.char1.key}")
        self.assertFalse(self.plot.is_owner(self.char1))
        other = PlotThread.create_thread(name="Related", creator=self.char1)
        other.activate()
        self.invoke(commands.CmdPlot, f"/relate {self.ref}=#{other.plot_number}")
        self.invoke(commands.CmdPlot, f"/accept #{other.plot_number}={self.ref}", self.char1)
        self.assertTrue(ThreadLink.objects.get(from_thread=self.plot, to_thread=other).is_accepted)

    def test_plot_list_status_and_tag_filters_and_prefixes(self):
        self.invoke(commands.CmdPlot, f"/tag {self.ref}=Mystery")
        self.assertIn("Harbour Mystery", self.invoke(commands.CmdPlot, "/TAGS Mystery"))
        self.assertNotIn("Harbour Mystery", self.invoke(commands.CmdPlot, "/tags Other"))
        self.assertIn("Harbour Mystery", self.invoke(commands.CmdPlot, "/list active"))
        self.assertNotIn("Harbour Mystery", self.invoke(commands.CmdPlot, "/list concluded"))
        self.assertIn("Usage", self.invoke(commands.CmdPlot, "/list invalid"))
        self.assertIn("one switch", self.invoke(commands.CmdPlot, "/list/active"))
        self.assertIn("Unknown", self.invoke(commands.CmdPlot, "/un"))

    def test_retired_plot_and_arc_switches_are_refused(self):
        for cls, forms in (
            (
                commands.CmdPlot,
                (
                    "update/ooc",
                    "update/edit",
                    "tag/major",
                    "link/scene",
                    "link/post",
                    "link/event",
                    "relate/accept",
                    "list/tag",
                ),
            ),
            (commands.CmdArc, ("update/ooc", "update/edit", "list/tag")),
        ):
            for form in forms:
                with self.subTest(command=cls.key, form=form):
                    self.assertIn(
                        "one switch", self.invoke(cls, f"/{form} {self.ref}=x", self.char1)
                    )
        self.assertFalse(PlotUpdate.objects.exists())
        self.assertFalse(self.plot.tags.exists())

    def test_arc_note_revise_list_and_xp_field(self):
        arc = PlotArc.create_arc(name="Season", creator=self.char1)
        ref = f"#{arc.arc_number}"
        self.invoke(commands.CmdArc, f"/note {ref}=OOC", self.char1)
        block = PlotUpdate.objects.get(arc=arc)
        self.assertEqual(block.update_type, "ooc")
        with patch.object(commands, "EvEditor") as editor:
            self.invoke(commands.CmdArc, f"/revise {ref}/{block.block_number}", self.char1)
        editor.assert_called_once()
        self.assertTrue(commands._update_save(self.char1, "Revised"))
        commands._update_quit(self.char1)
        block.refresh_from_db()
        self.assertEqual(block.content, "Revised")
        self.invoke(commands.CmdArc, f"/tag {ref}=Mystery", self.char1)
        self.assertIn("Season", self.invoke(commands.CmdArc, "/list Mystery", self.char1))
        self.assertNotIn("Season", self.invoke(commands.CmdArc, "/list Other", self.char1))
        self.invoke(commands.CmdArc, f"/xp {ref}/lore=2.5", self.char1)
        arc.refresh_from_db()
        self.assertEqual(arc.xp_mult_lore, Decimal("2.50"))
        for value in ("lore:3", "NaN", "Infinity"):
            self.invoke(commands.CmdArc, f"/xp {ref}/lore={value}", self.char1)
        arc.refresh_from_db()
        self.assertEqual(arc.xp_mult_lore, Decimal("2.50"))
        self.invoke(commands.CmdArc, f"/xp {ref}/lore=default", self.char1)
        arc.refresh_from_db()
        self.assertIsNone(arc.xp_mult_lore)
        self.invoke(commands.CmdArc, f"/xp {ref}=lore:3", self.char1)
        arc.refresh_from_db()
        self.assertIsNone(arc.xp_mult_lore)

    def test_hook_uses_plot_equals_recipient(self):
        self.assertIn(
            "Hook sent", self.invoke(commands.CmdHook, f"{self.ref}={self.char2.key}", self.char1)
        )
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.hook_log[-1]["target"], self.char2.key)
        self.invoke(commands.CmdHook, f"{self.char2.key}={self.ref}", self.char1)
        self.plot.refresh_from_db()
        self.assertEqual(len(self.plot.hook_log), 1)

    def test_request_lifecycle_and_thread_fields(self):
        self.invoke(commands.CmdPlot, f"/threads {self.ref}=request")
        player = create.create_object("evennia.objects.objects.DefaultCharacter", key="Requester")
        self.invoke(commands.CmdThread, f"/new {self.ref}=First request", player)
        thread = self.plot.story_threads.get()
        self.invoke(commands.CmdThread, f"/decline {thread.ref}=Already covered")
        thread.refresh_from_db()
        self.assertEqual((thread.status, thread.decline_reason), ("declined", "Already covered"))
        self.invoke(commands.CmdThread, f"/new {self.ref}=Second request", player)
        second = self.plot.story_threads.get(title="Second request")
        self.invoke(commands.CmdThread, f"/withdraw {second.ref}", player)
        self.assertFalse(StoryThread.objects.filter(pk=second.pk).exists())
        self.invoke(commands.CmdThread, f"/new {self.ref}=Third request", player)
        third = self.plot.story_threads.get(title="Third request")
        self.invoke(commands.CmdThread, f"/accept {third.ref}")
        self.invoke(commands.CmdThread, f"/detail {third.ref}=Look near the harbour")
        self.invoke(commands.CmdThread, f"/hold {third.ref}")
        third.refresh_from_db()
        self.assertEqual(
            (third.status, third.detail, third.is_held), ("open", "Look near the harbour", True)
        )
        self.invoke(commands.CmdThread, f"/hold {third.ref}")
        self.invoke(commands.CmdThread, f"/lead {third.ref}", player)
        self.invoke(commands.CmdThread, f"/interest {third.ref}")
        self.assertTrue(third.interests.get(character=player).is_lead)
        self.assertTrue(third.interests.filter(character=self.char2).exists())
        self.invoke(commands.CmdThread, f"/drop {third.ref}")
        self.invoke(commands.CmdThread, f"/reopen {third.ref}")
        third.refresh_from_db()
        self.assertEqual(third.status, "open")
        self.invoke(commands.CmdPlot, f"/conclude {self.ref}")
        sequel = PlotThread.create_thread(name="Next mystery", creator=self.char2)
        sequel.activate()
        self.invoke(commands.CmdPlot, f"/sequel #{sequel.plot_number}={self.ref}")
        self.invoke(commands.CmdThread, f"/carry {third.ref}=#{sequel.plot_number}")
        third.refresh_from_db()
        self.assertEqual(third.status, "carried")
        self.assertEqual(third.carried_to.plot, sequel)

    @unittest.skipUnless(apps.is_installed("evennia_xp"), "XP partner is absent")
    def test_arc_award_comment_keeps_dbrefs_and_refuses_colon_amounts(self):
        from evennia_xp.models import XPLog

        arc = PlotArc.create_arc(name="Awards", creator=self.char1)
        self.plot.arc = arc
        self.plot.save()
        PlotParticipant.objects.create(
            thread=self.plot, character=self.char2, character_name=self.char2.key
        )
        prefix = f"/award #{arc.arc_number}="
        self.invoke(commands.CmdArc, prefix + "2 # End of #12 # milestone", self.char1)
        log = XPLog.objects.get(character_id=self.char2.pk)
        self.assertEqual(log.amount, Decimal("2"))
        self.assertEqual(log.reason, f"plot_arc_#{arc.arc_number}: End of #12 # milestone")
        for value in ("3:Old reason", "NaN", "Infinity"):
            self.invoke(commands.CmdArc, prefix + value, self.char1)
        self.assertEqual(XPLog.objects.filter(character_id=self.char2.pk).count(), 1)
