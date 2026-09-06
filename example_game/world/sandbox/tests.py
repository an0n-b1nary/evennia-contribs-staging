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


class SeededSandboxMixin:
    """Run seed_sandbox with START_LOCATION pointed at a room that exists.

    In a live game START_LOCATION is "#2" - Limbo, which `evennia migrate`
    creates and nothing deletes. That is the whole reason the seeder re-dresses
    that room rather than making a hall whose dbref would drift (see
    seed_sandbox.py::_spawn_room). Evennia's test fixtures never run
    initial_setup, so in a test database #2 is whichever object the fixture
    happened to create second - quite possibly a Character, which has no
    set_terrain().

    Overriding the setting to room1 for the duration of each test lets the
    seeder take its real path here instead of some test-only fallback, and it
    leaves char1 standing in the Arrival Hall, which is what a real player
    sees on their first connect.
    """

    def setUp(self):
        super().setUp()
        origin = self.settings(START_LOCATION=f"#{self.room1.id}")
        origin.enable()
        self.addCleanup(origin.disable)
        call_command("seed_sandbox", verbosity=0)


def _search_room(key):
    from evennia.utils.search import search_object

    matches = search_object(key)
    assert matches, f"no room named {key!r}"
    return matches[0]


class TestSpawnPoints(SeededSandboxMixin, EvenniaTest):
    """A new character lands in the seeded world, not in stock Limbo.

    These pin the arrangement documented in settings.py's "Spawn points" block.
    They fail if someone repoints START_LOCATION at a room the seeder creates
    (whose dbref moves on every rebuild), or renames the OOC hub without
    updating OOC_ROOM_DBREF.
    """

    character_typeclass = Character
    room_typeclass = Room

    def test_spawn_settings_are_dbrefs(self):
        # Not cosmetic: ObjectDB.objects.get_id() accepts a dbref and nothing
        # else, so a room name here resolves to None and strands the character.
        self.assertTrue(settings.DEFAULT_HOME.startswith("#"))
        self.assertTrue(settings.START_LOCATION.startswith("#"))

    def test_start_location_resolves_to_the_arrival_hall(self):
        # The spawn room and the map origin are two different rooms now: a new
        # player lands in the OOC hub, which is deliberately unmapped, while
        # the grid is anchored on the IC entry room.
        from evennia.objects.models import ObjectDB

        from world.sandbox.management.commands.seed_sandbox import (
            OOC_ROOM_NAME,
            ORIGIN_ROOM_NAME,
        )

        room = ObjectDB.objects.get_id(settings.START_LOCATION)
        self.assertIsNotNone(room)
        self.assertEqual(room.key, OOC_ROOM_NAME)
        self.assertNotEqual(OOC_ROOM_NAME, ORIGIN_ROOM_NAME)

    def test_the_spawn_room_survives_a_reseed(self):
        # The point of the whole arrangement: reseeding must not move the room
        # the spawn settings name.
        from evennia.objects.models import ObjectDB

        from world.sandbox.management.commands.seed_sandbox import OOC_ROOM_NAME

        before = ObjectDB.objects.get_id(settings.START_LOCATION).id
        call_command("seed_sandbox", verbosity=0)
        after = ObjectDB.objects.get_id(settings.START_LOCATION)
        self.assertIsNotNone(after)
        self.assertEqual(before, after.id)
        self.assertEqual(after.key, OOC_ROOM_NAME)

    def test_the_drafting_room_survives_a_reseed(self):
        # It is the one other room the purge spares, and for a reason a test
        # should hold onto: rooms a playtester digs hang off it, so deleting it
        # would cascade their exits away and orphan everything they built.
        from evennia_maps.models import RoomTile

        drafting = _search_room("Drafting Room")
        before = drafting.id
        before_tile = RoomTile.objects.get(room_id=before).id

        call_command("seed_sandbox", verbosity=0)

        after = _search_room("Drafting Room")
        self.assertEqual(before, after.id)
        # And its scratch-plane tile with it - the tile is what a dug room is
        # positioned relative to.
        self.assertEqual(RoomTile.objects.get(room_id=after.id).id, before_tile)

    def test_ooc_room_setting_resolves_by_name(self):
        # OOC_ROOM_DBREF holds a *name*; evennia_social resolves it with
        # search_object(), which is what lets the hub be recreated each seed.
        from evennia_social.commands.navigation import _resolve_ooc_room
        from world.sandbox.management.commands.seed_sandbox import OOC_ROOM_NAME

        room = _resolve_ooc_room()
        self.assertIsNotNone(room)
        self.assertEqual(room.key, OOC_ROOM_NAME)

    def test_the_hub_reaches_the_ic_world_but_is_not_on_the_map(self):
        # The single boundary between the two halves, and it carries no
        # direction alias, so layout.plan() never walks from the IC grid back
        # into the wing: reachable on foot, absent from the grid.
        from evennia_maps.models import RoomTile
        from world.sandbox.management.commands.seed_sandbox import (
            OOC_ROOM_NAME,
            ORIGIN_ROOM_NAME,
        )

        hub = _search_room(OOC_ROOM_NAME)
        plaza = _search_room(ORIGIN_ROOM_NAME)
        self.assertIn(plaza, [ex.destination for ex in hub.exits])
        self.assertIn(hub, [ex.destination for ex in plaza.exits])
        self.assertFalse(RoomTile.objects.filter(room=hub).exists())

    def test_every_spoke_hangs_off_the_hub_with_no_direction(self):
        # Hub-and-spoke, so two moves reaches anything - and every one of those
        # exits is direction-less, which is what keeps the whole wing outside
        # the reach of layout.plan() independently of the room-type guard.
        from evennia_maps.direction import resolve as resolve_direction
        from world.sandbox import content
        from world.sandbox.management.commands.seed_sandbox import OOC_ROOM_NAME

        hub = _search_room(OOC_ROOM_NAME)
        destinations = {ex.destination.db.sandbox_slug for ex in hub.exits}
        self.assertTrue(set(content.OOC_SPOKE_SLUGS).issubset(destinations))
        for ex in hub.exits:
            self.assertIsNone(resolve_direction(ex), f"{ex.key} resolves to a direction")

    def test_a_directional_exit_into_an_ooc_room_still_does_not_map_it(self):
        # The flavor-exit trick above is a *convention*: it keeps the hub off
        # the grid only for as long as nobody digs a directional exit to it.
        # MAPS_UNMAPPABLE_ROOM_TYPES is what makes it a rule, and this is the
        # case that tells the two apart - the exit here carries a canonical
        # direction from a mapped room, which is precisely the input the
        # auto-placement listener exists to act on.
        from evennia.utils import create

        from evennia_maps.models import RoomTile
        from world.sandbox.management.commands.seed_sandbox import (
            OOC_ROOM_NAME,
            ORIGIN_ROOM_NAME,
        )

        hub = _search_room(OOC_ROOM_NAME)
        plaza = _search_room(ORIGIN_ROOM_NAME)
        self.assertEqual(hub.room_type, "ooc")
        self.assertTrue(RoomTile.objects.filter(room=plaza).exists())

        create.create_object("typeclasses.exits.Exit", key="north", location=plaza, destination=hub)
        self.assertFalse(RoomTile.objects.filter(room=hub).exists())

    def test_no_ooc_room_reaches_the_ic_grid(self):
        # The invariant the setting buys, asserted across the whole seed rather
        # than on the one room we happen to remember.
        #
        # Scoped to the *overworld* plane, because there is exactly one
        # deliberate exception and it lives on another one: the Drafting Room
        # holds a pinned tile on the scratch plane, since the auto-placement
        # listener only fires when the room being dug *from* is already mapped.
        # An unmapped drafting room would make `@dig north=X` a silent no-op,
        # which is the trap that room exists to teach around. The exception is
        # allowed because MAPS_UNMAPPABLE_ROOM_TYPES guards the listener, not
        # the explicit write path the seeder uses.
        from evennia_maps.models import RoomTile
        from world.sandbox import content

        mapped_ooc = [
            tile.room_name
            for tile in RoomTile.objects.select_related("plane").filter(
                plane__name=content.PLANE_NAME
            )
            if getattr(tile.room, "room_type", None) == "ooc"
        ]
        self.assertEqual(mapped_ooc, [])

    def test_the_drafting_room_is_the_only_ooc_tile_anywhere(self):
        # Pins the exception itself, so a second one cannot appear without
        # somebody deciding to change this line.
        from evennia_maps.models import RoomTile

        mapped_ooc = {
            tile.room_name
            for tile in RoomTile.objects.select_related("plane")
            if getattr(tile.room, "room_type", None) == "ooc"
        }
        self.assertEqual(mapped_ooc, {"Drafting Room"})


