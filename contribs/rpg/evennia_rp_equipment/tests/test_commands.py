# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""+gear, +wear, +remove and +worn, the default drop/give commands, and the audit.

char1 is a Developer (staff); char2 is an ordinary player.
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from evennia.commands.default.general import CmdDrop, CmdGive

from evennia_rp_equipment import services
from evennia_rp_equipment.audit import log_problems, problems
from evennia_rp_equipment.commands import CmdGear, CmdRemove, CmdWear, CmdWorn
from evennia_rp_equipment.requirements import PIPS, Requirement

from .base import GearCommandTest


class GearCommandTests(GearCommandTest):
    def test_info_includes_optional_verified_provenance_without_crafting_installed(self):
        from evennia_rp_equipment.commands import render_info

        item = self.make_item(self.char2, "cloak")
        with patch.object(
            type(item),
            "get_display_provenance",
            return_value="Made by Morgan (Weaver)",
            create=True,
        ):
            self.assertIn("Craft hallmark: Made by Morgan (Weaver)", render_info(item, self.char1))

    def test_make_describe_require_and_inspect(self):
        self.call(CmdGear(), "/make Cursed Axe=weapon", "You make Cursed Axe.", caller=self.char2)
        self.call(
            CmdGear(),
            "/desc axe=Black iron, cold to the touch.",
            "Described Cursed Axe.",
            caller=self.char2,
        )
        self.call(
            CmdGear(),
            "/line axe=a cursed axe of black iron",
            "Set Cursed Axe's worn line.",
            caller=self.char2,
        )
        self.call(
            CmdGear(),
            "/require axe=Brawn +2",
            "Cursed Axe now requires Brawn ++.",
            caller=self.char2,
        )
        self.call(CmdGear(), "/require axe=Brawn", "Give a requirement like", caller=self.char2)
        self.call(
            CmdGear(),
            "/info axe",
            "Cursed Axe (weapon)\nMade by Char2.\nBlack iron, cold to the touch.\n"
            "Worn line: a cursed axe of black iron\nRequires:\n  1. Brawn ++: not met",
            caller=self.char2,
        )
        self.call(CmdGear(), "", "Your equipment\n  Cursed Axe [weapon]", caller=self.char2)
        self.call(
            CmdGear(),
            "/unrequire axe=1",
            "Cursed Axe no longer requires Brawn ++.",
            caller=self.char2,
        )
        self.call(CmdGear(), "/unrequire axe=x", "Give the requirement's number", caller=self.char2)

    def test_wear_worn_and_remove(self):
        services.make(self.char2, "cloak", slot="body")
        services.set_worn_line(self.char2, self.char2.search("cloak"), "a cloak of deep indigo")
        self.call(CmdWear(), "cloak", "You put on cloak.", caller=self.char2)
        self.call(
            CmdWorn(), "", "You are wearing:\n  a cloak of deep indigo (cloak)", caller=self.char2
        )
        self.call(
            CmdWorn(), "Char2", "Char2 is wearing:\n  a cloak of deep indigo", caller=self.char1
        )
        self.call(CmdGear(), "", "Your equipment\n  cloak [body] (worn)", caller=self.char2)
        self.call(CmdRemove(), "cloak", "You take off cloak.", caller=self.char2)
        self.call(CmdWorn(), "", "You aren't wearing anything.", caller=self.char2)

    def test_wear_shows_refusals_and_attunement(self):
        self.make_sheet(self.char2)
        self.make_item(self.char2, "axe", "Brawn +1")
        self.call(CmdWear(), "axe", "Wearing axe needs Brawn +.", caller=self.char2)
        self.make_item(self.char2, "staff", "ability Domain Expertise: Riddles")
        self.call(
            CmdWear(),
            "staff",
            "You put on staff.|You aren't fully attuned to staff",
            caller=self.char2,
        )

    def test_default_drop_and_give_refuse_worn_items(self):
        item = self.make_item(self.char2, "cloak")
        services.wear(self.char2, item)
        self.call(CmdDrop(), "cloak", "Remove cloak first.", caller=self.char2)
        self.call(CmdGive(), "cloak = Char", "Remove cloak first.", caller=self.char2)
        self.assertEqual(item.location, self.char2)

    def test_destroy(self):
        self.make_item(self.char2, "rag")
        self.call(CmdGear(), "/destroy rag", "You destroy rag.", caller=self.char2)
        self.assertEqual(services.made_count(self.char2), 0)


class AuditTests(GearCommandTest):
    def test_audit_lists_broken_requirements_for_staff_only(self):
        self.make_sheet(self.char2, brawn="Mid+")
        axe = self.make_item(self.char2, "axe", "Brawn +1")
        services.wear(self.char2, axe)
        self.assertEqual(problems(), [])
        self.call(CmdGear(), "/audit", "No worn gear has a broken requirement.", caller=self.char1)

        # A ruleset edit renames the stat out from under the worn axe.
        axe.requirement_data = [Requirement(PIPS, stat="luck", count=1).to_dict()]
        found = problems()
        self.assertEqual(len(found), 1)
        self.assertIn("which this game no longer has", found[0])
        self.call(CmdGear(), "/audit", "Worn gear needing attention", caller=self.char1)
        self.call(CmdGear(), "/audit", "Only staff can audit", caller=self.char2)

        with self.assertLogs("evennia", "WARNING"):
            self.assertEqual(len(log_problems()), 1)
        out = StringIO()
        call_command("rp_equipment_audit", stdout=out)
        self.assertIn("1 problem(s).", out.getvalue())
