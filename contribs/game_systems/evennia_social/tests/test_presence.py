# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Presence: +unfindable (unlisted), legacy stored data, and the surfaces that honour them.

EvenniaTest defaults: char1 is Developer (staff), char2 is not. Both start
in room1.
"""

import re
from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings
from evennia.utils.ansi import strip_ansi

from evennia_social import presence
from evennia_social.commands import CmdHangouts, CmdUnfindable, CmdWhere, CmdWho
from evennia_social.tests.base import SocialCommandTestCase, SocialTestCase

_CONNECTED = "evennia_social.commands.discovery.get_connected_characters"
_IDENTITY_MODES = ("account", "character")
_RETIRED_INPUT_BASELINES = ((presence.UNFINDABLE, "canonical"), ("dark", "legacy"))


class TestPresenceRules(SocialTestCase):
    def test_default_is_findable(self):
        self.assertEqual(presence.visibility(self.char2), presence.FINDABLE)
        self.assertTrue(presence.is_findable(self.char2))
        self.assertTrue(presence.is_listed(self.char2))

    def test_unfindable_is_unlisted(self):
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        self.assertFalse(presence.is_publicly_findable(self.char2))
        self.assertFalse(presence.is_publicly_listed(self.char2))
        self.assertTrue(presence.is_listed(self.char2, self.char1))  # staff viewer
        self.assertFalse(presence.is_listed(self.char2))  # no viewer to see through

    def test_findable_again_clears_the_attribute(self):
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        presence.set_visibility(self.char2, presence.FINDABLE)
        self.assertFalse(self.char2.attributes.has(presence.ATTRIBUTE))

    def test_legacy_stored_dark_is_unfindable_for_all_roles(self):
        for mode in _IDENTITY_MODES:
            with override_settings(EVENNIA_COMMS_IDENTITY=mode), self.subTest(mode=mode):
                for character in (self.char1, self.char2):
                    with self.subTest(character=character.key):
                        character.attributes.add(presence.ATTRIBUTE, "dark")
                        with self.subTest(behavior="visibility"):
                            self.assertEqual(presence.visibility(character), presence.UNFINDABLE)
                        with self.subTest(behavior="marker"):
                            self.assertEqual(presence.staff_marker(character), " (unfindable)")
                        with self.subTest(behavior="raw-value"):
                            self.assertEqual(character.attributes.get(presence.ATTRIBUTE), "dark")

    def test_service_rejects_dark_without_mutating_existing_visibility(self):
        for mode in _IDENTITY_MODES:
            with override_settings(EVENNIA_COMMS_IDENTITY=mode), self.subTest(mode=mode):
                for character in (self.char1, self.char2):
                    with self.subTest(character=character.key):
                        presence.set_visibility(character, presence.UNFINDABLE)
                        before = character.attributes.get(presence.ATTRIBUTE)
                        with self.assertRaises(ValueError):
                            presence.set_visibility(character, "dark")
                        self.assertEqual(character.attributes.get(presence.ATTRIBUTE), before)

    def test_same_room_and_staff_see_through(self):
        presence.set_visibility(self.char1, presence.UNFINDABLE)
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
        self.char1.key = "HiddenStaff"
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

    def test_staff_see_supported_and_legacy_unfindable_characters_marked(self):
        cases = ((presence.UNFINDABLE, "canonical"), ("dark", "legacy"))
        self.assertTrue(cases)
        for mode in _IDENTITY_MODES:
            with override_settings(EVENNIA_COMMS_IDENTITY=mode), self.subTest(mode=mode):
                for value, source in cases:
                    with self.subTest(source=source):
                        if source == "legacy":
                            self.char1.attributes.add(presence.ATTRIBUTE, value)
                        else:
                            presence.set_visibility(self.char1, value)
                        with patch(_CONNECTED, return_value=[self.char1, self.char2]):
                            shown = CmdWhere._format(self.char1)
                        self.assertIn(f"{self.char1.key} (unfindable)", shown)
                        self.assertNotIn("(dark)", shown)
                        self.char2.location = self.room1
                        self.room2.hangout_type = "bar"
                        with patch(_CONNECTED, return_value=[self.char1, self.char2]):
                            remote = CmdWhere._format(self.char2)
                            counts = CmdWhere._format_count(self.char2)
                            venues = CmdHangouts._format(self.char2)
                        self.assertNotIn(self.char1.key, remote)
                        self.assertNotIn(self.room2.key, counts)
                        self.assertNotIn(self.room2.key, venues)
                        self.char2.location = self.room2
                        with patch(_CONNECTED, return_value=[self.char1, self.char2]):
                            same_room = CmdWhere._format(self.char2)
                        self.assertIn(self.char1.key, same_room)
                        self.char2.location = self.room1

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

    def test_dark_input_is_rejected_without_mutating_stored_visibility(self):
        for mode in _IDENTITY_MODES:
            with override_settings(EVENNIA_COMMS_IDENTITY=mode), self.subTest(mode=mode):
                for caller in (self.char1, self.char2):
                    with self.subTest(caller=caller.key):
                        for initial, source in _RETIRED_INPUT_BASELINES:
                            with self.subTest(source=source):
                                if source == "legacy":
                                    caller.attributes.add(presence.ATTRIBUTE, initial)
                                else:
                                    presence.set_visibility(caller, initial)
                                before = caller.attributes.get(presence.ATTRIBUTE)
                                output = self.call(CmdUnfindable(), "dark", caller=caller)
                                with self.subTest(behavior="output"):
                                    self.assertEqual(output, "Usage: +unfindable [on|off]")
                                with self.subTest(behavior="stored-value"):
                                    self.assertEqual(
                                        caller.attributes.get(presence.ATTRIBUTE), before
                                    )

    def test_legacy_dark_status_uses_unfindable_explanation(self):
        for mode in _IDENTITY_MODES:
            with override_settings(EVENNIA_COMMS_IDENTITY=mode), self.subTest(mode=mode):
                self.char1.attributes.add(presence.ATTRIBUTE, "dark")
                self.call(
                    CmdUnfindable(),
                    "",
                    "You are unfindable: left out of who, +where, venue counts and the map. "
                    "Anyone in the same room still sees you, and staff see you marked (unfindable).",
                    caller=self.char1,
                    use_assertequal=True,
                )
                self.assertEqual(self.char1.attributes.get(presence.ATTRIBUTE), "dark")

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

    def test_legacy_staff_left_out_for_players(self):
        self.char1.attributes.add(presence.ATTRIBUTE, "dark")
        self.char2.location = self.room2
        shown = self._who(self.char2)
        self.assertNotRegex(shown, rf"\b{re.escape(self.account.key)}\b")
        self.assertIn("One unique account logged in", shown)

    def test_unfindable_left_out_for_players(self):
        presence.set_visibility(self.char1, presence.UNFINDABLE)
        self.char2.location = self.room2
        self.assertNotRegex(self._who(self.char2), rf"\b{re.escape(self.account.key)}\b")

    def test_same_room_reveals_unfindable(self):
        presence.set_visibility(self.char1, presence.UNFINDABLE)
        shown = self._who(self.char2)  # both in room1
        self.assertRegex(shown, rf"\b{re.escape(self.account.key)}\b")

    def test_same_room_reveals_legacy_staff(self):
        self.char1.attributes.add(presence.ATTRIBUTE, "dark")
        shown = self._who(self.char2)  # both in room1
        self.assertRegex(shown, rf"\b{re.escape(self.account.key)}\b")
