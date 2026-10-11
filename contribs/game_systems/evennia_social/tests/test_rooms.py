# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Social commands consume the shared room permission seam."""

from unittest.mock import patch

from django.test import override_settings

from evennia_social.commands.roomconfig import _can_configure_room
from evennia_social.mood import can_set_mood
from evennia_social.tests.base import SocialTestCase


@override_settings(LINKS_ROOM_PERMISSION="game.room_rights")
class TestRoomPermissionSeam(SocialTestCase):
    def test_provider_can_grant_configure_without_control(self):
        self.room1.locks.add("control:false()")
        with patch(
            "evennia_links.rooms.resolve_dotted",
            return_value=lambda actor, room, action: actor == self.char2 and action == "configure",
        ):
            self.assertTrue(_can_configure_room(self.char2, self.room1))
            self.assertTrue(can_set_mood(self.char2, self.room1))

    def test_provider_denial_overrides_control_but_preserves_staff(self):
        self.room1.locks.add("control:all()")
        with patch("evennia_links.rooms.resolve_dotted", return_value=lambda *args: False):
            self.assertFalse(_can_configure_room(self.char2, self.room1))
            self.assertFalse(can_set_mood(self.char2, self.room1))
            self.assertTrue(_can_configure_room(self.char1, self.room1))
            self.assertTrue(can_set_mood(self.char1, self.room1))
