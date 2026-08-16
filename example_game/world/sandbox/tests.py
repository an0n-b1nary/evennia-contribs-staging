"""Sandbox integration tests for the world.sandbox glue and the settings
contract the contribs expect from the game.

The glue listener (world/sandbox/glue.py:on_pose_recorded, connected once in
world/sandbox/apps.py:SandboxConfig.ready) is tested end-to-end through
PosingCharacterMixin.record_pose(), with the downstream consumers mocked at
the contrib boundary - their behavior is covered by the contribs' own
suites. Glue imports both consumers lazily inside the function, so patching
the source modules is sufficient.

The map-overlay cases at the bottom are the opposite kind of test: nothing is
mocked, and the point is precisely what only this game can prove. Each of the
six overlay layers lives in a different contrib and connects itself from that
contrib's own AppConfig.ready(), gated on evennia_maps being installed. No
contrib's own suite can show that all four providers answer the same collect,
because no contrib's test game installs the other three.
"""

from importlib import import_module
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.test import RequestFactory
from evennia.utils.test_resources import EvenniaTest, EvenniaTestCase
from typeclasses.characters import Character
from typeclasses.rooms import Room


class TestPoseRecordedGlue(EvenniaTest):
    """Contract (c): on_pose_recorded fans out to scenes then rptracker."""

    character_typeclass = Character
    room_typeclass = Room

    def test_capture_then_record_in_order(self):
        order = []
        with (
            mock.patch("evennia_scenes.capture.capture_to_scene") as mock_capture,
            mock.patch("evennia_rptracker.record_rp_activity") as mock_record,
        ):
            mock_capture.side_effect = lambda *a, **k: order.append("capture")
            mock_record.side_effect = lambda *a, **k: order.append("record")

            self.char1.record_pose("waves.", pose_type="pose")

            mock_capture.assert_called_once_with(self.char1, "waves.", log_type="pose")
            mock_record.assert_called_once_with(self.char1, self.room1)
            self.assertEqual(order, ["capture", "record"])

    def test_capture_failure_does_not_block_record(self):
        order = []

        def capture_boom(*args, **kwargs):
            order.append("capture")
            raise RuntimeError("boom")

        with (
            mock.patch("evennia_scenes.capture.capture_to_scene") as mock_capture,
            mock.patch("evennia_rptracker.record_rp_activity") as mock_record,
        ):
            mock_capture.side_effect = capture_boom
            mock_record.side_effect = lambda *a, **k: order.append("record")

            # Must not raise despite capture_to_scene blowing up.
            self.char1.record_pose("waves.", pose_type="pose")

            mock_record.assert_called_once_with(self.char1, self.room1)
            self.assertEqual(order, ["capture", "record"])

    def test_no_location_skips_record(self):
        self.char1.location = None
        with (
            mock.patch("evennia_scenes.capture.capture_to_scene") as mock_capture,
            mock.patch("evennia_rptracker.record_rp_activity") as mock_record,
        ):
            self.char1.record_pose("waves.", pose_type="pose")

            mock_capture.assert_called_once_with(self.char1, "waves.", log_type="pose")
            mock_record.assert_not_called()


class TestContribSettings(EvenniaTestCase):
    """Contract (d): settings the posing/social contribs expect the game to
    register (see server/conf/settings.py and both contribs' READMEs)."""

    def test_contrib_apps_installed(self):
        self.assertIn("evennia_posing", settings.INSTALLED_APPS)
        self.assertIn("evennia_social", settings.INSTALLED_APPS)

    def test_social_settings_exist(self):
        self.assertTrue(hasattr(settings, "OOC_ROOM_DBREF"))
        self.assertTrue(hasattr(settings, "TELEPORT_MODE"))

    def test_posing_account_options_registered(self):
        for key in (
            "show_pose_headers",
            "pose_header_format",
            "pose_separator",
            "highlight_enabled",
            "highlight_self_color",
            "highlight_others_color",
        ):
            self.assertIn(key, settings.OPTIONS_ACCOUNT_DEFAULT)


