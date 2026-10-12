"""Fresh-process Building seams; optional partners are physically absent."""

from importlib.util import find_spec

from django.apps import apps
from django.conf import settings
from django.test import override_settings
from django.urls import include, path
from evennia.web.urls import urlpatterns as defaults
from evennia_building.tests import TestInteriors

urlpatterns = [
    path("building/", include("evennia_building.urls")),
    path("api/v1/building/", include("evennia_building.api.urls")),
]
if apps.is_installed("evennia_maps"):
    urlpatterns += [
        path("map/", include("evennia_maps.urls")),
        path("api/v1/", include("evennia_maps.api.urls")),
    ]
if apps.is_installed("evennia_regions"):
    urlpatterns += [
        path("regions/", include("evennia_regions.urls")),
        path("api/v1/", include("evennia_regions.api.urls")),
    ]
urlpatterns += defaults


@override_settings(
    LINKS_ROOM_TRAVEL="evennia_building.access.can_teleport",
    LINKS_ROOM_VISIBILITY="evennia_building.visibility.room_visibility",
)
class BuildingPartnerTests(TestInteriors):
    def test_physical_partner_absence(self):
        for label in settings.BUILDING_ABSENT_PARTNERS:
            self.assertFalse(apps.is_installed(label))
            self.assertIsNone(find_spec(label))

    def test_real_social_policy_and_imports(self):
        if not apps.is_installed("evennia_social"):
            self.skipTest("Social intentionally absent")
        from evennia_social import presence
        from evennia_social.commands import CmdJoin, CmdSummon
        from evennia_social.search import find_room_for_player

        self.assertTrue(CmdJoin and CmdSummon)
        property = self.approve()
        self.char2.location = self.entry.room
        self.assertFalse(presence.is_findable(self.char2))
        self.assertTrue(presence.is_findable(self.char2, self.char1))
        self.char2.visited_rooms = set()
        self.assertEqual(
            find_room_for_player(self.char2, self.entry.room.key, self.char2)[0], self.entry.room
        )
        self.assertEqual(property.owner_id, self.char2.pk)

    def test_rendered_index_and_dark_deploy(self):
        self.account2.characters.add(self.char2)
        self.client.force_login(self.account2)
        response = self.client.get("/building/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Garden home")
        with override_settings(BUILDING_REVEALED=False):
            self.assertEqual(self.client.get("/building/").status_code, 403)
