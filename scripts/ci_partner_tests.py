# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Fresh-process integration fixture copied into a disposable Evennia game.

CI runs this module with every contrib installed, then in a separate environment
where evennia-calendar was never installed. Real AppConfig.ready() receivers and
real partner URLs must agree with the selected configuration; no signals or
imports are mocked and no installed-app overrides are used.
"""

import sys
from datetime import timedelta
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec

from django.apps import apps
from django.conf import settings
from django.test import RequestFactory
from django.urls import NoReverseMatch, include, path, reverse
from django.utils import timezone
from evennia.objects.objects import DefaultRoom
from evennia.utils.test_resources import EvenniaTest
from evennia.web.urls import urlpatterns as evennia_default_urlpatterns
from evennia_scenes.models import Scene

from evennia_links.runtime import get as _runtime
from evennia_maps.models import MapPlane, RoomTile
from evennia_maps.overlays import collect_overlays, overlay_url_templates
from evennia_maps.typeclasses import MapsRoomMixin
from evennia_maps.views import PlaneLiveMapView
from evennia_regions.models import Region, RegionMembership

urlpatterns = [
    path("map/", include("evennia_maps.urls")),
    path("regions/", include("evennia_regions.urls")),
    path("", include(("evennia_scenes.urls", "evennia_scenes"))),
    path("lore/", include("evennia_lore.urls")),
    path("api/v1/", include("evennia_maps.api.urls")),
    path("api/v1/", include("evennia_regions.api.urls")),
]
if apps.is_installed("evennia_calendar"):
    urlpatterns.append(path("calendar/", include("evennia_calendar.urls")))
urlpatterns += evennia_default_urlpatterns


class PartnerRoom(MapsRoomMixin, DefaultRoom):
    """A real mapped room in the disposable integration game."""


class TestPartnerIntegration(EvenniaTest):
    """Require working seams and renders both with and without the calendar."""

    room_typeclass = PartnerRoom

    def setUp(self):
        """Create real region, scene, lore, and optional event data on a mapped room."""
        super().setUp()
        from evennia_lore.models import LoreEntry, LoreRegionLink

        self.plane = MapPlane.objects.create(name="Partner plane")
        self.room1.key = "Partner Hall"
        RoomTile.objects.create(
            plane=self.plane, room=self.room1, room_name=self.room1.key, x=0, y=0
        )
        self.region = Region.objects.create(name="Partner District")
        RegionMembership.objects.create(region=self.region, room=self.room1, is_primary=True)
        self.live = Scene.objects.create(
            title="Public partner scene", room=self.room1, creator=self.char1
        )
        Scene.objects.create(
            title="Recent partner scene",
            room=self.room1,
            status=Scene.Status.CLOSED,
            ended_at=timezone.now(),
            creator=self.char1,
        )
        entry = LoreEntry.objects.create(
            entry_number=1, title="Partner lore", status=LoreEntry.Status.PUBLISHED
        )
        LoreRegionLink.objects.create(entry=entry, region_id=self.region.pk)
        if settings.PARTNER_TEST_CALENDAR:
            from evennia_calendar.models import CalendarEvent, SceneCalendarLink

            self.event = CalendarEvent.objects.create(
                title="Public lottery event",
                scheduled_time=timezone.now() + timedelta(days=1),
                is_staff_event=True,
            )
            SceneCalendarLink.objects.create(event=self.event, scene_id=self.live.pk)

    def test_selected_calendar_configuration_is_real(self):
        """Removing only an app label cannot masquerade as an uninstalled partner."""
        self.assertEqual(apps.is_installed("evennia_calendar"), settings.PARTNER_TEST_CALENDAR)
        if settings.PARTNER_TEST_CALENDAR:
            self.assertIsNotNone(find_spec("evennia_calendar"))
            self.assertTrue(version("evennia-calendar"))
        else:
            self.assertIsNone(find_spec("evennia_calendar"))
            with self.assertRaises(PackageNotFoundError):
                version("evennia-calendar")
            self.assertFalse(any(name.startswith("evennia_calendar") for name in sys.modules))

    def test_retained_contribs_import_their_command_surfaces(self):
        """Catch ungated imports in command modules as well as AppConfig.ready()."""
        for config in apps.get_app_configs():
            if config.name.startswith("evennia_"):
                module = f"{config.name}.commands"
                if find_spec(module) is not None:
                    with self.subTest(module=module):
                        import_module(module)

    def test_real_ready_receivers_supply_the_remaining_overlays(self):
        """Verify every retained provider answers with its own domain data."""
        expected = {
            "primary_region",
            "active_scenes",
            "has_active_scene",
            "recent_scene_count",
            "recent_scenes",
            "has_lore",
            "present",
        }
        if settings.PARTNER_TEST_CALENDAR:
            expected.add("upcoming_events")
        for staff in (False, True):
            with self.subTest(staff=staff):
                overlays = collect_overlays([self.room1.pk], staff=staff)
                # Building's public growth overlay answers staff, or everyone once revealed.
                frontier = apps.is_installed("evennia_building") and (
                    staff or _runtime("BUILDING_REVEALED")
                )
                self.assertEqual(set(overlays), expected | ({"frontier"} if frontier else set()))
                if frontier:
                    # An ordinary world room carries no growth metadata.
                    self.assertEqual(overlays["frontier"], {})
                self.assertEqual(overlays["primary_region"][self.room1.pk]["id"], self.region.pk)
                self.assertEqual(overlays["active_scenes"][self.room1.pk][0]["id"], self.live.pk)
                self.assertTrue(overlays["has_lore"][self.room1.pk])
                self.assertEqual(overlays["recent_scene_count"][self.room1.pk], 1)
                # EvenniaTest logs in and puppets char1 through the real session
                # handler. Keep this seam free of mocked character discovery.
                self.assertEqual(overlays["present"], {self.room1.pk: [self.char1.key]})
                if settings.PARTNER_TEST_CALENDAR:
                    self.assertEqual(
                        overlays["upcoming_events"][self.room1.pk][0]["id"], self.event.pk
                    )

    def test_outbound_links_match_the_installed_routes(self):
        """Advertise only destinations with real mounted routes."""
        links = overlay_url_templates()
        expected = {"room", "region", "scene"}
        if settings.PARTNER_TEST_CALENDAR:
            expected.add("event")
        self.assertEqual(set(links), expected)
        if not settings.PARTNER_TEST_CALENDAR:
            with self.assertRaises(NoReverseMatch):
                reverse("evennia_calendar:calendar-event-detail", args=[0])

    def test_static_map_renders_remaining_overlays_and_links(self):
        """Render the complete static page and retain region and scene links."""
        response = self.client.get(reverse("evennia_maps:plane-detail", args=[self.plane.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Partner Hall")
        self.assertContains(response, "Partner District")
        self.assertContains(response, "Public partner scene")
        self.assertContains(
            response, reverse("evennia_regions:region-detail", args=[self.region.pk])
        )
        self.assertContains(
            response, reverse("evennia_scenes:scene-detail", args=[self.live.scene_number])
        )
        if not settings.PARTNER_TEST_CALENDAR:
            self.assertNotContains(response, "/calendar/")

    def test_live_map_retains_the_feed_and_only_available_links(self):
        """Render the live map shell with the feed and available partner links."""
        request = RequestFactory().get(reverse("evennia_maps:plane-live-map", args=[self.plane.pk]))
        request.user = self.account2
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        response = PlaneLiveMapView.as_view()(request, pk=self.plane.pk)
        response.render()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-tiles-url-template="/api/v1/planes/0/tiles/"')
        event_url = "/calendar/0/" if settings.PARTNER_TEST_CALENDAR else ""
        self.assertContains(response, f'data-event-url-template="{event_url}"')
        self.assertContains(response, 'data-region-url-template="/regions/0/"')

    def test_anonymous_live_map_redirects_to_the_static_partner_map(self):
        response = self.client.get(reverse("evennia_maps:plane-live-map", args=[self.plane.pk]))
        self.assertRedirects(response, reverse("evennia_maps:plane-detail", args=[self.plane.pk]))

    def test_authenticated_tile_feed_keeps_remaining_provider_data(self):
        """Serve real overlay data with no calendar events when its partner is absent."""
        self.client.force_login(self.account)
        response = self.client.get(reverse("api-plane-tiles", args=[self.plane.pk]))
        self.assertEqual(response.status_code, 200)
        tile = response.json()["results"][0]
        self.assertEqual(tile["primary_region_id"], self.region.pk)
        self.assertTrue(tile["has_active_scene"])
        self.assertTrue(tile["has_lore"])
        self.assertEqual(tile["recent_scene_count"], 1)
        self.assertEqual(tile["present"], [self.char1.key])
        if settings.PARTNER_TEST_CALENDAR:
            self.assertEqual(tile["upcoming_events"][0]["id"], self.event.pk)
        else:
            self.assertEqual(tile["upcoming_events"], [])

    def test_live_presence_privacy_and_disconnect_use_real_sessions(self):
        """Refresh the feed after visibility changes and after unpuppeting."""
        from evennia_social import presence

        url = reverse("api-plane-tiles", args=[self.plane.pk])
        self.assertEqual(self.session.get_puppet(), self.char1)
        cases = (
            (presence.FINDABLE, "current", [self.char1.key], [self.char1.key]),
            (presence.UNFINDABLE, "current", [], [f"{self.char1.key} (unfindable)"]),
            ("dark", "legacy", [], [f"{self.char1.key} (unfindable)"]),
        )
        self.assertTrue(cases)
        for visibility, source, public_names, staff_names in cases:
            if source == "legacy":
                self.char1.attributes.add(presence.ATTRIBUTE, visibility)
            else:
                presence.set_visibility(self.char1, visibility)
            for account, expected in ((self.account2, public_names), (self.account, staff_names)):
                with self.subTest(visibility=visibility, source=source, account=account.key):
                    self.client.force_login(account)
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["results"][0]["present"], expected)
        self.account.unpuppet_object(self.session)
        self.assertIsNone(self.session.get_puppet())
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["present"], [])

    def test_room_panel_gathers_real_partner_data(self):
        """The room-detail route: real overlays, real sections, real links."""
        self.client.force_login(self.account2)
        response = self.client.get(
            reverse("api-plane-tile-detail", kwargs={"pk": self.plane.pk, "room_id": self.room1.pk})
        )
        self.assertEqual(response.status_code, 200)
        detail = response.json()
        self.assertEqual(detail["region"]["url"], f"/regions/{self.region.pk}/")
        self.assertEqual(detail["active_scenes"][0]["id"], self.live.pk)
        self.assertTrue(detail["active_scenes"][0]["url"])
        self.assertEqual(detail["present"], [self.char1.key])
        lore = next(section for section in detail["sections"] if section["key"] == "lore")
        self.assertEqual(lore["items"][0]["label"], "Partner lore")
        self.assertTrue(lore["items"][0]["locked"])
        if settings.PARTNER_TEST_CALENDAR:
            self.assertEqual(detail["upcoming_events"][0]["url"], f"/calendar/{self.event.pk}/")
        else:
            self.assertEqual(detail["upcoming_events"], [])

    def test_browsable_api_override_works_with_evennias_api_disabled(self):
        """Exercise the game-level override described in both install guides."""
        self.assertFalse(settings.REST_API_ENABLED)
        self.client.force_login(self.account)
        for url in ("/api/v1/", "/api/v1/planes/", "/api/v1/regions/"):
            with self.subTest(url=url):
                response = self.client.get(url, HTTP_ACCEPT="text/html")
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, ">Schema</a>")
                self.assertNotContains(response, ">Documentation</a>")
