"""Public frontier, mixed homes and mood rights with the actual host composition."""

from datetime import timedelta

from django.test import override_settings
from django.utils import timezone
from evennia_building import frontier_lifecycle, services
from evennia_building.models import BuildingClock, Property
from evennia_building.test_frontier import TestFrontier
from typeclasses.characters import Character
from typeclasses.exits import Exit
from typeclasses.rooms import Room


@override_settings(ROOT_URLCONF="web.urls")
class FrontierSeams(TestFrontier):
    character_typeclass = Character
    room_typeclass = Room
    exit_typeclass = Exit

    def test_street_is_public_while_locked_home_and_presence_remain_private(self):
        from evennia_maps.permissions import is_room_web_visible
        from evennia_social.presence import is_findable

        part = self.interior()
        self.acknowledge_all()
        result = self.approve()
        home = Property.objects.get(part=part)
        services.set_locked(self.recipient, home, True)
        entrance = result.connections.get(exit__db_location=self.room1).exit
        entrance.at_traverse(self.outsider, self.entry.room)
        self.assertEqual(self.outsider.location, self.entry.room)
        home.entrance.at_traverse(self.outsider, part.entry)
        self.assertEqual(self.outsider.location, self.entry.room)
        self.recipient.location = part.entry
        self.assertFalse(is_findable(self.recipient, self.outsider))
        self.assertFalse(is_room_web_visible(part.entry, self.outsider))
        self.assertTrue(is_room_web_visible(self.entry.room, self.outsider))
        self.assertFalse(entrance.delete())

    def test_actual_social_mood_command_grants_steward_only_temporary_text(self):
        from evennia_social.commands.mood import CmdMood
        from evennia_social.commands.roomconfig import _can_configure_room

        self.approve()
        self.char2.location = self.entry.room
        self.call(CmdMood(), "Quiet footsteps.", caller=self.char2)
        self.assertEqual(self.entry.room.db.room_mood, "Quiet footsteps.")
        self.assertFalse(_can_configure_room(self.char2, self.entry.room))

    def test_provenance_in_room_details_command_web_overlay_and_examine_attribute(self):
        from evennia_building.overlays import provide

        from evennia_regions.views import RoomDetailView
        from evennia_social.commands.roomconfig import CmdRoomConfig

        self.approve()
        self.char1.location = self.entry.room
        shown = self.call(CmdRoomConfig(), "", caller=self.char1)
        self.assertIn("Reclaimed by", shown)
        response = self.web(RoomDetailView.as_view(), self.outsider, pk=self.entry.room_id)
        response.render()
        self.assertContains(response, "Reclaimed by")
        self.assertContains(response, self.char2.key)
        overlay = provide(sender=None, room_ids=[self.entry.room_id], viewer=self.outsider)
        self.assertIn(self.entry.room_id, overlay["frontier"])
        self.assertEqual(self.entry.room.db.building_provenance["reclaimed_by"], self.char2.key)
        self.assertNotIn("Reclaimed by", self.entry.room.return_appearance(self.outsider))

    @override_settings(BUILDING_ACTIVITY_PROVIDER="world.sandbox.building.last_played")
    def test_real_character_activity_provider_flags_without_changing_stewardship(self):
        result = self.approve()
        now = timezone.now()
        old = now - timedelta(days=40)
        BuildingClock.objects.update_or_create(pk=1, defaults={"revealed_at": old})
        result.rooms.update(assigned_at=old)
        self.char2.db.sandbox_last_seen = old
        self.assertEqual(len(frontier_lifecycle.check_quiet(now=now)), 1)
        self.assertEqual(result.rooms.get().steward_id, self.char2.pk)
        self.char2.db.sandbox_last_seen = now
        self.assertEqual(frontier_lifecycle.check_quiet(now=now), [])
