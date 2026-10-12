"""Building with the actual host typeclasses, settings and installed partners."""

from unittest.mock import patch

from django.test import override_settings
from evennia_building import services
from evennia_building.models import Property
from evennia_building.tests import TestInteriors
from typeclasses.characters import Character
from typeclasses.exits import Exit
from typeclasses.rooms import Room

from evennia_maps.permissions import is_room_web_visible
from evennia_social import presence


class BuildingInteriorSeams(TestInteriors):
    character_typeclass = Character
    room_typeclass = Room
    exit_typeclass = Exit

    def test_host_composes_visibility_and_preserves_unmanaged_rules(self):
        self.room1.db.allow_teleport = "secret"
        self.assertFalse(is_room_web_visible(self.room1, self.char2))
        self.assertTrue(is_room_web_visible(self.entry.room, self.char2))
        self.assertFalse(is_room_web_visible(self.entry.room))
        with override_settings(BUILDING_REVEALED=False):
            self.assertFalse(is_room_web_visible(self.room1, self.char2))

    def test_draft_has_no_scene_presence_rp_or_hangout_context(self):
        from evennia_economy.models import Storefront
        from evennia_rptracker import tracker
        from evennia_scenes.commands import CmdScene
        from evennia_scenes.models import Scene

        from evennia_social.commands.roomconfig import CmdRoomConfig
        from evennia_social.mood import can_set_mood

        services.enter(self.char2, self.project)
        self.assertEqual(self.char2.location.room_type, "ooc")
        self.assertIsNone(self.char2.location.hangout_type)
        self.assertFalse(presence.is_findable(self.char2))
        self.assertIsNone(self.char2.location.active_scene_id)
        self.call(CmdScene(), "/open Draft scene", caller=self.char2)
        self.call(CmdRoomConfig(), "/hangout library", caller=self.char2)
        self.assertFalse(Scene.objects.filter(room=self.entry.room).exists())
        self.assertIsNone(self.entry.room.hangout_type)
        self.assertFalse(can_set_mood(self.char2, self.entry.room))
        with patch.object(tracker, "_active_sessions", {}):
            tracker.record_rp_activity(self.char2, self.entry.room)
            self.assertEqual(tracker._active_sessions, {})
        self.assertFalse(Storefront.objects.filter(room=self.entry.room).exists())

    def test_property_rooms_and_exits_use_host_mixins(self):
        property = self.approve()
        self.assertIsInstance(self.entry.room, Room)
        self.assertIsInstance(property.entrance, Exit)
        self.assertFalse(self.entry.room.delete())
        self.assertEqual(Property.objects.count(), 1)
        self.assertTrue(property.departure.access(self.char2, "traverse"))

    def test_staff_entry_is_attributed_without_ejecting_occupants(self):
        from evennia_building.models import BuildAudit

        property = self.approve()
        services.set_locked(self.char2, property, True)
        self.char1.move_to(self.entry.room, quiet=True)
        self.assertTrue(
            BuildAudit.objects.filter(
                property=property, actor=self.char1, action="staff_entry"
            ).exists()
        )
        self.assertEqual(self.char1.location, self.entry.room)