class TestSeededMapWorld(SeededSandboxMixin, EvenniaTest):
    """seed_sandbox builds a real, mapped world.

    Running the management command rather than hand-building rows: the seed is
    the only thing that ever exercises the derive-the-grid-from-exits path
    (place one origin tile, then layout.plan/apply_plan), and a broken
    direction alias in ROOM_LINKS is invisible until something walks it.
    """

    character_typeclass = Character
    room_typeclass = Room

    def test_every_mapped_room_gets_a_tile(self):
        # Across all three IC planes, not one: the surface, the undercroft
        # under it and the standalone interior are placed by three different
        # mechanisms (a derived walk, the vertical step inside that same walk,
        # and a second walk from its own anchor), and counting only the
        # surface would leave two of the three untested.
        from evennia_maps.models import RoomTile
        from world.sandbox.management.commands.seed_sandbox import (
            MAPPED_ROOM_NAMES,
            PLANE_NAMES,
        )

        tiles = RoomTile.objects.filter(plane__name__in=PLANE_NAMES)
        self.assertEqual(tiles.count(), len(MAPPED_ROOM_NAMES))
        self.assertEqual(
            {tile.room_name for tile in tiles},
            set(MAPPED_ROOM_NAMES),
        )

    def test_the_three_ic_planes_have_the_geometry_they_claim(self):
        # zstack and elevation are not decoration. Two planes sharing a
        # non-blank zstack is the entire condition for Leaflet drawing a
        # base-layer control, and a blank zstack is the entire definition of
        # a plane reached by portal rather than by walking.
        from evennia_maps.models import MapPlane
        from world.sandbox import content

        by_name = {p.name: p for p in MapPlane.objects.all()}
        for name, zstack, elevation, _desc in content.IC_PLANES:
            with self.subTest(plane=name):
                self.assertEqual(by_name[name].zstack, zstack)
                self.assertEqual(by_name[name].elevation, elevation)
        # Said as a property rather than left implicit in the table above.
        stacked = [p for p in by_name.values() if p.zstack == content.ZSTACK]
        self.assertEqual(len(stacked), 2)

    def test_the_undercroft_is_derived_by_walking_down(self):
        # No coordinate is written for any undercroft room. A `down` exit is
        # a vertical direction, so the same walk that lays out the surface
        # crosses into the adjacent elevation at the same (x, y) - which is
        # why the Cistern lands under the Plaza and not merely somewhere.
        from evennia_maps.models import RoomTile
        from world.sandbox import content

        cistern = RoomTile.objects.get(room_name="The Cistern")
        plaza = RoomTile.objects.get(room_name="Sandbox Plaza")
        self.assertEqual(cistern.plane.name, content.UNDERCROFT_PLANE_NAME)
        self.assertEqual((cistern.x, cistern.y), (plaza.x, plaza.y))

    def test_the_interior_is_its_own_walk_on_a_standalone_plane(self):
        from evennia_maps.models import RoomTile
        from world.sandbox import content

        lobby = RoomTile.objects.get(room_name="Consulate Lobby")
        gallery = RoomTile.objects.get(room_name="The Gallery")
        self.assertEqual(lobby.plane.name, content.INTERIOR_PLANE_NAME)
        self.assertEqual((lobby.x, lobby.y), (0, 0))
        self.assertTrue(lobby.pinned)
        # Derived from the lobby by the same walk machinery, one plane over.
        self.assertEqual((gallery.x, gallery.y), (0, 1))

    def test_the_grid_matches_the_exits_it_was_derived_from(self):
        # Only two coordinates in the whole IC world are written by hand, and
        # both are origins. Every position below comes from walking canonical
        # direction aliases out from the plaza. Asserting the shape here is
        # what makes an alias typo a failure rather than a missing tile
        # nobody notices.
        from evennia_maps.models import RoomTile
        from world.sandbox import content

        by_name = {
            t.room_name: (t.x, t.y) for t in RoomTile.objects.filter(plane__name=content.PLANE_NAME)
        }
        self.assertEqual(
            by_name,
            {
                "Sandbox Plaza": (0, 0),
                "The Archive": (0, 1),
                "The Overlook": (0, 2),
                "Consulate Hall": (1, 0),
                "Market Row": (1, 1),
                "Garden Walk": (-1, 0),
                "The Warren": (-1, 1),
                "Harbor Steps": (0, -1),
                "The Causeway": (1, -1),
            },
        )

    def test_terrain_snapshot_follows_the_room_mixin(self):
        # MapsRoomMixin.set_terrain() -> terrain_changed -> tile snapshot,
        # resolved through MAPS_TERRAIN_PRECEDENCE. Proves the mixin is
        # actually in typeclasses.rooms.Room's MRO.
        from evennia_maps.models import RoomTile

        self.assertEqual(RoomTile.objects.get(room_name="Garden Walk").terrain, "forest")
        self.assertEqual(RoomTile.objects.get(room_name="The Overlook").terrain, "hills")

    def test_two_terrain_tags_resolve_to_one_by_precedence(self):
        # Harbor Steps carries both "water" and "urban". The precedence list
        # exists to turn a set into one deterministic answer, and this is the
        # only seeded room that makes it do any work.
        from evennia_maps.models import RoomTile

        room = RoomTile.objects.get(room_name="Harbor Steps").room
        self.assertEqual(set(room.terrain_tags), {"water", "urban"})
        self.assertEqual(RoomTile.objects.get(room_name="Harbor Steps").terrain, "water")

    def test_a_valid_terrain_can_still_have_no_sprite(self):
        # Two different absences that look identical on a rendered grid unless
        # you know to tell them apart, so they are asserted apart here:
        #
        #   The Causeway has a terrain ("scrub") with no entry in
        #   MAPS_TERRAIN_TILESET, so the tile draws the fallback swatch.
        #   The Warren has no terrain at all, which is what +map/check lints.
        from evennia_maps.models import RoomTile
        from evennia_maps.views import tile_sprite

        causeway = RoomTile.objects.get(room_name="The Causeway")
        self.assertEqual(causeway.terrain, "scrub")
        self.assertEqual(tile_sprite(causeway.terrain), "")

        warren = RoomTile.objects.get(room_name="The Warren")
        self.assertEqual(warren.terrain, "")

    def test_every_sprited_terrain_has_a_file_on_disk(self):
        # The tileset names URLs under /static/, and a typo there is a broken
        # image on the live map that no view test would notice: tile_sprite()
        # happily returns a URL to nothing.
        from pathlib import Path

        from django.conf import settings

        static_dir = Path(settings.STATICFILES_DIRS[0])
        for terrain, url in settings.MAPS_TERRAIN_TILESET.items():
            with self.subTest(terrain=terrain):
                self.assertTrue(url.startswith("/static/"))
                self.assertTrue((static_dir / url[len("/static/") :]).is_file())

    def test_hangout_types_differ_across_rooms(self):
        # The one overlay with no table behind it: evennia_maps reads the bare
        # attribute duck-typed. Three distinct values, because a layer where
        # every marker is the same letter proves only that the layer draws.
        from evennia_maps.models import RoomTile
        from evennia_maps.views import tile_hangout_type
        from world.sandbox import content

        found = {
            tile.room_name: tile_hangout_type(tile.room)
            for tile in RoomTile.objects.filter(plane__name=content.PLANE_NAME)
        }
        named = {name: value for name, value in found.items() if value}
        self.assertEqual(len(named), len(content.HANGOUTS))
        self.assertEqual(len(set(named.values())), len(content.HANGOUTS))

        from evennia_social import HANGOUT_TYPES

        for name, value in named.items():
            with self.subTest(room=name):
                self.assertIn(value, HANGOUT_TYPES)

    def test_the_portal_is_inferred_from_geometry_alone(self):
        # There is no portal flag anywhere. Consulate Hall gets a portal
        # marker purely because one of its exits lands on a plane whose zstack
        # is blank - and the plain "doors" exit that does it carries no
        # direction alias, so the walk that laid out the surface never
        # followed it.
        from evennia_maps.api.views import portal_target_planes_by_room
        from evennia_maps.models import MapPlane, RoomTile
        from world.sandbox import content

        interior = MapPlane.objects.get(name=content.INTERIOR_PLANE_NAME)
        surface = MapPlane.objects.get(name=content.PLANE_NAME)
        tiles = RoomTile.objects.filter(plane=surface)
        portals = portal_target_planes_by_room(
            [tile.room_id for tile in tiles], exclude_plane_id=surface.pk, staff=True
        )
        hall = RoomTile.objects.get(room_name="Consulate Hall").room_id
        self.assertEqual(portals, {hall: interior.pk})

    def test_the_origin_tile_is_pinned(self):
        from evennia_maps.models import RoomTile

        self.assertTrue(RoomTile.objects.get(room_name="Sandbox Plaza").pinned)

    def test_a_reachable_room_is_deliberately_left_off_the_map(self):
        # +map/check's unmapped-neighbour lint needs something to lint. The
        # Study is reached from the Lobby by a canonical `east` exit and still
        # has no tile, which is the ordinary state of a room dug before
        # anybody drew a map.
        from evennia_maps.models import RoomTile
        from world.sandbox import content

        for slug in content.UNMAPPED_SLUGS:
            spec = content.IC_ROOMS_BY_SLUG[slug]
            with self.subTest(room=spec.name):
                self.assertFalse(RoomTile.objects.filter(room_name=spec.name).exists())

    def test_the_unmapped_room_is_reachable_by_a_direction_from_a_mapped_one(self):
        # The lint's precondition, which is the half this game owns. Whether
        # +map/check phrases it correctly is evennia_maps' own test; whether
        # the seeded world gives it anything to find is this one. A flavor
        # exit here would leave the lint permanently silent.
        from evennia_maps.direction import resolve
        from evennia_maps.models import RoomTile
        from world.sandbox import content

        for slug in content.UNMAPPED_SLUGS:
            target = content.IC_ROOMS_BY_SLUG[slug].name
            with self.subTest(room=target):
                reached_from_mapped = [
                    exit_obj
                    for tile in RoomTile.objects.all()
                    for exit_obj in tile.room.exits
                    if exit_obj.destination.key == target and resolve(exit_obj) is not None
                ]
                self.assertTrue(reached_from_mapped)

    def test_the_undercroft_reflow_reports_a_two_step_blocked_cascade(self):
        # The whole reason MISPLACED_TILES exists. A reflow of a map that has
        # been hand-edited must report rather than silently rearrange, and the
        # interesting half is the *second* step: the Vault looks safe to move
        # until you know the Tunnel that holds its target cannot vacate.
        from evennia_maps import layout
        from evennia_maps.models import RoomTile

        plan = layout.plan(RoomTile.objects.get(room_name="The Cistern").room)
        blocked = {entry.room.key: entry.reason for entry in plan.blocked}

        self.assertEqual(blocked.get("Service Tunnel"), layout.BLOCKED_BY_PINNED)
        self.assertEqual(blocked.get("The Vault"), layout.BLOCKED_BY_BLOCKED)
        # The pinned squatter is skipped, not blocked - a different outcome
        # with a different list, and conflating them would hide the cascade.
        self.assertIn("The Sump", {room.key for room, _p, _x, _y in plan.pinned_skips})

    def test_the_squatting_tile_is_pinned_so_the_cascade_is_stable(self):
        # If the Sump were not pinned it would simply move and the whole
        # cascade above would evaporate on the first reflow.
        from evennia_maps.models import RoomTile
        from world.sandbox import content

        for slug, x, y, pinned in content.MISPLACED_TILES:
            spec = content.IC_ROOMS_BY_SLUG[slug]
            with self.subTest(room=spec.name):
                tile = RoomTile.objects.get(room_name=spec.name)
                self.assertEqual((tile.x, tile.y), (x, y))
                self.assertEqual(tile.pinned, pinned)

    def test_seeding_twice_is_idempotent(self):
        # The purge half has to know about the plane, region and scenes, and
        # MapPlane.name is unique — a purge that missed one would raise here
        # rather than quietly doubling the world.
        #
        # Four planes: the three IC ones are purged and rebuilt, the scratch
        # plane is get_or_create-d and deliberately survives. That last one is
        # the case a count of three would have caught as a bug and a count of
        # four asserts as the design.
        #
        # Region membership is counted through all_objects because one of the
        # three regions is archived on purpose - the default manager would
        # hide it, and a purge that missed an archived region would collide on
        # the unique name on the very next run rather than here.
        from evennia_maps.models import MapPlane, RoomTile
        from evennia_regions.models import Region, RegionMembership
        from world.sandbox import content
        from world.sandbox.management.commands.seed_sandbox import (
            MAPPED_ROOM_NAMES,
            PLANE_NAMES,
        )

        expected_memberships = sum(
            1 + len(secondary) for _primary, secondary in content.IC_REGION_MEMBERSHIPS.values()
        )

        call_command("seed_sandbox", verbosity=0)

        self.assertEqual(
            set(MapPlane.all_objects.values_list("name", flat=True)),
            {*PLANE_NAMES, content.DRAFTING_PLANE_NAME},
        )
        self.assertEqual(
            RoomTile.objects.filter(plane__name__in=PLANE_NAMES).count(),
            len(MAPPED_ROOM_NAMES),
        )
        self.assertEqual(
            RoomTile.objects.filter(plane__name=content.DRAFTING_PLANE_NAME).count(), 1
        )
        self.assertEqual(Region.all_objects.count(), len(content.REGIONS))
        self.assertEqual(RegionMembership.objects.count(), expected_memberships)


