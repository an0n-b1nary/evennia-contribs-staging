# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Staff Building commands with actual host composition and optional partners."""

from django.test import override_settings
from evennia_building import test_staff_commands as staff_tests
from evennia_building.commands import CmdBuildAdmin
from typeclasses.characters import Character
from typeclasses.exits import Exit
from typeclasses.rooms import Room


@override_settings(ROOT_URLCONF="web.urls")
class BuildingStaffCommandSeams(staff_tests.StaffCommandTests):
    character_typeclass = Character
    room_typeclass = Room
    exit_typeclass = Exit

    def test_staff_companion_is_registered_with_current_lock(self):
        from commands.default_cmdsets import CharacterCmdSet

        cmdset = CharacterCmdSet(self.char1)
        self.assertIsInstance(cmdset.get("+buildadmin"), CmdBuildAdmin)
        self.char2.permissions.clear()
        self.char2.account.permissions.clear()
        self.assertFalse(cmdset.get("+buildadmin").access(self.char2, "cmd"))
