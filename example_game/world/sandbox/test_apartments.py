"""Apartment consent, passage and lifecycle with the actual host composition."""

from django.test import override_settings
from evennia_building import attachments, lifecycle, services
from evennia_building.test_apartments import TestApartments
from typeclasses.characters import Character
from typeclasses.exits import Exit
from typeclasses.rooms import Room


@override_settings(ROOT_URLCONF="web.urls")
class ApartmentSeams(TestApartments):
    character_typeclass = Character
    room_typeclass = Room
    exit_typeclass = Exit

    def test_guest_traverses_locked_parent_without_map_or_presence_disclosure(self):
        from evennia_maps.permissions import is_room_web_visible
        from evennia_social.presence import is_findable

        child = self.apartment()
        services.set_locked(self.char2, self.parent, True)
        services.set_override(self.char2, self.hall.room, [])
        invitation = services.invite(self.tenant, child, self.guest, entry=True, maps=False)
        services.answer_invitation(self.guest, invitation, accept=True)
        self.parent.entrance.at_traverse(self.guest, self.entry.room)
        self.assertEqual(self.guest.location, self.entry.room)
        hall_door = self.parent_project.doors.get(source=self.entry, target=self.hall).exit
        self.assertTrue(hall_door.access(self.guest, "traverse"))
        hall_door.at_traverse(self.guest, self.hall.room)
        self.assertEqual(self.guest.location, self.hall.room)
        self.assertFalse(is_room_web_visible(self.bedroom.room, self.guest))
        self.assertFalse(is_room_web_visible(self.hall.room, self.tenant))
        self.char2.location = self.bedroom.room
        self.assertFalse(is_findable(self.char2, self.guest))
        child.entrance.at_traverse(self.guest, self.child_entry.room)
        self.assertEqual(self.guest.location, self.child_entry.room)
        services.invite(self.tenant, child, self.guest, revoke=True)
        child.departure.at_traverse(self.guest, self.hall.room)
        outward = self.parent_project.doors.get(source=self.hall, target=self.entry).exit
        outward.at_traverse(self.guest, self.entry.room)
        self.parent.departure.at_traverse(self.guest, self.room1)
        self.assertEqual(self.guest.location, self.room1)

    def test_agreed_doors_and_managed_geometry_cannot_be_deleted(self):
        child = self.apartment()
        for exit in (
            child.entrance,
            child.departure,
            self.parent.entrance,
            self.parent.departure,
            self.parent_project.doors.get(source=self.entry, target=self.hall).exit,
        ):
            self.assertFalse(exit.delete())
        self.assertFalse(self.hall.room.delete())
        self.assertTrue(attachments.route_valid(self.agreement))

    def test_quiet_provider_uses_existing_host_character_hook(self):
        from datetime import timedelta

        from django.utils import timezone
        from evennia_building.models import BuildingClock, Property

        now = timezone.now()
        old = now - timedelta(days=40)
        BuildingClock.objects.create(pk=1, revealed_at=old)
        Property.objects.all().update(created_at=old)
        self.char2.attributes.add("sandbox_last_seen", now)
        with override_settings(BUILDING_ACTIVITY_PROVIDER="world.sandbox.building.last_played"):
            self.assertEqual(lifecycle.check_quiet(now=now), [])