class TestMapOverlaySeam(SeededSandboxMixin, EvenniaTest):
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
        from evennia_maps.models import RoomTile

        # The overworld plane only. The scratch plane the Drafting Room sits
        # on carries no region membership, no lore and no scenes by design, so
        # including it would make every "every tile is answered" assertion
        # below fail for a room that was never meant to be in the IC world.
        from world.sandbox import content

        self.tiles = list(
            RoomTile.objects.select_related("plane").filter(plane__name=content.PLANE_NAME)
        )
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
        from world.sandbox import content

        primary = self._overlays()["primary_region"]
        self.assertEqual(set(primary), set(self.room_ids))
        # Two of the three regions on the surface, not one: an overlay whose
        # every value is identical cannot distinguish "resolved correctly"
        # from "hardcoded".
        visible = {
            content.REGIONS_BY_SLUG["commons"]["name"],
            content.REGIONS_BY_SLUG["waterfront"]["name"],
        }
        self.assertEqual({entry["name"] for entry in primary.values()}, visible)

    def test_a_room_can_hold_a_primary_and_a_secondary_membership(self):
        from evennia_regions.models import RegionMembership
        from world.sandbox import content

        room_id = self.tile_by_name["Market Row"].room_id
        memberships = {
            m.region.name: m.is_primary
            for m in RegionMembership.objects.select_related("region").filter(room_id=room_id)
        }
        self.assertEqual(
            memberships,
            {
                content.REGIONS_BY_SLUG["commons"]["name"]: True,
                content.REGIONS_BY_SLUG["waterfront"]["name"]: False,
            },
        )
        # One deterministic answer on the tile despite two memberships.
        self.assertEqual(
            self._overlays()["primary_region"][room_id]["name"],
            content.REGIONS_BY_SLUG["commons"]["name"],
        )

    def test_an_archived_primary_region_falls_through_to_a_visible_one(self):
        # The undercroft rooms' *flagged* primary is the archived Undercity.
        # primary_for() still answers with it; the map's overlay deliberately
        # diverges and skips archived regions, because the tile label is a
        # link and RegionDetailView resolves through Region.objects - so
        # honouring the flag here would render a link straight to a 404.
        from evennia_maps.models import RoomTile
        from evennia_maps.overlays import collect_overlays
        from evennia_regions.models import RegionMembership
        from world.sandbox import content

        cistern = RoomTile.objects.get(room_name="The Cistern")
        flagged = RegionMembership.objects.get(room_id=cistern.room_id, is_primary=True)
        self.assertEqual(flagged.region.name, content.REGIONS_BY_SLUG["undercity"]["name"])
        self.assertTrue(flagged.region.is_archived)

        overlays = collect_overlays([cistern.room_id], staff=False)
        self.assertEqual(
            overlays["primary_region"][cistern.room_id]["name"],
            content.REGIONS_BY_SLUG["waterfront"]["name"],
        )

    def test_scenes_pin_the_live_room_and_heat_the_closed_ones(self):
        # The heatmap radius is min(4 + 2n, 16), so an even distribution shows
        # only that the layer draws. Three against one is what makes the
        # difference visible, and asserting the exact counts is what stops a
        # later edit flattening it back out without anyone noticing.
        overlays = self._overlays()
        hall = self.tile_by_name["Consulate Hall"].room_id
        archive = self.tile_by_name["The Archive"].room_id
        market = self.tile_by_name["Market Row"].room_id

        self.assertEqual(set(overlays["has_active_scene"]), {hall})
        self.assertEqual(overlays["recent_scene_count"], {archive: 3, market: 1})
        self.assertEqual(len(overlays["recent_scenes"][archive]), 3)
        self.assertGreater(
            overlays["recent_scene_count"][archive], overlays["recent_scene_count"][market]
        )

    def test_lore_lights_one_region_and_not_the_others(self):
        # has_lore is answered per room but decided per region. Lore is
        # attached to the Commons alone, so the Waterfront rooms stay dark -
        # an overlay that is true everywhere is indistinguishable from one
        # that is broken.
        from world.sandbox import content

        lit = set(self._overlays()["has_lore"])
        commons = {
            self.tile_by_name[content.IC_ROOMS_BY_SLUG[slug].name].room_id
            for slug, (primary, _secondary) in content.IC_REGION_MEMBERSHIPS.items()
            if primary == content.LORE_REGION_SLUG
            and content.IC_ROOMS_BY_SLUG[slug].name in self.tile_by_name
        }
        self.assertEqual(lit, commons)
        self.assertTrue(set(self.room_ids) - lit)

    def test_calendar_reaches_a_room_through_the_scene(self):
        from world.sandbox import content

        hall = self.tile_by_name["Consulate Hall"].room_id
        events = self._overlays()["upcoming_events"]
        self.assertEqual(set(events), {hall})
        self.assertEqual(
            events[hall][0]["title"], content.CALENDAR_EVENTS_BY_SLUG["kickoff"]["title"]
        )

    def test_a_staff_only_event_is_withheld_from_players(self):
        # is_staff_event exists to stop staff-run events being
        # visible-but-unjoinable, and a map pin advertising one would undo
        # that. This is the pair a playtester watches change when they run
        # +sandbox/builder on.
        from world.sandbox import content

        market = self.tile_by_name["Market Row"].room_id
        briefing = content.CALENDAR_EVENTS_BY_SLUG["briefing"]["title"]

        as_player = self._overlays(staff=False)["upcoming_events"]
        self.assertNotIn(market, as_player)

        as_staff = self._overlays(staff=True)["upcoming_events"]
        self.assertEqual([e["title"] for e in as_staff[market]], [briefing])

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


