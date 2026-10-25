# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""RP_EQUIPMENT_REVEALED: hidden from players, kept by staff, and changeable at runtime.

char1 is a Developer (staff); char2 is an ordinary player.
"""

from __future__ import annotations

from django.test import override_settings

from evennia_links import runtime
from evennia_rp_equipment import services
from evennia_rp_equipment.commands import EquipmentCmdSet

from .base import GearCommandTest


class RevealTests(GearCommandTest):
    def commands(self):
        return EquipmentCmdSet().commands

    def test_revealed_by_default(self):
        self.assertIn("RP_EQUIPMENT_REVEALED", runtime.registered())
        for command in self.commands():
            with self.subTest(command.key):
                self.assertTrue(command.access(self.char2))
                command.caller = self.char2
                command.args = ""
                self.assertFalse(command.at_pre_cmd())

    @override_settings(RP_EQUIPMENT_REVEALED=False)
    def test_hidden_from_players_and_kept_by_staff(self):
        for command in self.commands():
            with self.subTest(command.key):
                self.assertFalse(command.access(self.char2))
                self.assertTrue(command.access(self.char1))
                command.caller = self.char2
                command.args = ""
                self.assertTrue(command.at_pre_cmd())
                command.caller = self.char1
                self.assertFalse(command.at_pre_cmd())

    def test_the_runtime_setting_hides_and_restores_without_a_restart(self):
        runtime.set("RP_EQUIPMENT_REVEALED", False)
        try:
            self.assertFalse(self.commands()[0].access(self.char2))
        finally:
            runtime.reset("RP_EQUIPMENT_REVEALED")
        self.assertTrue(self.commands()[0].access(self.char2))

    @override_settings(RP_EQUIPMENT_REVEALED=False)
    def test_hiding_leaves_worn_gear_worn_and_guarded(self):
        """The switch hides commands only: descriptions and the build guard still hold."""
        item = self.make_item(self.char2, "cloak")
        services.set_worn_line(self.char2, item, "a cloak of deep indigo")
        services.wear(self.char2, item)
        self.assertTrue(item.is_worn)
        self.assertIn("a cloak of deep indigo", self.char2.return_appearance(self.char1))
