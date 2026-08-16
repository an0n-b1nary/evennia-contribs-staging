"""Sandbox integration tests for the game's CharacterCmdSet wiring.

Verifies that a Character's merged cmdset resolves the pose/social command
names to the classes shipped by evennia_posing / evennia_social - including
that evennia_posing's CmdPose replaces Evennia's stock pose/emote command
(the Phase-2 stopgap module commands/pose_seam.py is gone). Command behavior
itself is covered by the contribs' own suites; this only checks resolution
by key/alias, mirroring how Evennia's cmdparser matches names (prefixes like
@ and + are stripped per CMD_IGNORE_PREFIXES).

+sandbox is the exception, and is tested for behavior here rather than only
for resolution, because it is the game's own command and no contrib suite
covers it.
"""

import importlib

from django.conf import settings
from evennia.commands.command import CMD_IGNORE_PREFIXES
from evennia.objects.models import ObjectDB
from evennia.utils.search import search_object
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from evennia_jobs.commands import CmdJobs
from typeclasses.characters import Character
from typeclasses.rooms import Room
from world.sandbox.tests import SeededSandboxMixin

from commands.sandbox import CmdSandbox, _stray_rooms
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

    def test_sandbox_command_resolves(self):
        cmd = _resolve(self.cmdset, "+sandbox")
        self.assertIsNotNone(cmd, "no command resolved for '+sandbox'")
        self.assertIs(type(cmd), CmdSandbox)


def _has_builder(obj):
    return "builder" in [perm.lower() for perm in obj.permissions.all()]


class TestSandboxCommand(SeededSandboxMixin, EvenniaCommandTest):
    """+sandbox: self-promotion, and the reset it deliberately does not grant.

    char2/account2 are the plain-player fixture (EvenniaTest gives permissions
    only to char1/account), so they stand in for a playtester; char1 carries
    Developer and stands in for whoever runs the sandbox.
    """

    character_typeclass = Character
    room_typeclass = Room

    def test_builder_toggle_writes_account_and_puppet(self):
        # Both, because perm() reads the account unquelled and the *minimum* of
        # the pair under quell - see CmdSandbox._permission_targets.
        self.call(CmdSandbox(), "/builder on", caller=self.char2)
        self.assertTrue(_has_builder(self.account2))
        self.assertTrue(_has_builder(self.char2))

        self.call(CmdSandbox(), "/builder off", caller=self.char2)
        self.assertFalse(_has_builder(self.account2))
        self.assertFalse(_has_builder(self.char2))

    def test_builder_toggle_opens_a_class_locked_command(self):
        # +jobs is one of the three commands gated at the class level rather
        # than inside func(), so its access check is the honest end-to-end
        # proof that the toggle reaches the lock system.
        cmd = CmdJobs()
        self.assertFalse(cmd.access(self.char2, "cmd"))

        self.call(CmdSandbox(), "/builder on", caller=self.char2)
        self.assertTrue(cmd.access(self.char2, "cmd"))

        self.call(CmdSandbox(), "/builder off", caller=self.char2)
        self.assertFalse(cmd.access(self.char2, "cmd"))

    def test_builder_without_on_or_off_is_refused(self):
        self.call(CmdSandbox(), "/builder", "Usage:", caller=self.char2)
        self.assertFalse(_has_builder(self.account2))

    def test_status_reports_the_toggle_state(self):
        out = self.call(CmdSandbox(), "", caller=self.char2)
        self.assertIn("Builder mode: off", out)

        self.call(CmdSandbox(), "/builder on", caller=self.char2)
        out = self.call(CmdSandbox(), "", caller=self.char2)
        self.assertIn("Builder mode: ON", out)

    def test_stray_count_excludes_seeded_and_origin_rooms(self):
        strays = {room.id for room in _stray_rooms()}
        # room2 is a fixture room the seeder never made, so a reset leaves it.
        self.assertIn(self.room2.id, strays)
        # The origin room is untagged by design (the seeder re-dresses it
        # rather than creating it), so counting it would put a floor of 1 under
        # a number that must read zero on an untouched sandbox.
        self.assertNotIn(self.room1.id, strays)
        self.assertNotIn(search_object("The Archive")[0].id, strays)

    def test_reset_is_refused_below_admin(self):
        self.call(CmdSandbox(), "/reset", "Only the sandbox's staff", caller=self.char2)

    def test_reset_is_refused_to_a_self_promoted_builder(self):
        # The whole point of holding /reset above Builder: self-promotion is
        # open to everyone here, so a Builder-level gate would be no gate.
        self.call(CmdSandbox(), "/builder on", caller=self.char2)
        self.call(CmdSandbox(), "/reset", "Only the sandbox's staff", caller=self.char2)

    def test_reset_rebuilds_the_world_for_staff(self):
        origin_before = ObjectDB.objects.get_id(settings.START_LOCATION).id
        search_object("The Archive")[0].delete()
        self.assertFalse(search_object("The Archive"))

        # msg=None and assertIn rather than an expected string: the command
        # reports over three separate .msg calls, which self.call joins with
        # "|" and compares with startswith.
        out = self.call(CmdSandbox(), "/reset", caller=self.char1)
        self.assertIn("The seeded world is rebuilt", out)
        self.assertIn("Rooms made by hand, left untouched by the purge: 1", out)

        self.assertTrue(search_object("The Archive"))
        # The reason the spawn settings can stay literal dbrefs: a reset must
        # not move the room they name.
        self.assertEqual(ObjectDB.objects.get_id(settings.START_LOCATION).id, origin_before)