# ---------------------------------------------------------------------------
# Regions + maps: the tile-overlay seam, end to end
# ---------------------------------------------------------------------------


class TestSeededMapWorld(EvenniaTest):
    """seed_sandbox builds a real, mapped world.

    Running the management command rather than hand-building rows: the seed is
    the only thing that ever exercises the derive-the-grid-from-exits path
    (place one origin tile, then layout.plan/apply_plan), and a broken
    direction alias in ROOM_LINKS is invisible until something walks it.
    """

    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        call_command("seed_sandbox", verbosity=0)

    def test_every_seeded_room_gets_a_tile(self):
        from evennia_maps.models import MapPlane, RoomTile
        from world.sandbox.management.commands.seed_sandbox import PLANE_NAME, ROOM_NAMES

        plane = MapPlane.objects.get(name=PLANE_NAME)
        tiles = RoomTile.objects.filter(plane=plane)
        self.assertEqual(tiles.count(), len(ROOM_NAMES))
        self.assertEqual(
            {tile.room_name for tile in tiles},
            set(ROOM_NAMES),
        )

    def test_the_grid_matches_the_exits_it_was_derived_from(self):
        # Only (0, 0) was written by hand; the other five positions come from
        # walking canonical-direction exit aliases. Asserting the shape here
        # is what makes an alias typo a failure rather than a missing tile
        # nobody notices.
        from evennia_maps.models import RoomTile

        by_name = {t.room_name: (t.x, t.y) for t in RoomTile.objects.all()}
        self.assertEqual(by_name["Sandbox Plaza"], (0, 0))
        self.assertEqual(by_name["The Archive"], (0, 1))
        self.assertEqual(by_name["The Overlook"], (0, 2))
        self.assertEqual(by_name["Consulate Hall"], (1, 0))
        self.assertEqual(by_name["Staff Lounge"], (0, -1))
        self.assertEqual(by_name["Garden Walk"], (-1, 0))

    def test_terrain_snapshot_follows_the_room_mixin(self):
        # MapsRoomMixin.set_terrain() -> terrain_changed -> tile snapshot,
        # resolved through MAPS_TERRAIN_PRECEDENCE. Proves the mixin is
        # actually in typeclasses.rooms.Room's MRO.
        from evennia_maps.models import RoomTile

        self.assertEqual(RoomTile.objects.get(room_name="Garden Walk").terrain, "forest")
        self.assertEqual(RoomTile.objects.get(room_name="The Overlook").terrain, "hills")

    def test_the_origin_tile_is_pinned(self):
        from evennia_maps.models import RoomTile

        self.assertTrue(RoomTile.objects.get(room_name="Sandbox Plaza").pinned)

    def test_seeding_twice_is_idempotent(self):
        # The purge half has to know about the plane, region and scenes now,
        # and MapPlane.name is unique — a purge that missed one would raise
        # here rather than quietly doubling the world.
        from evennia_maps.models import MapPlane, RoomTile
        from evennia_regions.models import RegionMembership
        from world.sandbox.management.commands.seed_sandbox import ROOM_NAMES

        call_command("seed_sandbox", verbosity=0)

        self.assertEqual(MapPlane.objects.count(), 1)
        self.assertEqual(RoomTile.objects.count(), len(ROOM_NAMES))
        self.assertEqual(RegionMembership.objects.count(), len(ROOM_NAMES))