class TestMapWebSurface(SeededSandboxMixin, EvenniaTest):
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
        from world.sandbox import content

        plane = MapPlane.objects.get(name=content.PLANE_NAME)
        html = self._render(PlaneMapView.as_view(), f"/map/{plane.pk}/", pk=plane.pk)
        self.assertIn("Sandbox Plaza", html)
        self.assertIn("The Overlook", html)
        # The region link is an overlay value turned into a URL - its presence
        # proves the collect ran and evennia_regions' route is mounted.
        self.assertIn(content.REGIONS_BY_SLUG["commons"]["name"], html)
        self.assertIn("/regions/", html)
        # A sprite URL from MAPS_TERRAIN_TILESET, which only reaches the page
        # through tile_sprite() resolving a real terrain snapshot.
        self.assertIn("/static/sandbox/terrain/", html)

    def test_the_staff_room_is_withheld_from_an_anonymous_visitor(self):
        # The most direct demonstration of the fail-closed visibility rule
        # there is, because what changes is whether a room exists at all as
        # far as the page is concerned. Unlike the OOC wing, the Warren *is*
        # placed on the grid - it is the read side that withholds it.
        from evennia_maps.models import MapPlane, RoomTile
        from evennia_maps.views import PlaneMapView
        from world.sandbox import content

        warren = content.IC_ROOMS_BY_SLUG[content.STAFF_ROOM_SLUG]
        self.assertTrue(RoomTile.objects.filter(room_name=warren.name).exists())

        plane = MapPlane.objects.get(name=content.PLANE_NAME)
        html = self._render(PlaneMapView.as_view(), f"/map/{plane.pk}/", pk=plane.pk)
        self.assertNotIn(warren.name, html)

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
        from world.sandbox import content

        name = content.REGIONS_BY_SLUG["commons"]["name"]
        region = Region.objects.get(name=name)
        html = self._render(RegionDetailView.as_view(), f"/regions/{region.pk}/", pk=region.pk)
        self.assertIn(name, html)
        self.assertIn("Sandbox Plaza", html)
        # The staff room is a member and is still withheld: the region page
        # applies the same visibility rule the map does, which is the point of
        # having it in one place rather than per-view.
        self.assertNotIn(content.IC_ROOMS_BY_SLUG[content.STAFF_ROOM_SLUG].name, html)


