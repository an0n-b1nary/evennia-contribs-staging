# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Command-level tests for evennia_social.

Covers each command's happy path plus the two generalized-search seams
introduced by this extraction (find_character, find_room — see
MIGRATION_NOTES.md) and the severed evennia_scenes coupling in CmdOoc.
"""

from evennia.utils.create import create_object

from evennia_posing.signals import pose_recorded
from evennia_social.commands.discovery import CmdHangouts, CmdWhere
from evennia_social.commands.filtering import CmdIgnore
from evennia_social.commands.finger import CmdFinger
from evennia_social.commands.messaging import CmdPage
from evennia_social.commands.ooc import CmdOoc
from evennia_social.commands.roomconfig import CmdRoomConfig
from evennia_social.commands.tel import CmdTel
from evennia_social.commands.teleportation import CmdJoin, CmdSummon
from evennia_social.social import find_character
from evennia_social.tests.base import SocialCommandTestCase, SocialTestCase


class TestCmdIgnore(SocialCommandTestCase):
    def setUp(self):
        super().setUp()
        self.account.db.ignore_list = []
        self.account2.db.ignore_list = []

    def test_add_view_remove(self):
        result = self.call(CmdIgnore(), "Char2")
        self.assertIn("Now ignoring", result)
        self.assertIn(self.account2.id, self.account.db.ignore_list)

        result = self.call(CmdIgnore(), "")
        self.assertIn("Ignore List", result)
        self.assertIn("1 player", result)

        result = self.call(CmdIgnore(), "/remove Char2")
        self.assertIn("No longer ignoring", result)
        self.assertNotIn(self.account2.id, self.account.db.ignore_list)

    def test_cannot_ignore_self(self):
        result = self.call(CmdIgnore(), "Char")
        self.assertIn("can't ignore yourself", result)


class TestCmdFinger(SocialCommandTestCase):
    def test_view_own_profile_defaults(self):
        result = self.call(CmdFinger(), "")
        self.assertIn("Char's Profile", result)
        self.assertIn("Unspecified", result)

    def test_set_and_view_field(self):
        self.call(CmdFinger(), "/set gender=Nonbinary", "Gender set to: Nonbinary")
        self.assertEqual(self.char1.profile_gender, "Nonbinary")

    def test_clear_identity_field_resets_to_unspecified(self):
        self.char1.profile_gender = "Nonbinary"
        self.call(CmdFinger(), "/clear gender", "Gender reset to Unspecified.")
        self.assertEqual(self.char1.profile_gender, "Unspecified")

    def test_profile_has_no_lore_or_plot_placeholders(self):
        """MIGRATION_NOTES: lore_lean_*/resource_lean_value/plot_follows
        are dropped from the ported profile display — this contrib's
        Character mixin doesn't even define those attributes.
        """
        self.assertFalse(hasattr(self.char1, "lore_lean_value"))
        self.assertFalse(hasattr(self.char1, "plot_follows"))


class TestCmdPage(SocialCommandTestCase):
    def test_send_and_reply(self):
        result = self.call(CmdPage(), "Char2=hello there")
        self.assertIn("You paged Char2", result)
        self.assertEqual(self.char2.last_pager, self.char1.id)

        result = self.call(CmdPage(), "hi back", caller=self.char2)
        self.assertIn("You paged Char", result)


class TestCmdSummonJoin(SocialCommandTestCase):
    def test_summon_request_and_accept(self):
        # char1/char2 both start in room1 by default; move char2 elsewhere
        # so the summon has somewhere to summon *from*.
        self.char2.location = self.room2
        result = self.call(CmdSummon(), "Char2")
        self.assertIn("You sent a summon request", result)
        self.assertIn(self.char1.id, self.char2.pending_summon_requests)

        result = self.call(CmdSummon(), "/accept Char", caller=self.char2)
        self.assertIn("summoned to", result)
        self.assertEqual(self.char2.location, self.char1.location)

    def test_join_request_and_accept(self):
        from evennia.utils import create

        room2 = create.create_object("evennia.objects.objects.DefaultRoom", key="Room2")
        self.char2.location = room2

        result = self.call(CmdJoin(), "Char2")
        self.assertIn("You sent a join request", result)

        result = self.call(CmdJoin(), "/accept Char", caller=self.char2)
        self.assertIn("accepted", result)
        self.assertEqual(self.char1.location, room2)
        room2.delete()


class TestCmdWhere(SocialCommandTestCase):
    def test_basic_listing(self):
        self.char1.at_post_puppet()
        self.char2.at_post_puppet()
        result = self.call(CmdWhere(), "")
        self.assertIn("Who's Where", result)
        self.assertIn("Char", result)


class TestCmdRoomConfig(SocialCommandTestCase):
    """+roomconfig — the in-game way to populate the +hangouts directory."""

    def setUp(self):
        super().setUp()
        self.account.permissions.add("Builder")

    def test_show_config_defaults(self):
        # .call() renders color codes out, so assert against display text.
        result = self.call(CmdRoomConfig(), "")
        self.assertIn("Room Configuration", result)
        self.assertIn("Hangout: None", result)

    def test_set_hangout_then_shows_in_hangouts_directory(self):
        """The round trip that matters: designating a hangout must make the
        room actually appear in +hangouts.
        """
        self.call(CmdRoomConfig(), "/hangout bar", "Hangout type set to")
        self.assertEqual(self.room1.hangout_type, "bar")

        self.char1.at_post_puppet()
        result = self.call(CmdHangouts(), "")
        self.assertIn(self.room1.key, result)
        self.assertIn("Bar", result)

    def test_invalid_hangout_type_rejected(self):
        result = self.call(CmdRoomConfig(), "/hangout casino")
        self.assertIn("Invalid hangout type", result)
        self.assertIsNone(self.room1.hangout_type)

    def test_clear_hangout(self):
        self.room1.hangout_type = "bar"
        self.call(CmdRoomConfig(), "/hangout/clear", "Removed Bar hangout designation")
        self.assertIsNone(self.room1.hangout_type)

    def test_cleared_hangout_not_listed_as_empty_hangout(self):
        """Clearing sets hangout_type = None, which still leaves an
        Attribute row behind — so +hangouts/all's get_by_attribute() lookup
        finds the room and must skip it on the falsy value rather than
        listing a non-hangout as an empty hangout.
        """
        self.room1.hangout_type = "bar"
        self.call(CmdRoomConfig(), "/hangout/clear")
        result = self.call(CmdHangouts(), "/all")
        self.assertIn("No hangouts found", result)

    def test_non_owner_non_staff_denied(self):
        self.account.permissions.remove("Builder")
        self.account2.permissions.remove("Builder")
        result = self.call(CmdRoomConfig(), "/hangout bar", caller=self.char2)
        self.assertIn("don't have permission", result)


class TestCmdOoc(SocialCommandTestCase):
    def test_ooc_does_not_touch_pose_tracking(self):
        """MIGRATION_NOTES: CmdOoc fires pose_recorded but must NOT call
        record_pose(), so pose order / last_pose_time are untouched.
        """
        self.char1.last_pose_time = None
        self.call(CmdOoc(), "checking scene logistics")
        self.assertIsNone(self.char1.last_pose_time)

    def test_ooc_fires_pose_recorded_signal(self):
        received = []

        def _listener(sender, character, pose_text, pose_type, location, **kwargs):
            received.append((character, pose_text, pose_type))

        pose_recorded.connect(_listener)
        try:
            self.call(CmdOoc(), "let's regroup ic")
        finally:
            pose_recorded.disconnect(_listener)

        self.assertEqual(len(received), 1)
        character, pose_text, pose_type = received[0]
        self.assertEqual(character, self.char1)
        self.assertEqual(pose_type, "ooc")
        self.assertIn("regroup", pose_text)


class TestCmdTel(SocialCommandTestCase):
    def test_staff_teleport_by_exact_name(self):
        self.account.permissions.add("Builder")
        room2 = create_object("evennia.objects.objects.DefaultRoom", key="Meeting Hall")
        result = self.call(CmdTel(), "Meeting Hall")
        self.assertIn("Teleported to", result)
        self.assertEqual(self.char1.location, room2)
        room2.delete()

    def test_staff_teleport_by_fuzzy_typo_suggests_not_autoselects(self):
        """A single fuzzy (non-substring) match is offered as a suggestion
        to confirm, never auto-selected — same as the source project's
        behavior (a typo shouldn't silently teleport you somewhere else).
        """
        self.account.permissions.add("Builder")
        room2 = create_object("evennia.objects.objects.DefaultRoom", key="Meeting Hall")
        result = self.call(CmdTel(), "Meting Hall")  # typo: missing an "e"
        self.assertIn("Multiple matches", result)
        self.assertIn("Meeting Hall", result)
        self.assertEqual(self.char1.location, self.room1)
        room2.delete()


class TestFindCharacter(SocialTestCase):
    """find_character() — the isinstance-based generalization of the
    source's typeclass-string search (see MIGRATION_NOTES.md).
    """

    def test_finds_exact_match(self):
        target, error = find_character("Char2")
        self.assertIsNone(error)
        self.assertEqual(target, self.char2)

    def test_no_match(self):
        target, error = find_character("Nobody")
        self.assertIsNone(target)
        self.assertIn("Could not find", error)

    def test_empty_name(self):
        target, error = find_character("")
        self.assertIsNone(target)
        self.assertIn("must specify", error)
