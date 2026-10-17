# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Crafted events exercise actual ignore, scene, posing and activity partners."""

from copy import deepcopy
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from evennia.objects.objects import DefaultCharacter
from evennia.utils.test_resources import EvenniaTest
from evennia_rp_crafting.events import use
from evennia_rp_crafting.test_events import EventFixture
from evennia_rp_crafting.test_wave_two import WaveTwoFixture
from typeclasses.characters import Character
from typeclasses.rooms import Room


@skipUnless(
    apps.is_installed("evennia_scenes") and apps.is_installed("evennia_social"),
    "Scenes and Social required",
)
class EmissionSeams(EventFixture, EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        override = override_settings(LINKS_ROOM_LIVE=None)
        override.enable()
        self.addCleanup(override.disable)
        if apps.is_installed("evennia_rptracker"):
            from evennia_rptracker import tracker

            sessions = patch.dict(tracker._active_sessions, {}, clear=True)
            sessions.start()
            self.addCleanup(sessions.stop)

    def scene(self, room=None):
        from evennia_scenes.models import Scene

        return Scene.objects.create(
            title="An item event", room=room or self.room1, creator=self.char2
        )

    def activity(self):
        from evennia_scenes.models import SceneParticipant

        result = {
            "participants": list(SceneParticipant.objects.order_by("pk").values()),
            "posing": [
                (actor.last_pose_time, actor.last_pose_text, actor.pose_status)
                for actor in (self.char1, self.char2)
            ],
        }
        if apps.is_installed("evennia_rptracker"):
            from evennia_rptracker import tracker
            from evennia_rptracker.models import RPSession, RPSessionPartner

            result["tracker"] = deepcopy(tracker._active_sessions)
            result["sessions"] = list(RPSession.objects.order_by("pk").values())
            result["partners"] = list(RPSessionPartner.objects.order_by("pk").values())
        if apps.is_installed("evennia_rp_chargen"):
            from evennia_rp_chargen import locks

            result["locks"] = [
                deepcopy(actor.attributes.get(locks.ATTR_KEY, category=locks.ATTR_CATEGORY))
                for actor in (self.char1, self.char2)
            ]
        return result

    def test_consumable_is_ignored_and_logged_without_changing_existing_activity(self):
        from evennia_scenes.models import LogEntry, SceneParticipant

        if apps.is_installed("evennia_rp_chargen"):
            from evennia_rp_chargen.models import CharacterBuild

            CharacterBuild.objects.create(
                character=self.char1, status=CharacterBuild.Status.FINALIZED
            )
        self.char2.record_pose("Answers a greeting.")
        self.char1.record_pose("Greets a friend.")
        self.char1.record_pose("Continues the conversation.")
        if apps.is_installed("evennia_rptracker"):
            from evennia_rptracker.models import RPSession

            self.assertTrue(
                RPSession.objects.filter(character=self.char1, status="active").exists()
            )
        scene = self.scene()
        SceneParticipant.objects.create(
            scene=scene,
            character=self.char1,
            character_name=self.char1.key,
            is_active=False,
            pose_count=7,
        )
        self.char1.pose_status = "observing"
        before = self.activity()
        self.account2.db.ignore_list = [self.account.pk]
        received = []
        with (
            patch.object(
                DefaultCharacter, "msg", lambda target, text=None, **kw: received.append(target.pk)
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            use(self.char1, self.item())
        self.assertNotIn(self.char2.pk, received)
        self.assertIn(self.char1.pk, received)
        self.assertEqual(LogEntry.objects.get(scene=scene).author, self.char1)
        self.assertEqual(self.activity(), before)

    def test_handed_off_consumable_is_attributed_to_user_rather_than_maker(self):
        from evennia_scenes.models import LogEntry

        scene = self.scene()
        item = self.item()
        item.move_to(self.char2, quiet=True)
        self.account.db.ignore_list = [self.account2.pk]
        received = []
        with (
            patch.object(
                DefaultCharacter, "msg", lambda target, text=None, **kw: received.append(target.pk)
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = use(self.char2, item)
        self.assertNotIn(self.char1.pk, received)
        self.assertEqual(result.actor_id, self.char2.pk)
        self.assertEqual(LogEntry.objects.get(scene=scene).author, self.char2)

    def test_legacy_events_work_while_later_waves_are_hidden(self):
        from evennia_scenes.models import LogEntry

        scene = self.scene()
        with (
            override_settings(
                RP_CRAFTING_WAVE_TWO_REVEALED=False, RP_CRAFTING_WAVE_THREE_REVEALED=False
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            use(self.char1, self.item())
        self.assertEqual(LogEntry.objects.filter(scene=scene).count(), 1)

    def test_deferred_delivery_uses_original_room_after_actor_moves(self):
        from evennia_scenes.models import LogEntry

        source, other = self.scene(), self.scene(self.room2)
        with self.captureOnCommitCallbacks(execute=True):
            use(self.char1, self.item())
            self.char1.move_to(self.room2, quiet=True)
        self.assertEqual(LogEntry.objects.get().scene, source)
        self.assertFalse(LogEntry.objects.filter(scene=other).exists())

    def test_recipient_failure_does_not_lose_scene_log_or_other_deliveries(self):
        from evennia_scenes.models import LogEntry

        scene = self.scene()
        received = []

        def receive(target, text=None, **kwargs):
            if target == self.char1:
                raise RuntimeError("a disconnected recipient")
            received.append(target.pk)

        with (
            patch.object(DefaultCharacter, "msg", receive),
            self.captureOnCommitCallbacks(execute=True),
        ):
            use(self.char1, self.item())
        self.assertIn(self.char2.pk, received)
        self.assertEqual(LogEntry.objects.filter(scene=scene).count(), 1)

    def test_staff_actor_keeps_existing_ignore_exception(self):
        self.account.permissions.add("Builder")
        self.account2.db.ignore_list = [self.account.pk]
        received = []
        with (
            patch.object(
                DefaultCharacter, "msg", lambda target, text=None, **kw: received.append(target.pk)
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            use(self.char1, self.item())
        self.assertIn(self.char2.pk, received)


@skipUnless(
    all(
        apps.is_installed(name)
        for name in ("evennia_scenes", "evennia_social", "evennia_accessibility")
    ),
    "Scenes, Social and Accessibility required",
)
class AmbientEmissionSeams(WaveTwoFixture, EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def test_fixture_uses_current_offline_owner_for_ignore_and_non_activity_capture(self):
        from evennia_rp_crafting import fixtures
        from evennia_scenes.models import LogEntry, Scene, SceneParticipant

        fixture = self.fixture(ambient="A lantern chimes.")
        fixtures.install(self.char1, fixture, self.room1)
        self.owner = self.char2
        self.account2.characters.add(self.char2)
        self.char2.account = None
        self.account.db.ignore_list = [self.account2.pk]
        self.account.options.set("mute_ambient_effects", "False")
        scene = Scene.objects.create(
            title="The new owner's lantern", room=self.room1, creator=self.char1
        )
        received = []
        with (
            patch.object(
                DefaultCharacter, "msg", lambda target, text=None, **kw: received.append(target.pk)
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.assertEqual(fixtures.ambient_tick(), 1)
        self.assertNotIn(self.char1.pk, received)
        self.assertEqual(LogEntry.objects.get(scene=scene).author, self.char2)
        self.assertFalse(SceneParticipant.objects.filter(scene=scene).exists())

    def test_temporary_layer_keeps_its_actor_after_room_ownership_changes(self):
        from evennia_rp_crafting import fixtures
        from evennia_scenes.models import LogEntry, Scene, SceneParticipant

        fixtures.decorate(self.char1, self.fixture(ambient="A paper lantern rustles."), self.room1)
        self.owner = self.char2
        self.account2.db.ignore_list = [self.account.pk]
        self.account2.options.set("mute_ambient_effects", "False")
        scene = Scene.objects.create(
            title="Temporary lanterns", room=self.room1, creator=self.char2
        )
        received = []
        with (
            patch.object(
                DefaultCharacter, "msg", lambda target, text=None, **kw: received.append(target.pk)
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.assertEqual(fixtures.ambient_tick(), 1)
        self.assertNotIn(self.char2.pk, received)
        self.assertEqual(LogEntry.objects.get(scene=scene).author, self.char1)
        self.assertFalse(SceneParticipant.objects.filter(scene=scene).exists())