class TestEveryWebSurfaceIsMounted(SeededSandboxMixin, EvenniaTest):
    """All nine contrib web surfaces resolve, and their landing pages render.

    This is the check the wiring rule exists for. Each contrib already renders
    its own pages in its own suite, against a test URLconf that mounts that
    contrib alone. What no contrib suite can show is that *this* game mounted
    the routes, at the right prefix, under the right namespace - and namespace
    is the part that differs per contrib for real reasons (see
    web/website/urls.py). A wrong choice there is a NoReverseMatch on a page
    nobody visits until a playtester does.

    Anonymous, because that is who arrives from a link.
    """

    character_typeclass = Character
    room_typeclass = Room

    # (reverse name, the URL prefix it must land under). Names carry a
    # namespace exactly where web/website/urls.py supplies one; the bare ones
    # are bare on purpose and would break if wrapped.
    LANDING_ROUTES = (
        ("evennia_maps:plane-list", "/map/"),
        ("evennia_regions:region-list", "/regions/"),
        ("evennia_calendar:calendar-list", "/calendar/"),
        ("evennia_plots:plot-list", "/plots/"),
        ("evennia_scenes:scene-list", "/scenes/"),
        ("evennia_boards:board-list", "/boards/"),
        ("lore-list", "/lore/"),
        ("job-list", "/jobs/"),
        ("xp-summary", "/xp/"),
    )

    def test_every_landing_route_reverses_under_its_prefix(self):
        from django.urls import reverse

        for name, prefix in self.LANDING_ROUTES:
            with self.subTest(route=name):
                self.assertTrue(reverse(name).startswith(prefix))

    def test_every_landing_page_responds(self):
        # Through the test client rather than a RequestFactory: the client
        # resolves the URL itself, so a route that reverses but is mounted
        # under a URLconf this game does not actually use still fails here.
        #
        # A redirect counts as mounted. Several of these surfaces send an
        # anonymous visitor to the login page, which is the contrib deciding
        # who may read it - not this game failing to wire it up.
        from django.urls import reverse

        for name, _prefix in self.LANDING_ROUTES:
            with self.subTest(route=name):
                response = self.client.get(reverse(name))
                self.assertIn(response.status_code, (200, 302))