class TestMapOverlaySeam(EvenniaTest):
    """All six overlay layers light up, from four different contribs.

    This is the end-to-end proof the extraction plan asks for: evennia_maps
    sends collect_tile_overlays once, and evennia_regions, evennia_scenes,
    evennia_lore and evennia_calendar each answer with their own keys, with no
    overlay configuration in settings.py at all.
    """

    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        call_command("seed_sandbox", verbosity=0)
        from evennia_maps.models import RoomTile

        self.tiles = list(RoomTile.objects.select_related("plane").all())
        self.plane = self.tiles[0].plane
        self.room_ids = [tile.room_id for tile in self.tiles]
        self.tile_by_name = {tile.room_name: tile for tile in self.tiles}

    def _overlays(self, *, staff=False):
        from evennia_maps.overlays import collect_overlays

        return collect_overlays(self.room_ids, staff=staff)

    def test_all_six_overlay_keys_are_answered(self):
        # The keys evennia_maps/overlays.py documents. A provider that failed
        # to connect degrades to an absent key rather than an error, which is
        # exactly why this has to be asserted somewhere.
        self.assertEqual(
            set(self._overlays()),
            {
                "primary_region",
                "has_active_scene",
                "recent_scene_count",
                "recent_scenes",
                "has_lore",
                "upcoming_events",
            },
        )

    def test_regions_names_every_tile(self):
        from world.sandbox.management.commands.seed_sandbox import REGION_NAME

        primary = self._overlays()["primary_region"]
        self.assertEqual(set(primary), set(self.room_ids))
        self.assertEqual(
            {entry["name"] for entry in primary.values()},
            {REGION_NAME},
        )

    def test_scenes_pin_the_live_room_and_heat_the_closed_one(self):
        overlays = self._overlays()
        hall = self.tile_by_name["Consulate Hall"].room_id
        archive = self.tile_by_name["The Archive"].room_id

        self.assertEqual(set(overlays["has_active_scene"]), {hall})
        self.assertEqual(overlays["recent_scene_count"], {archive: 1})
        self.assertEqual(len(overlays["recent_scenes"][archive]), 1)

    def test_lore_lights_the_whole_region(self):
        # has_lore is answered per room but decided per region: every seeded
        # room shares one primary region, and that region has public lore.
        self.assertEqual(set(self._overlays()["has_lore"]), set(self.room_ids))

    def test_calendar_reaches_a_room_through_the_scene(self):
        from world.sandbox.management.commands.seed_sandbox import CALENDAR_EVENT_TITLE

        hall = self.tile_by_name["Consulate Hall"].room_id
        events = self._overlays()["upcoming_events"]
        self.assertEqual(set(events), {hall})
        self.assertEqual(events[hall][0]["title"], CALENDAR_EVENT_TITLE)

    def test_the_collect_is_one_signal_not_one_per_tile(self):
        # The invariant the whole design rests on: overlay cost is flat in
        # tile count.
        #
        # The smaller set is the two rooms that carry data, not an arbitrary
        # slice: a couple of providers skip a follow-up query when nothing in
        # the request has anything to look up (scenes' log-label query is the
        # documented case — "three queries when no room in the request has a
        # recent log to label"). Comparing six rooms against a data-less one
        # would measure that, not room count.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from evennia_maps.overlays import collect_overlays

        with_data = [
            self.tile_by_name["The Archive"].room_id,
            self.tile_by_name["Consulate Hall"].room_id,
        ]
        with CaptureQueriesContext(connection) as ctx:
            collect_overlays(with_data, staff=False)
        few = len(ctx.captured_queries)
        with CaptureQueriesContext(connection) as ctx:
            collect_overlays(self.room_ids, staff=False)
        many = len(ctx.captured_queries)
        self.assertEqual(few, many)


