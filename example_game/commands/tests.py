"""Sandbox integration tests for the game's CharacterCmdSet wiring.

Verifies that a Character's merged cmdset resolves the pose/social command
names to the classes shipped by evennia_posing / evennia_social - including
that evennia_posing's CmdPose replaces Evennia's stock pose/emote command
(the Phase-2 stopgap module commands/pose_seam.py is gone). Command behavior
itself is covered by the contribs' own suites; this only checks resolution
by key/alias, mirroring how Evennia's cmdparser matches names (prefixes like
@ and + are stripped per CMD_IGNORE_PREFIXES).
"""

import importlib

from evennia.commands.command import CMD_IGNORE_PREFIXES
from evennia.utils.test_resources import EvenniaTest
from typeclasses.characters import Character

from evennia_posing.commands import CmdLastPose, CmdPose, CmdPot
from evennia_social.commands import (
    CmdFinger,
    CmdHangouts,
    CmdIgnore,
    CmdPage,
    CmdTel,
    CmdWhere,
)


def _resolve(cmdset, name):
    """Return the command instance in `cmdset` matching `name` by key or
    alias (with Evennia's prefix-stripping semantics), or None."""
    wanted = name.lower().lstrip(CMD_IGNORE_PREFIXES)
    for cmd in cmdset.commands:
        names = {cmd.key, *cmd.aliases}
        stripped = {n.lower().lstrip(CMD_IGNORE_PREFIXES) for n in names}
        if wanted in stripped:
            return cmd
    return None


class TestCharacterCmdSet(EvenniaTest):
    """Contract (b): contrib commands win by key/alias in the merged cmdset."""

    character_typeclass = Character

    def setUp(self):
        super().setUp()
        self.char1.cmdset.update()
        self.cmdset = self.char1.cmdset.current

    def test_pose_and_emote_resolve_to_contrib_cmdpose(self):
        for name in ("pose", "emote"):
            cmd = _resolve(self.cmdset, name)
            self.assertIsNotNone(cmd, f"no command resolved for {name!r}")
            self.assertIs(type(cmd), CmdPose)

    def test_tel_resolves_to_contrib_cmdtel(self):
        for name in ("@tel", "tel"):
            cmd = _resolve(self.cmdset, name)
            self.assertIsNotNone(cmd, f"no command resolved for {name!r}")
            self.assertIs(type(cmd), CmdTel)

    def test_social_and_posing_commands_resolve(self):
        expected = {
            "+pot": CmdPot,
            "+lastpose": CmdLastPose,
            "+finger": CmdFinger,
            "+where": CmdWhere,
            "+hangouts": CmdHangouts,
            "page": CmdPage,
            "+ignore": CmdIgnore,
        }
        for name, cmdclass in expected.items():
            cmd = _resolve(self.cmdset, name)
            self.assertIsNotNone(cmd, f"no command resolved for {name!r}")
            self.assertIs(type(cmd), cmdclass)

    def test_pose_seam_module_removed(self):
        with self.assertRaises(ImportError):
            importlib.import_module("commands.pose_seam")
