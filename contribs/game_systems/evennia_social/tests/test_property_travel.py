"""Host-managed rooms keep travel and remote discovery grants authoritative."""

from unittest.mock import patch

from django.test import override_settings

from evennia_social import presence
from evennia_social.commands.teleportation import CmdSummon, _store_request
from evennia_social.search import find_room_for_player

from .base import SocialCommandTestCase


def travel(actor, room):
    return room.attributes.get("test_admission")


def visible(room, viewer=None):
    return room.attributes.get("test_visibility")


@override_settings(
    LINKS_ROOM_TRAVEL="evennia_social.tests.test_property_travel.travel",
    LINKS_ROOM_VISIBILITY="evennia_social.tests.test_property_travel.visible",
)
class TestPropertyTravel(SocialCommandTestCase):
    def test_explicit_grant_allows_private_unvisited_destination(self):
        self.room2.allow_teleport = "private"
        self.room2.db.test_admission = True
        self.char2.visited_rooms = set()
        room, _ = find_room_for_player(self.char2, self.room2.key, self.char2)
        self.assertEqual(room, self.room2)

    def test_remote_presence_obeys_managed_room_visibility(self):
        self.char2.location = self.room2
        self.room2.db.test_visibility = False
        self.assertFalse(presence.is_findable(self.char2))
        self.assertTrue(presence.is_findable(self.char2, self.char1))
        self.assertTrue(presence.is_findable(self.char2, self.char2))

    def test_summon_acceptance_rechecks_revoked_admission(self):
        self.char1.location = self.room2
        self.room2.db.test_admission = True
        _store_request(self.char2, self.char1, "summon", self.room2.pk)
        self.room2.db.test_admission = False
        with patch(
            "evennia_social.commands.teleportation.find_character", return_value=(self.char1, None)
        ):
            self.call(CmdSummon(), f"/accept {self.char1.key}", caller=self.char2)
        self.assertEqual(self.char2.location, self.room1)
        self.assertNotIn(self.char1.pk, self.char2.pending_summon_requests)
