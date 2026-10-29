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
from django.test import override_settings
from evennia.utils import create

from evennia_social import presence
from evennia_social.integrations.maps import provide
from evennia_social.tests.base import SocialTestCase, SocialTestCharacter

_CONNECTED = "evennia_social.social.get_connected_characters"
_IDENTITY_MODES = ("account", "character")
_HIDDEN_CASES = ((presence.UNFINDABLE, "canonical"), ("dark", "legacy"))


class TestWhosHereOverlay(SocialTestCase):
    def setUp(self):
        super().setUp()
        self.char3 = create.create_object(
            SocialTestCharacter, key="Ashwren", location=self.room2, home=self.room2
        )

    def _provide(self, connected, *, staff=False, room_ids=None, **kwargs):
        if room_ids is None:
            room_ids = [self.room1.pk, self.room2.pk]
        with patch(_CONNECTED, return_value=list(connected)):
            return provide(sender=None, room_ids=room_ids, staff=staff, **kwargs)

    def test_connected_characters_by_room_sorted(self):
        overlay = self._provide([self.char2, self.char1, self.char3])
        self.assertEqual(
            overlay["present"],
            {self.room1.pk: sorted([self.char1.key, self.char2.key]), self.room2.pk: ["Ashwren"]},
        )

    def test_offline_characters_are_not_here(self):
        self.assertEqual(self._provide([self.char3]), {"present": {self.room2.pk: ["Ashwren"]}})

    def test_canonical_and_legacy_unfindable_are_hidden_from_public_overlay(self):
        self.assertTrue(_HIDDEN_CASES)
        for mode in _IDENTITY_MODES:
            with override_settings(EVENNIA_COMMS_IDENTITY=mode), self.subTest(mode=mode):
                for value, source in _HIDDEN_CASES:
                    with self.subTest(source=source):
                        if source == "legacy":
                            self.char1.attributes.add(presence.ATTRIBUTE, value)
                        else:
                            presence.set_visibility(self.char1, value)
                        presence.set_visibility(self.char2, presence.UNFINDABLE)
                        overlay = self._provide([self.char1, self.char2, self.char3])
                        self.assertEqual(overlay, {"present": {self.room2.pk: ["Ashwren"]}})
                        staff_overlay = self._provide([self.char1, self.char2], staff=True)[
                            "present"
                        ][self.room1.pk]
                        self.assertEqual(
                            staff_overlay,
                            sorted(
                                [
                                    f"{self.char1.key} (unfindable)",
                                    f"{self.char2.key} (unfindable)",
                                ]
                            ),
                        )
                        self.assertNotIn("(dark)", " ".join(staff_overlay))

    def test_staff_see_everyone_with_a_marker(self):
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        self.char1.attributes.add(presence.ATTRIBUTE, "dark")
        overlay = self._provide([self.char1, self.char2], staff=True)
        self.assertEqual(
            overlay["present"][self.room1.pk],
            sorted([f"{self.char1.key} (unfindable)", f"{self.char2.key} (unfindable)"]),
        )

    def test_only_the_requested_rooms(self):
        overlay = self._provide([self.char2, self.char3], room_ids=[self.room2.pk])
        self.assertEqual(overlay, {"present": {self.room2.pk: ["Ashwren"]}})
        self.assertEqual(self._provide([self.char2], room_ids=[]), {})

    def test_several_sessions_count_once(self):
        overlay = self._provide([self.char3, self.char3])
        self.assertEqual(overlay["present"][self.room2.pk], ["Ashwren"])

    def _connected(self, character):
        """Pretend *character* has a live session, as a player in-game would."""
        return patch.object(character.sessions, "count", return_value=1)

    def test_connected_viewer_in_same_room_sees_canonical_and_legacy_unfindable(self):
        """Unfindable hides you from afar, not from someone standing there."""
        for mode in _IDENTITY_MODES:
            with override_settings(EVENNIA_COMMS_IDENTITY=mode), self.subTest(mode=mode):
                for value, source in _HIDDEN_CASES:
                    with self.subTest(source=source):
                        if source == "legacy":
                            self.char2.attributes.add(presence.ATTRIBUTE, value)
                        else:
                            presence.set_visibility(self.char2, value)
                        self.char2.location = self.room1
                        self.char3.location = self.room1
                        with self._connected(self.char3):
                            overlay = self._provide([self.char2, self.char3], viewer=self.char3)
                        self.assertEqual(
                            overlay["present"][self.room1.pk],
                            sorted([self.char2.key, self.char3.key]),
                        )

    def test_a_viewer_elsewhere_does_not(self):
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        self.char1.attributes.add(presence.ATTRIBUTE, "dark")
        with self._connected(self.char3):
            overlay = self._provide([self.char1, self.char2, self.char3], viewer=self.char3)
        self.assertEqual(overlay, {"present": {self.room2.pk: ["Ashwren"]}})

    def test_an_offline_viewer_left_standing_in_the_room_does_not(self):
        # Evennia moves an offline character out of the world, but a game may
        # leave it in place; browsing the website as it is not being there.
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        self.char3.location = self.room1
        overlay = self._provide([self.char2], viewer=self.char3)
        self.assertEqual(overlay, {})

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
