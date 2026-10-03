# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Commands: +sheet, +stats, +pips, +lock, +unlock and staff +chargen.

char1 is a Developer (staff); char2 is an ordinary player.
"""

from __future__ import annotations

from django.core import checks
from django.test import override_settings

from evennia_rp_chargen import locks, services
from evennia_rp_chargen.commands import (
    ChargenCmdSet,
    CmdChargen,
    CmdLock,
    CmdPips,
    CmdSheet,
    CmdStats,
    CmdUnlock,
)
from evennia_rp_chargen.models import CharacterBuild
from evennia_rp_chargen.stats import StatHandler

from .base import POINT_BUY, ChargenCommandTest


@override_settings(RP_CHARGEN_ALLOCATION=POINT_BUY, RP_CHARGEN_PIP_BUDGET=3)
class PlayerCommandTests(ChargenCommandTest):
    def test_draft_to_finalized(self):
        self.call(CmdStats(), "", "Brawn", caller=self.char2)
        self.call(
            CmdStats(),
            "brawn=High",
            "Brawn is now High. (3 of 4 build points spent)",
            caller=self.char2,
        )
        self.call(CmdStats(), "brains=High", "That costs 6 build points", caller=self.char2)
        self.call(CmdStats(), "/finalize", "Not yet: Set Brains, Charm.", caller=self.char2)
        self.call(CmdStats(), "brains=Mid", "Brains is now Mid.", caller=self.char2)
        self.call(CmdStats(), "charm=Low", "Charm is now Low.", caller=self.char2)
        self.call(
            CmdStats(), "/finalize", "Sheet finalized. You're ready to play.", caller=self.char2
        )
        self.call(CmdStats(), "brawn=Mid", "Your stats are final.", caller=self.char2)

    def test_stats_clear_and_usage(self):
        self.call(CmdStats(), "brawn=High", "Brawn is now High.", caller=self.char2)
        self.call(
            CmdStats(), "/clear brawn", "Cleared. 0 of 4 build points spent", caller=self.char2
        )
        self.call(CmdStats(), "brawn", "Usage: +stats <stat>=<rung>", caller=self.char2)

    def test_pips(self):
        self.make_sheet(self.char2, brawn="Mid", brains="Mid", charm="Mid")
        self.call(CmdPips(), "brawn=++", "Brawn is now Mid ++.", caller=self.char2)
        self.call(CmdPips(), "/set brains=1", "Brains is now Mid +.", caller=self.char2)
        self.call(CmdPips(), "charm=1", "That's 4 edge in all, and you have 3.", caller=self.char2)
        self.call(CmdPips(), "/weakness brawn=-", "Brawn is now Mid ++ -.", caller=self.char2)
        self.call(CmdPips(), "brawn=lots", "Give a number", caller=self.char2)
        self.call(CmdPips(), "/clear", "Cleared edge from 2 stat(s).", caller=self.char2)
        self.call(CmdPips(), "", "Char2", caller=self.char2)

    def test_locks_gate_pips_and_are_self_service(self):
        self.make_sheet(self.char2, brawn="Mid")
        locks.note_ic_action(self.char2)
        self.call(CmdPips(), "brawn=1", "Your edge and loadout are locked", caller=self.char2)
        self.call(CmdUnlock(), "", "You unlock your edge and loadout.", caller=self.char2)
        self.call(CmdUnlock(), "", "Your edge and loadout aren't locked.", caller=self.char2)
        self.call(CmdPips(), "brawn=1", "Brawn is now Mid +.", caller=self.char2)
        self.call(CmdLock(), "", "You lock your edge and loadout.", caller=self.char2)
        self.call(CmdLock(), "", "Your edge and loadout are already locked.", caller=self.char2)

    def test_drafts_do_not_lock(self):
        self.call(CmdLock(), "", "Only a finalized sheet locks.", caller=self.char2)


class SheetCommandTests(ChargenCommandTest):
    def test_own_sheet_shows_pips_never_scores(self):
        self.make_sheet(self.char2, brawn="High+-")
        output = self.call(CmdSheet(), "", "Char2", caller=self.char2)
        self.assertIn("High + -", output)
        self.assertIn("unlocked", output)
        for score in ("21", "19.5"):
            self.assertNotIn(score, output)

    def test_draft_sheet_shows_what_is_left(self):
        services.ensure_build(self.char2)
        output = self.call(CmdSheet(), "", "Char2", caller=self.char2)
        self.assertIn("To do: Set Brawn, Brains, Charm.", output)

    def test_others_sheets_are_staff_only(self):
        self.make_sheet(self.char1)
        self.call(CmdSheet(), "Char", "You can only see your own sheet.", caller=self.char2)
        self.make_sheet(self.char2)
        self.call(CmdSheet(), "Char2", "Char2", caller=self.char1)


class StaffCommandTests(ChargenCommandTest):
    def test_non_staff_refused(self):
        self.call(CmdChargen(), "", "You need staff permission", caller=self.char2)

    def test_list_view_approve_reopen(self):
        self.make_sheet(self.char2, finalize=False)
        self.call(CmdChargen(), "", "Character sheets", caller=self.char1)
        self.call(CmdChargen(), "/list approved", "No sheets match.", caller=self.char1)
        self.call(CmdChargen(), "/list bogus", "List which?", caller=self.char1)
        self.call(CmdChargen(), "Char2", "Char2", caller=self.char1)
        services.finalize(self.char2)
        self.call(
            CmdChargen(), "/approve Char2=Fine", "Char2's sheet is now approved.", caller=self.char1
        )
        self.call(CmdChargen(), "/reopen Char2", "Char2's sheet is now draft.", caller=self.char1)
        self.call(
            CmdChargen(), "/reopen Char2", "Char2's sheet is already a draft.", caller=self.char1
        )
        self.assertEqual(services.get_build(self.char2).status, CharacterBuild.Status.DRAFT)

    def test_setstat(self):
        self.make_sheet(self.char2)
        self.call(
            CmdChargen(),
            "/setstat Char2/brawn=High++",
            "Char2's Brawn is now High ++.",
            caller=self.char1,
        )
        self.assertEqual(StatHandler(self.char2).get("brawn").display(), "High ++")
        self.call(CmdChargen(), "/setstat Char2=High", "Usage:", caller=self.char1)

    @override_settings(RP_CHARGEN_REQUIRE_APPROVAL=True)
    def test_finalize_with_approval_required(self):
        self.make_sheet(self.char2, finalize=False)
        self.call(
            CmdStats(),
            "/finalize",
            "Sheet finalized and sent to staff for approval.",
            caller=self.char2,
        )
        output = self.call(CmdChargen(), "", "Character sheets", caller=self.char1)
        self.assertIn("Finalized", output)

    def test_cmdset_has_every_command(self):
        cmdset = ChargenCmdSet()
        cmdset.at_cmdset_creation()
        keys = {cmd.key for cmd in cmdset.commands}
        self.assertEqual(keys, {"+sheet", "+stats", "+pips", "+lock", "+unlock", "+chargen"})


class SystemCheckTests(ChargenCommandTest):
    def ids(self):
        return [m.id for m in checks.run_checks() if m.id.startswith("evennia_rp_chargen")]

    def test_clean_by_default(self):
        self.assertEqual(self.ids(), [])

    @override_settings(
        RP_CHARGEN_ALLOCATION={
            "path": "evennia_rp_chargen.allocation.ArrayAllocation",
            "params": {"array": ["high"]},
        }
    )
    def test_allocation_that_does_not_fit(self):
        self.assertEqual(self.ids(), ["evennia_rp_chargen.E001"])

    @override_settings(RP_CHARGEN_PIP_BUDGET=-1, RP_CHARGEN_WEAKNESS_CAP="lots")
    def test_bad_pip_settings(self):
        self.assertEqual(self.ids(), ["evennia_rp_chargen.E002"] * 2)
