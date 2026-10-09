# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Presence: +unfindable, staff dark, and the surfaces that honour them.

EvenniaTest defaults: char1 is Developer (staff), char2 is not. Both start
in room1.
"""

import re
from types import SimpleNamespace
from unittest.mock import patch

from evennia.utils.ansi import strip_ansi

from evennia_social import presence
from evennia_social.commands import CmdHangouts, CmdUnfindable, CmdWhere, CmdWho
from evennia_social.tests.base import SocialCommandTestCase, SocialTestCase

_CONNECTED = "evennia_social.commands.discovery.get_connected_characters"


class TestPresenceRules(SocialTestCase):
    def test_default_is_findable(self):
        self.assertEqual(presence.visibility(self.char2), presence.FINDABLE)
        self.assertTrue(presence.is_findable(self.char2))
        self.assertTrue(presence.is_listed(self.char2))

    def test_unfindable_hides_location_but_not_online_status(self):
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        self.assertFalse(presence.is_publicly_findable(self.char2))
        self.assertTrue(presence.is_publicly_listed(self.char2))

    def test_findable_again_clears_the_attribute(self):
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        presence.set_visibility(self.char2, presence.FINDABLE)
        self.assertFalse(self.char2.attributes.has(presence.ATTRIBUTE))

    def test_only_staff_can_go_dark(self):
        with self.assertRaises(ValueError):
            presence.set_visibility(self.char2, presence.DARK)
        presence.set_visibility(self.char1, presence.DARK)
        self.assertFalse(presence.is_publicly_listed(self.char1))

    def test_stored_dark_on_a_non_staff_character_reads_as_unfindable(self):
        # Lost staff permissions must not keep a player hidden from who.
        self.char2.attributes.add(presence.ATTRIBUTE, presence.DARK)
        self.assertEqual(presence.visibility(self.char2), presence.UNFINDABLE)

    def test_same_room_and_staff_see_through(self):
        presence.set_visibility(self.char1, presence.DARK)
        self.assertTrue(presence.is_findable(self.char1, self.char2))  # same room
        self.assertTrue(presence.is_listed(self.char1, self.char2))
        self.char2.location = self.room2
        self.assertFalse(presence.is_findable(self.char1, self.char2))
        self.assertFalse(presence.is_listed(self.char1, self.char2))
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        self.assertTrue(presence.is_findable(self.char2, self.char1))  # staff viewer

    def test_staff_marker(self):
        self.assertEqual(presence.staff_marker(self.char2), "")
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        self.assertEqual(presence.staff_marker(self.char2), " (unfindable)")


class TestDiscoveryHonoursPresence(SocialTestCase):
    def setUp(self):
        super().setUp()
        self.char1.location = self.room2  # staff, elsewhere
        presence.set_visibility(self.char1, presence.UNFINDABLE)

    def test_where_leaves_out_an_unfindable_character_elsewhere(self):
        with patch(_CONNECTED, return_value=[self.char1, self.char2]):
            shown = CmdWhere._format(self.char2)
        self.assertNotIn(self.room2.key, shown)
        self.assertIn("1 character online", shown)

    def test_where_shows_them_to_someone_in_the_same_room(self):
        self.char2.location = self.room2
        with patch(_CONNECTED, return_value=[self.char1, self.char2]):
            shown = CmdWhere._format(self.char2)
        self.assertIn(self.char1.key, shown)

    def test_staff_see_unfindable_characters_marked(self):
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        with patch(_CONNECTED, return_value=[self.char1, self.char2]):
            shown = CmdWhere._format(self.char1)
        self.assertIn(f"{self.char2.key} (unfindable)", shown)

    def test_where_count_and_hangouts_leave_them_out(self):
        self.room2.hangout_type = "bar"
        with patch(_CONNECTED, return_value=[self.char1, self.char2]):
            counts = CmdWhere._format_count(self.char2)
            venues = CmdHangouts._format(self.char2)
        self.assertNotIn(self.room2.key, counts)
        self.assertNotIn(self.room2.key, venues)


class TestCmdUnfindable(SocialCommandTestCase):
    def test_status_on_off(self):
        self.call(CmdUnfindable(), "", "You are findable", caller=self.char2)
        self.call(CmdUnfindable(), "on", "You are unfindable", caller=self.char2)
        self.assertEqual(presence.visibility(self.char2), presence.UNFINDABLE)
        self.call(CmdUnfindable(), "off", "You are findable", caller=self.char2)
        self.assertEqual(presence.visibility(self.char2), presence.FINDABLE)

    def test_players_cannot_go_dark(self):
        self.call(CmdUnfindable(), "dark", "Only staff can go dark", caller=self.char2)
        self.assertEqual(presence.visibility(self.char2), presence.FINDABLE)

    def test_staff_can_go_dark(self):
        self.call(CmdUnfindable(), "dark", "You are dark", caller=self.char1)
        self.assertEqual(presence.visibility(self.char1), presence.DARK)

    def test_bad_argument(self):
        self.call(CmdUnfindable(), "maybe", "Usage: +unfindable", caller=self.char2)


class TestCmdWho(SocialTestCase):
    """who for an unprivileged account, against stand-in sessions."""

    def _session(self, account, puppet):
        return SimpleNamespace(
            logged_in=True,
            account=account,
            get_account=lambda: account,
            get_puppet=lambda: puppet,
            conn_time=0,
            cmd_last_visible=0,
            protocol_flags={},
        )

    def _who(self, viewer_puppet):
        output = []
        cmd = CmdWho()
        cmd.caller = cmd.account = self.account2
        cmd.session = self._session(self.account2, viewer_puppet)
        cmd.cmdstring = "who"
        cmd.msg = lambda text=None, **kwargs: output.append(text)
        sessions = [self._session(self.account, self.char1), cmd.session]
        with patch("evennia.SESSION_HANDLER.get_sessions", return_value=sessions):
            cmd.func()
        # ANSI codes end in a letter, which would defeat the \b in the
        # account-name assertions below.
        return strip_ansi(str(output[0]))

    def test_dark_staff_left_out_for_players(self):
        presence.set_visibility(self.char1, presence.DARK)
        self.char2.location = self.room2
        shown = self._who(self.char2)
        self.assertNotRegex(shown, rf"\b{re.escape(self.account.key)}\b")
        self.assertIn("One unique account logged in", shown)

    def test_unfindable_still_listed(self):
        presence.set_visibility(self.char1, presence.UNFINDABLE)
        self.char2.location = self.room2
        self.assertRegex(self._who(self.char2), rf"\b{re.escape(self.account.key)}\b")

    def test_same_room_reveals_dark_staff(self):
        presence.set_visibility(self.char1, presence.DARK)
        shown = self._who(self.char2)  # both in room1
        self.assertRegex(shown, rf"\b{re.escape(self.account.key)}\b")