class TestNavCoversEveryWebSurface(EvenniaTest):
    """The navbar reaches every surface this game mounts, and cannot 500 the site.

    TestEveryWebSurfaceIsMounted proves the nine contrib routes are wired. That
    is necessary and not sufficient: for most of this game's life all nine were
    mounted and none appeared in the menu, so a playtester had to type URLs. This
    class is the other half - what is mounted is reachable by clicking.

    The coverage test reads LANDING_ROUTES off that class rather than restating
    the list, so mounting a tenth contrib without adding it to the menu fails
    here instead of shipping an invisible page.
    """

    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _request(self, path="/", user=None):
        request = self.factory.get(path)
        request.user = user if user is not None else AnonymousUser()
        return request

    def test_every_landing_route_is_reachable_from_the_nav(self):
        from web.website.nav import ACCOUNT_LINKS, NAV_GROUPS

        in_menu = {name for _label, table in NAV_GROUPS for _lbl, name, _gate in table}
        in_menu |= {name for _label, name, _gate in ACCOUNT_LINKS}

        for name, _prefix in TestEveryWebSurfaceIsMounted.LANDING_ROUTES:
            with self.subTest(route=name):
                self.assertIn(name, in_menu)

    def test_nav_drops_unresolvable_routes(self):
        """A route that does not reverse costs one entry, not the whole site.

        This is the contract the menu exists for: it is included from base.html,
        so a NoReverseMatch here would be a 500 on every page. Same behaviour as
        evennia_maps.overlays.overlay_url_templates().
        """
        from web.website import nav

        broken = (("Setting", (("Nowhere", "no-such-route-name", nav.PUBLIC),)),)
        with mock.patch.object(nav, "NAV_GROUPS", broken):
            menu = nav.build_menu(self._request())

        self.assertEqual(menu["groups"], [])

    def test_nav_hides_gated_entries_from_anonymous(self):
        from web.website.nav import build_menu

        menu = build_menu(self._request())
        labels = [item["label"] for group in menu["groups"] for item in group["items"]]

        self.assertIn("Map", labels)
        self.assertIn("Lore", labels)
        self.assertEqual(menu["account"]["personal"], [])
        self.assertEqual(menu["account"]["staff"], [])

    def test_nav_shows_personal_but_not_staff_entries_to_a_player(self):
        from web.website.nav import build_menu

        self.account.is_staff = False
        menu = build_menu(self._request(user=self.account))

        self.assertEqual(
            [item["label"] for item in menu["account"]["personal"]],
            ["My XP", "My Tickets", "My Lore"],
        )
        self.assertEqual(menu["account"]["staff"], [])

    def test_nav_shows_staff_entries_to_staff(self):
        from web.website.nav import build_menu

        self.account.is_staff = True
        menu = build_menu(self._request(user=self.account))

        self.assertEqual(
            [item["label"] for item in menu["account"]["staff"]],
            ["Lore Queue", "All Jobs", "Plot Arcs"],
        )

    def test_nav_marks_the_active_group(self):
        from web.website.nav import build_menu

        menu = build_menu(self._request(path="/scenes/"))
        active = [group["label"] for group in menu["groups"] if group["active"]]

        self.assertEqual(active, ["Events"])

    def test_a_detail_page_activates_its_section(self):
        """Prefix matching, so /scenes/12/ lights up Scenes and not just /scenes/."""
        from web.website.nav import build_menu

        menu = build_menu(self._request(path="/scenes/12/"))
        active = [
            item["label"] for group in menu["groups"] for item in group["items"] if item["active"]
        ]

        self.assertEqual(active, ["Scenes"])

    def test_longest_prefix_wins_across_menus(self):
        """/lore/mine/ activates "My Lore" only - not "Lore" as well.

        Both /lore/ and /lore/mine/ prefix-match the path, which is why the
        active entry is chosen across the whole menu at once rather than
        per-list.
        """
        from web.website.nav import build_menu

        self.account.is_staff = False
        menu = build_menu(self._request(path="/lore/mine/", user=self.account))

        active = [
            item["label"] for group in menu["groups"] for item in group["items"] if item["active"]
        ]
        active += [item["label"] for item in menu["account"]["personal"] if item["active"]]

        self.assertEqual(active, ["My Lore"])


