# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Shared delivery gates and independent room capture after committed actions."""

from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from evennia.utils.test_resources import EvenniaTest

from .emissions import deliver, emit
from .tests import CraftingFixture


class EmissionDeliveryTests(CraftingFixture, EvenniaTest):
    def setUp(self):
        super().setUp()
        override = override_settings(LINKS_ROOM_LIVE=None)
        override.enable()
        self.addCleanup(override.disable)

    def test_missing_actor_or_room_cannot_send_unattributed_output(self):
        with patch.object(self.char2, "msg") as heard:
            deliver(self.room1.pk, 0, "<EVENT> Orphaned.")
            deliver(0, self.char1.pk, "<EVENT> No room.", destination_ids=[self.room1.pk])
        heard.assert_not_called()

    def test_later_wave_gates_apply_only_to_their_own_emissions(self):
        message = "<EVENT> A tune."
        with (
            override_settings(
                RP_CRAFTING_WAVE_TWO_REVEALED=False, RP_CRAFTING_WAVE_THREE_REVEALED=True
            ),
            patch.object(self.char2, "msg") as heard,
        ):
            emit(self.room1.pk, self.char1.pk, message)
            heard.assert_not_called()
            emit(self.room1.pk, self.char1.pk, message, wave_three=True)
            heard.assert_called_once_with(
                (message, {"type": "crafting_event"}), from_obj=self.char1
            )

    @skipUnless(apps.is_installed("evennia_accessibility"), "Accessibility required")
    def test_archived_remote_room_receives_neither_output_nor_capture(self):
        if apps.is_installed("evennia_scenes"):
            from evennia_scenes.models import Scene

            Scene.objects.create(room=self.room2, creator=self.char2, title="An archived room")
        self.char2.move_to(self.room2, quiet=True)
        with (
            override_settings(LINKS_ROOM_LIVE=lambda room: room.pk == self.room1.pk),
            patch.object(self.char2, "msg") as heard,
        ):
            deliver(
                self.room1.pk, self.char1.pk, "<EVENT> A tune.", destination_ids=[self.room2.pk]
            )
        heard.assert_not_called()
        if apps.is_installed("evennia_scenes"):
            from evennia_scenes.models import LogEntry

            self.assertFalse(LogEntry.objects.exists())

    @skipUnless(
        apps.is_installed("evennia_scenes") and apps.is_installed("evennia_accessibility"),
        "Scenes and Accessibility required",
    )
    def test_room_capture_failure_does_not_stop_the_next_rooms_output_or_log(self):
        from evennia_scenes.capture import capture_room_event
        from evennia_scenes.models import LogEntry, Scene

        scene = Scene.objects.create(room=self.room2, creator=self.char2, title="A distant tune")
        self.char2.move_to(self.room2, quiet=True)
        self.account2.options.options_dict = dict(self.account2.options.options_dict) | {
            "mute_ambient_effects": ("Ambient effects", "Boolean", False)
        }
        self.account2.options.set("mute_ambient_effects", "False")

        def capture(room, author, content):
            if room == self.room1:
                raise RuntimeError("A broken scene hook")
            return capture_room_event(room, author, content)

        with (
            patch("evennia_scenes.capture.capture_room_event", side_effect=capture),
            patch.object(self.char2, "msg") as heard,
        ):
            deliver(
                self.room1.pk,
                self.char1.pk,
                "<EVENT> A tune.",
                destination_ids=[self.room2.pk, self.room2.pk, self.room1.pk],
            )
        heard.assert_called_once()
        self.assertEqual(LogEntry.objects.get().scene, scene)
