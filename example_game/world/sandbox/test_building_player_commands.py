# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Player Building commands under the reference game's actual MRO and cmdset."""

from django.test import override_settings
from evennia_building import test_player_commands as player_tests
from evennia_building.commands import (
    CmdBuild,
    CmdCollab,
    CmdConsent,
    CmdFrontier,
    CmdPassage,
    CmdProperty,
)
from typeclasses.characters import Character
from typeclasses.exits import Exit
from typeclasses.rooms import Room


@override_settings(ROOT_URLCONF="web.urls")
class BuildingPlayerCommandSeams(player_tests.PlayerCommandTests):
    """The same journeys must work with every installed partner and host mixin."""

    character_typeclass = Character
    room_typeclass = Room
    exit_typeclass = Exit

    def test_all_player_companions_are_registered(self):
        from commands.default_cmdsets import CharacterCmdSet

        cmdset = CharacterCmdSet(self.char2)
        for cls in (CmdBuild, CmdCollab, CmdProperty, CmdConsent, CmdPassage, CmdFrontier):
            self.assertIsInstance(cmdset.get(cls.key), cls)

    def test_direction_aliases_and_renamed_destination_are_real_exit_triggers(self):
        self.command(CmdBuild, "/dig north=Kitchen")
        kitchen = self.project.rooms.get(room__db_key="Kitchen")
        exit = self.project.doors.get(target=kitchen).exit
        kitchen.room.key = "Cookhouse"
        exit.at_cmdset_get(force_init=True)
        exit_cmdset = next(cmdset for cmdset in exit.cmdset.get() if cmdset.key == "ExitCmdSet")
        command = exit_cmdset.get("cookhouse")
        self.assertIsNotNone(command)
        self.assertIn("n", command.aliases)
        self.assertIn("north", command.aliases)