class TestBaseTemplateOverride(SeededSandboxMixin, EvenniaTest):
    """The two assets this game's base.html override brings back to life.

    Both were shipped-but-inert before it existed, and neither is visible to any
    contrib's own suite: a contrib renders against a test URLconf with stock
    base.html, where its breadcrumb block simply has nowhere to go.
    """

    character_typeclass = Character
    room_typeclass = Room

    def test_breadcrumbs_render_on_a_contrib_page(self):
        """46 contrib templates define {% block breadcrumbs %}; stock base.html has none."""
        from django.urls import reverse

        response = self.client.get(reverse("evennia_scenes:scene-list"))

        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-label="Breadcrumb"', response.content.decode())

    def test_accessibility_stylesheet_is_linked(self):
        """evennia_accessibility ships this CSS; nothing referenced it before."""
        from django.urls import reverse

        response = self.client.get(reverse("evennia_scenes:scene-list"))

        self.assertIn("evennia_accessibility/css/accessibility.css", response.content.decode())

    def test_the_grouped_menu_renders(self):
        from django.urls import reverse

        html = self.client.get(reverse("evennia_scenes:scene-list")).content.decode()

        for label in ("Setting", "Events", "Community"):
            with self.subTest(group=label):
                self.assertIn(f">{label}</a>", html)


