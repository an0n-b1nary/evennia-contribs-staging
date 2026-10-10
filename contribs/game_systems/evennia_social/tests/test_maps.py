# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
The live map's who's-here overlay (``integrations/maps.py``).

EvenniaTest defaults: char1 is Developer (staff), char2 is not. Both start
in room1.
"""

from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from evennia.utils import create

from evennia_social import presence
from evennia_social.integrations.maps import provide
from evennia_social.tests.base import SocialTestCase, SocialTestCharacter

_CONNECTED = "evennia_social.social.get_connected_characters"


class TestWhosHereOverlay(SocialTestCase):
    def setUp(self):
        super().setUp()
        self.char3 = create.create_object(
            SocialTestCharacter, key="Ashwren", location=self.room2, home=self.room2
        )

    def _provide(self, connected, *, staff=False, room_ids=None):
        if room_ids is None:
            room_ids = [self.room1.pk, self.room2.pk]
        with patch(_CONNECTED, return_value=list(connected)):
            return provide(sender=None, room_ids=room_ids, staff=staff)

    def test_connected_characters_by_room_sorted(self):
        overlay = self._provide([self.char2, self.char1, self.char3])
        self.assertEqual(
            overlay["present"],
            {self.room1.pk: sorted([self.char1.key, self.char2.key]), self.room2.pk: ["Ashwren"]},
        )

    def test_offline_characters_are_not_here(self):
        self.assertEqual(self._provide([self.char3]), {"present": {self.room2.pk: ["Ashwren"]}})

    def test_unfindable_and_dark_are_hidden_from_players(self):
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        presence.set_visibility(self.char1, presence.DARK)
        overlay = self._provide([self.char1, self.char2, self.char3])
        self.assertEqual(overlay, {"present": {self.room2.pk: ["Ashwren"]}})

    def test_staff_see_everyone_with_a_marker(self):
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        presence.set_visibility(self.char1, presence.DARK)
        overlay = self._provide([self.char1, self.char2], staff=True)
        self.assertEqual(
            overlay["present"][self.room1.pk],
            sorted([f"{self.char1.key} (dark)", f"{self.char2.key} (unfindable)"]),
        )

    def test_only_the_requested_rooms(self):
        overlay = self._provide([self.char2, self.char3], room_ids=[self.room2.pk])
        self.assertEqual(overlay, {"present": {self.room2.pk: ["Ashwren"]}})
        self.assertEqual(self._provide([self.char2], room_ids=[]), {})

    def test_several_sessions_count_once(self):
        overlay = self._provide([self.char3, self.char3])
        self.assertEqual(overlay["present"][self.room2.pk], ["Ashwren"])

    def test_nobody_to_show_answers_nothing(self):
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        self.assertEqual(self._provide([self.char2]), {})
        self.char3.location = None
        self.assertEqual(self._provide([self.char3]), {})


@skipUnless(apps.is_installed("evennia_maps"), "evennia_maps is not installed")
class TestWhosHereWiring(SocialTestCase):
    """With evennia_maps installed, ready() connects the provider to the real seam."""

    def test_the_map_collects_who_is_here(self):
        from evennia_maps.overlays import collect_overlays

        with patch(_CONNECTED, return_value=[self.char2]):
            overlays = collect_overlays([self.room1.pk], staff=False)
        self.assertEqual(overlays.get("present"), {self.room1.pk: [self.char2.key]})