class TestMapWebSurface(EvenniaTest):
    """The routes this game mounts, rendered and reversed for real.

    Both halves catch faults no contrib test can see. A contrib's own suite
    mounts a test URLconf containing that contrib alone, so it cannot show
    that *this* game mounted the routes, under the namespaces the templates
    and the overlay link table expect.
    """

    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        call_command("seed_sandbox", verbosity=0)
        self.factory = RequestFactory()

    def _render(self, view, path_, **kwargs):
        request = self.factory.get(path_)
        request.user = AnonymousUser()
        # Evennia's general_context processor reaches into request.session;
        # RequestFactory attaches none.
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        response = view(request, **kwargs)
        response.render()
        return response.content.decode()

    def test_outbound_link_table_resolves_every_role(self):
        # overlay_url_templates() drops any role whose route is not mounted,
        # so a missing include here shows up as a popup with no link rather
        # than an error. All three partners' pages are mounted in
        # web/website/urls.py precisely so this is non-empty.
        from evennia_maps.overlays import overlay_url_templates

        self.assertEqual(set(overlay_url_templates()), {"region", "scene", "event"})

    def test_live_map_finds_the_tile_feed(self):
        # Reverses MAPS_TILES_URL_NAME ("api-plane-tiles"); empty when the
        # API router is not mounted, in which case the live map renders an
        # explanatory notice instead of a blank canvas.
        from evennia_maps.views import tiles_url_template

        self.assertTrue(tiles_url_template())

    def test_svg_map_page_renders_with_its_overlays(self):
        from evennia_maps.models import MapPlane
        from evennia_maps.views import PlaneMapView
        from world.sandbox.management.commands.seed_sandbox import PLANE_NAME, REGION_NAME

        plane = MapPlane.objects.get(name=PLANE_NAME)
        html = self._render(PlaneMapView.as_view(), f"/map/{plane.pk}/", pk=plane.pk)
        self.assertIn("Sandbox Plaza", html)
        self.assertIn("The Overlook", html)
        # The region link is an overlay value turned into a URL — its presence
        # proves the collect ran and evennia_regions' route is mounted.
        self.assertIn(REGION_NAME, html)
        self.assertIn("/regions/", html)

    def test_both_api_routers_are_reachable_under_one_prefix(self):
        # web/urls.py mounts two DRF routers at the same "api/v1/" prefix.
        # Their route names do not collide, so both feeds resolve; only DRF's
        # own "api-root" is shared, and nothing reverses that.
        from django.urls import resolve, reverse

        self.assertEqual(reverse("api-plane-list"), "/api/v1/planes/")
        self.assertEqual(reverse("api-region-list"), "/api/v1/regions/")
        self.assertEqual(resolve("/api/v1/regions/").url_name, "api-region-list")

    def test_plane_list_page_renders(self):
        from evennia_maps.views import PlaneListView
        from world.sandbox.management.commands.seed_sandbox import PLANE_NAME

        html = self._render(PlaneListView.as_view(), "/map/")
        self.assertIn(PLANE_NAME, html)
        # Tile counts are staff-only — an anonymous visitor must not learn how
        # many rooms a plane holds that they are not being shown.
        self.assertNotIn("6 tiles", html)

    def test_live_map_page_carries_its_link_templates(self):
        # The Leaflet page builds popups client-side from these templates, so
        # a route this game failed to mount shows up as a popup entry with no
        # link rather than as an error anywhere.
        from evennia_maps.models import MapPlane
        from evennia_maps.views import PlaneLiveMapView
        from world.sandbox.management.commands.seed_sandbox import PLANE_NAME

        plane = MapPlane.objects.get(name=PLANE_NAME)
        html = self._render(PlaneLiveMapView.as_view(), f"/map/{plane.pk}/live/", pk=plane.pk)
        self.assertIn("/api/v1/planes/", html)
        self.assertIn("/regions/", html)
        self.assertIn("/scenes/", html)
        self.assertIn("/calendar/", html)

    def test_region_page_renders_its_member_rooms(self):
        from evennia_regions.models import Region
        from evennia_regions.views import RegionDetailView
        from world.sandbox.management.commands.seed_sandbox import REGION_NAME

        region = Region.objects.get(name=REGION_NAME)
        html = self._render(RegionDetailView.as_view(), f"/regions/{region.pk}/", pk=region.pk)
        self.assertIn(REGION_NAME, html)
        self.assertIn("Sandbox Plaza", html)