class TestSandboxIndex(SeededSandboxMixin, EvenniaTest):
    """The home page: it renders, it stays correct when empty, and it does not leak.

    Anonymous throughout, because that is who arrives from a link - and because
    the leak cases only mean anything for a viewer with no permissions at all.
    """

    character_typeclass = Character
    room_typeclass = Room

    def _index(self):
        from django.urls import reverse

        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_index_renders_every_widget(self):
        html = self._index()

        for heading in (
            "Happening Now",
            "Upcoming Events",
            "The Map",
            "Recent Activity",
            "Systems on this sandbox",
        ):
            with self.subTest(widget=heading):
                self.assertIn(heading, html)

    def test_index_does_not_leak_a_view_private_scene(self):
        """The fail-closed case. VIEW_PRIVATE is outside WEB_READABLE_PRIVACY.

        Both a running scene (Happening Now) and a closed one (Recent Activity)
        are seeded, because the two widgets reach the model by different paths
        and only one of them copies SceneListView.
        """
        from django.utils import timezone
        from evennia_scenes.models import Scene

        Scene.objects.create(
            title="Secret Conclave",
            status=Scene.Status.ACTIVE,
            privacy=Scene.Privacy.VIEW_PRIVATE,
            room=self.room1,
            room_name=self.room1.key,
            started_at=timezone.now(),
        )
        Scene.objects.create(
            title="Secret Aftermath",
            status=Scene.Status.CLOSED,
            privacy=Scene.Privacy.VIEW_PRIVATE,
            room=self.room1,
            room_name=self.room1.key,
            started_at=timezone.now(),
            ended_at=timezone.now(),
        )

        html = self._index()

        self.assertNotIn("Secret Conclave", html)
        self.assertNotIn("Secret Aftermath", html)

    def test_index_shows_a_public_scene(self):
        """The other half of the previous test: the filter is not simply hiding everything."""
        from django.utils import timezone
        from evennia_scenes.models import Scene

        Scene.objects.create(
            title="Open Market Day",
            status=Scene.Status.ACTIVE,
            privacy=Scene.Privacy.PUBLIC,
            room=self.room1,
            room_name=self.room1.key,
            started_at=timezone.now(),
        )

        self.assertIn("Open Market Day", self._index())

    def test_index_hides_unpublished_lore(self):
        """Mirrors LoreListView: only PUBLISHED, non-archived entries are public."""
        from django.db.models import Max
        from evennia_lore.models import LoreEntry

        # entry_number is a required unique column with no default; the contrib
        # assigns it on the authoring path, which this test bypasses.
        next_number = (
            LoreEntry.objects.aggregate(Max("entry_number"))["entry_number__max"] or 0
        ) + 1
        LoreEntry.objects.create(
            entry_number=next_number,
            title="Draft Secret",
            body="...",
            status=LoreEntry.Status.DRAFT,
        )

        self.assertNotIn("Draft Secret", self._index())

    def test_index_hides_a_cancelled_event(self):
        """Mirrors CalendarListView's is_cancelled=False."""
        from datetime import timedelta

        from django.utils import timezone
        from evennia_calendar.models import CalendarEvent

        CalendarEvent.objects.create(
            title="Called Off",
            scheduled_time=timezone.now() + timedelta(days=1),
            is_cancelled=True,
        )

        self.assertNotIn("Called Off", self._index())

    def test_index_lists_the_in_game_only_contribs(self):
        """The systems widget is honest about the contribs with no web surface."""
        html = self._index()

        for app_label in ("evennia_rptracker", "evennia_posing", "evennia_social"):
            with self.subTest(contrib=app_label):
                self.assertIn(app_label, html)
        self.assertIn("in-game only", html)

    def test_index_survives_an_empty_database(self):
        """No widget raises, and each renders its own empty state.

        A freshly migrated game with nothing in it is the first thing an adopter
        sees, so it has to be a correct page rather than a stack trace.
        """
        from evennia_boards.models import Board
        from evennia_calendar.models import CalendarEvent
        from evennia_lore.models import LoreEntry
        from evennia_plots.models import PlotThread
        from evennia_scenes.models import Scene

        from evennia_maps.models import MapPlane

        for model in (Scene, LoreEntry, CalendarEvent, Board, PlotThread, MapPlane):
            model.objects.all().delete()

        html = self._index()

        self.assertIn("No scenes are running right now.", html)
        self.assertIn("Nothing on the calendar yet.", html)
        self.assertIn("No map planes exist yet.", html)
        self.assertIn("Nothing has happened here in the last month.", html)
