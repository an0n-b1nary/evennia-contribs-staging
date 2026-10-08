# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Tests for room mood: SocialRoomMixin display, +mood, and its permissions.

char1's account is a Developer (staff) in Evennia's test fixtures; char2's is
a plain player, so char2 is the "ordinary player" throughout.
"""

import unittest
from unittest import mock

from django.apps import apps
from django.test import override_settings

from evennia_social.commands import CmdMood
from evennia_social.mood import MOOD_MAX_LENGTH, can_set_mood, clear_mood, set_mood
from evennia_social.tests.base import SocialCommandTestCase, SocialTestCase

HAS_SCENES = apps.is_installed("evennia_scenes")


class TestRoomMoodDisplay(SocialTestCase):
    def test_no_mood_leaves_the_description_alone(self):
        self.assertNotIn("[Mood]", self.room1.get_display_desc(self.char1))

    def test_mood_and_setter_follow_the_description(self):
        set_mood(self.room1, "Rain on the shutters.", self.char1)
        desc = self.room1.get_display_desc(self.char1)
        self.assertTrue(desc.startswith("room_desc"))
        self.assertIn("|w[Mood]|n Rain on the shutters.", desc)
        self.assertIn(f"(set by {self.char1.key})", desc)

    def test_mood_shows_in_the_full_look(self):
        set_mood(self.room1, "Lanterns gutter.", self.char1)
        self.assertIn("Lanterns gutter.", self.room1.return_appearance(self.char2))

    def test_clear_removes_text_and_attribution(self):
        set_mood(self.room1, "Quiet.", self.char1)
        self.assertEqual(clear_mood(self.room1), "Quiet.")
        self.assertEqual(self.room1.room_mood, "")
        self.assertIsNone(self.room1.room_mood_setter)

    def test_whitespace_is_collapsed_and_limits_enforced(self):
        self.assertEqual(set_mood(self.room1, "  a \n  b  ", self.char1), "a b")
        with self.assertRaises(ValueError):
            set_mood(self.room1, "   ", self.char1)
        with self.assertRaises(ValueError):
            set_mood(self.room1, "x" * (MOOD_MAX_LENGTH + 1), self.char1)
        self.assertEqual(self.room1.room_mood, "a b")


class TestCmdMood(SocialCommandTestCase):
    def test_bare_with_no_mood(self):
        self.call(CmdMood(), "", "No mood is set here.")

    def test_staff_sets_it_and_the_room_hears(self):
        with mock.patch.object(self.char2, "msg") as heard:
            self.call(CmdMood(), "Smoke hangs low.", "Mood set: Smoke hangs low.")
        self.assertEqual(self.room1.room_mood, "Smoke hangs low.")
        self.assertEqual(self.room1.room_mood_setter, self.char1.key)
        # msg_contents delivers text=(message, kwargs) as a keyword.
        text = heard.call_args.kwargs["text"]
        self.assertIn(
            "sets the mood: Smoke hangs low.", text[0] if isinstance(text, tuple) else text
        )

    def test_bare_shows_mood_and_setter(self):
        set_mood(self.room1, "Bells far off.", self.char1)
        self.call(CmdMood(), "", f"[Mood] Bells far off. (set by {self.char1.key})")

    def test_clear(self):
        set_mood(self.room1, "Bells far off.", self.char1)
        self.call(CmdMood(), "/clear", "Mood cleared.")
        self.assertEqual(self.room1.room_mood, "")
        self.call(CmdMood(), "/clear", "This room has no mood to clear.")

    def test_too_long_is_refused_and_nothing_changes(self):
        result = self.call(CmdMood(), "x" * (MOOD_MAX_LENGTH + 1))
        self.assertIn(f"Keep a mood to {MOOD_MAX_LENGTH} characters", result)
        self.assertEqual(self.room1.room_mood, "")

    def test_unknown_switch(self):
        self.call(CmdMood(), "/loud Thunder.", "Unknown switch: /loud.")

    def test_ordinary_player_is_refused_without_a_scene(self):
        result = self.call(CmdMood(), "Mine now.", caller=self.char2)
        self.assertIn("You can't set the mood here.", result)
        self.assertEqual(self.room1.room_mood, "")
        set_mood(self.room1, "Staff's.", self.char1)
        self.call(CmdMood(), "/clear", "You can't set the mood here.", caller=self.char2)
        self.assertEqual(self.room1.room_mood, "Staff's.")

    def test_anyone_can_read_it(self):
        set_mood(self.room1, "Wind.", self.char1)
        self.call(CmdMood(), "", "[Mood] Wind.", caller=self.char2)

    def test_room_owner_can_set_it(self):
        self.room1.locks.add(f"control:id({self.char2.id})")
        self.call(CmdMood(), "Mine now.", "Mood set: Mine now.", caller=self.char2)


@unittest.skipUnless(HAS_SCENES, "evennia_scenes not installed")
class TestMoodSceneRules(SocialTestCase):
    """Scene-aware rights. char2 is never owner or staff here."""

    def scene(self, privacy="public", *, creator=None, status="open"):
        from evennia_scenes.models import Scene

        creator = creator or self.char1
        scene = Scene.objects.create(
            title="Rehearsal",
            room=self.room1,
            room_name=self.room1.key,
            creator=creator,
            creator_name=creator.key,
        )
        Scene.objects.filter(pk=scene.pk).update(privacy=privacy, status=status)
        return Scene.objects.get(pk=scene.pk)

    def join(self, scene, character, *, role="participant", active=True):
        from evennia_scenes.models import SceneParticipant

        SceneParticipant.objects.create(
            scene=scene,
            character=character,
            character_name=character.key,
            role=role,
            is_active=active,
        )

    def test_public_scene_participant_may(self):
        self.join(self.scene(), self.char2)
        self.assertTrue(can_set_mood(self.char2, self.room1))

    def test_public_scene_observer_or_leaver_may_not(self):
        scene = self.scene()
        self.join(scene, self.char2, role="observer")
        self.assertFalse(can_set_mood(self.char2, self.room1))
        scene.participants.update(role="participant", is_active=False)
        self.assertFalse(can_set_mood(self.char2, self.room1))

    def test_non_participant_may_not_even_in_a_public_scene(self):
        self.scene()
        self.assertFalse(can_set_mood(self.char2, self.room1))

    def test_private_scene_is_host_only(self):
        for privacy in ("pose_private", "view_private"):
            with self.subTest(privacy=privacy):
                scene = self.scene(privacy)
                self.join(scene, self.char2)
                self.assertFalse(can_set_mood(self.char2, self.room1))
                scene.delete()
        self.scene("pose_private", creator=self.char2)
        self.assertTrue(can_set_mood(self.char2, self.room1))

    def test_an_unknown_privacy_tier_fails_closed(self):
        self.join(self.scene("rehearsal_only"), self.char2)
        self.assertFalse(can_set_mood(self.char2, self.room1))

    def test_a_closed_scene_grants_nothing(self):
        self.join(self.scene(status="closed"), self.char2)
        self.assertFalse(can_set_mood(self.char2, self.room1))

    def test_a_scene_elsewhere_grants_nothing_here(self):
        from evennia_scenes.models import Scene

        scene = self.scene()
        self.join(scene, self.char2)
        Scene.objects.filter(pk=scene.pk).update(room=self.room2)
        self.assertFalse(can_set_mood(self.char2, self.room1))

    @override_settings(SOCIAL_SCENES_APP_LABEL="not_a_scenes_app")
    def test_a_missing_partner_label_means_owner_and_staff_only(self):
        self.join(self.scene(), self.char2)
        self.assertFalse(can_set_mood(self.char2, self.room1))
        self.assertTrue(can_set_mood(self.char1, self.room1))
