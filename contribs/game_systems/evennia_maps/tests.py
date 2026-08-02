# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_maps: models, direction, placement, layout, listeners,
and +map.

EvenniaTest's stock DefaultRoom carries no terrain_tags state, so every
test case here sets room_typeclass to a local MapsTestRoom (MapsRoomMixin
+ DefaultRoom) — the same pattern evennia_social's test suite uses for
SocialRoomMixin. Plain create.create_object() calls for extra rooms
(room3, RoomA, etc.) use the same typeclass explicitly so terrain/mixin
behaviour is available uniformly, not just on the two EvenniaTest fixture
rooms.
"""

import contextlib

from django.db import IntegrityError, transaction
from evennia.objects.objects import DefaultRoom
from evennia.utils import create
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from evennia_maps import direction, layout, placement
from evennia_maps.commands import CmdMap
from evennia_maps.models import MapPlane, RoomTile
from evennia_maps.permissions import is_staff
from evennia_maps.signals import tile_placed
from evennia_maps.typeclasses import MapsRoomMixin

ROOM_TYPECLASS = "evennia_maps.tests.MapsTestRoom"


class MapsTestRoom(MapsRoomMixin, DefaultRoom):
    """Test-local Room mixing in MapsRoomMixin."""


def _make_plane(name="Overworld", zstack="", elevation=0):
    return MapPlane.objects.create(name=name, zstack=zstack, elevation=elevation)


def _make_room(key):
    return create.create_object(ROOM_TYPECLASS, key=key)


class MapsTestCase(EvenniaTest):
    room_typeclass = MapsTestRoom


class MapsCommandTestCase(EvenniaCommandTest):
    room_typeclass = MapsTestRoom


# ---------------------------------------------------------------------------
# MapPlane / RoomTile
# ---------------------------------------------------------------------------


class TestMapPlane(MapsTestCase):
    def test_create_plane(self):
        p = _make_plane("Overworld")
        self.assertEqual(p.name, "Overworld")
        self.assertEqual(p.zstack, "")
        self.assertEqual(p.elevation, 0)

    def test_str_returns_name(self):
        p = _make_plane("Skylands")
        self.assertEqual(str(p), "Skylands")

    def test_stacked_planes_share_zstack_at_different_elevations(self):
        _make_plane("Surface", zstack="overworld", elevation=0)
        underground = _make_plane("Underground", zstack="overworld", elevation=-1)
        self.assertEqual(underground.elevation, -1)

    def test_duplicate_elevation_in_same_zstack_rejected(self):
        _make_plane("Surface", zstack="overworld", elevation=0)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            _make_plane("Surface Duplicate", zstack="overworld", elevation=0)

    def test_multiple_standalone_planes_allowed_at_same_elevation(self):
        # zstack="" is exempt from the one-plane-per-elevation constraint,
        # so many interior planes can all sit at elevation=0.
        _make_plane("City Interior A", zstack="", elevation=0)
        _make_plane("City Interior B", zstack="", elevation=0)
        self.assertEqual(MapPlane.objects.filter(zstack="", elevation=0).count(), 2)


class TestRoomTile(MapsTestCase):
    def setUp(self):
        super().setUp()
        self.plane = _make_plane()

    def test_create_tile(self):
        tile = RoomTile.objects.create(
            plane=self.plane, room=self.room1, x=0, y=0, room_name=self.room1.key
        )
        self.assertEqual(tile.room, self.room1)
        self.assertEqual((tile.x, tile.y), (0, 0))

    def test_str_contains_room_and_plane(self):
        tile = RoomTile.objects.create(
            plane=self.plane, room=self.room1, x=1, y=2, room_name="The Grand Hall"
        )
        self.assertIn("The Grand Hall", str(tile))
        self.assertIn(self.plane.name, str(tile))

    def test_unique_coordinate_per_plane(self):
        RoomTile.objects.create(plane=self.plane, room=self.room1, x=0, y=0)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            RoomTile.objects.create(plane=self.plane, room=self.room2, x=0, y=0)

    def test_same_coordinate_allowed_on_different_planes(self):
        other_plane = _make_plane("Underground", zstack="overworld", elevation=-1)
        RoomTile.objects.create(plane=self.plane, room=self.room1, x=0, y=0)
        tile = RoomTile.objects.create(plane=other_plane, room=self.room2, x=0, y=0)
        self.assertEqual((tile.x, tile.y), (0, 0))

    def test_one_tile_per_room(self):
        RoomTile.objects.create(plane=self.plane, room=self.room1, x=0, y=0)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            RoomTile.objects.create(plane=self.plane, room=self.room1, x=5, y=5)

    def test_room_delete_cascades_tile(self):
        RoomTile.objects.create(plane=self.plane, room=self.room1, x=0, y=0)
        self.room1.delete()
        self.assertFalse(RoomTile.objects.filter(plane=self.plane, x=0, y=0).exists())

    def test_plane_delete_cascades_tiles(self):
        RoomTile.objects.create(plane=self.plane, room=self.room1, x=0, y=0)
        self.plane.delete()
        self.assertFalse(RoomTile.objects.filter(room=self.room1).exists())


# ---------------------------------------------------------------------------
# direction.resolve / get_offsets
# ---------------------------------------------------------------------------


class TestDirectionResolve(MapsTestCase):
    def _make_exit(self, key, aliases=None, location=None, destination=None):
        return create.create_object(
            self.exit_typeclass,
            key=key,
            aliases=aliases or [],
            location=location or self.room1,
            destination=destination or self.room2,
        )

    def test_resolve_matches_canonical_key(self):
        exit_obj = self._make_exit("n")
        self.assertEqual(direction.resolve(exit_obj), (0, 1, 0, "planar"))

    def test_resolve_matches_canonical_alias_case_insensitive(self):
        exit_obj = self._make_exit("Northward Path", aliases=["N"])
        self.assertEqual(direction.resolve(exit_obj), (0, 1, 0, "planar"))

    def test_resolve_matches_vertical_direction(self):
        exit_obj = self._make_exit("u")
        self.assertEqual(direction.resolve(exit_obj), (0, 0, 1, "vertical"))

    def test_resolve_matches_dig_style_full_name_without_alias(self):
        # `dig north=New Room` creates key="north" with no alias at all.
        # Registering only abbreviations would make the most common build
        # path invisible to the map.
        for key, expected in (
            ("north", (0, 1, 0, "planar")),
            ("southwest", (-1, -1, 0, "planar")),
            ("up", (0, 0, 1, "vertical")),
            ("down", (0, 0, -1, "vertical")),
        ):
            with self.subTest(key=key):
                self.assertEqual(direction.resolve(self._make_exit(key)), expected)

    def test_resolve_matches_tunnel_style_full_name_plus_alias(self):
        # `@tunnel ne` creates key="northeast" with alias "ne".
        exit_obj = self._make_exit("northeast", aliases=["ne"])
        self.assertEqual(direction.resolve(exit_obj), (1, 1, 0, "planar"))

    def test_resolve_rejects_free_form_exit(self):
        exit_obj = self._make_exit("rickety wooden ladder")
        self.assertIsNone(direction.resolve(exit_obj))

    def test_resolve_rejects_portal_directions(self):
        # in/out are real Evennia @tunnel directions, but they are
        # deliberately unmapped: portal-ness is inferred from geometry,
        # never declared as a direction offset. EvenniaTest's fixture
        # exit is keyed "out".
        self.assertIsNone(direction.resolve(self.exit))
        self.assertIsNone(direction.resolve(self._make_exit("in")))

    def test_get_offsets_merges_settings_override(self):
        with self.settings(MAPS_DIRECTION_OFFSETS={"n": (0, 2, 0, "planar")}):
            offsets = direction.get_offsets()
            self.assertEqual(offsets["n"], (0, 2, 0, "planar"))
            # Unrelated entries are untouched by the override.
            self.assertEqual(offsets["s"], (0, -1, 0, "planar"))

    def test_abbreviation_and_full_name_agree(self):
        """Guard against editing one spelling of a direction but not the other."""
        for abbrev, full in (
            ("n", "north"),
            ("s", "south"),
            ("e", "east"),
            ("w", "west"),
            ("ne", "northeast"),
            ("nw", "northwest"),
            ("se", "southeast"),
            ("sw", "southwest"),
            ("u", "up"),
            ("d", "down"),
        ):
            with self.subTest(direction=full):
                offsets = direction.DEFAULT_DIRECTION_OFFSETS
                self.assertEqual(offsets[abbrev], offsets[full])

    def test_opposite_directions_cancel(self):
        """n/s, e/w, u/d must be exact inverses or layout drifts."""
        offsets = direction.DEFAULT_DIRECTION_OFFSETS
        for a, b in (("n", "s"), ("e", "w"), ("ne", "sw"), ("nw", "se"), ("u", "d")):
            with self.subTest(pair=f"{a}/{b}"):
                ax, ay, az, _ = offsets[a]
                bx, by, bz, _ = offsets[b]
                self.assertEqual((ax + bx, ay + by, az + bz), (0, 0, 0))


# ---------------------------------------------------------------------------
# placement
# ---------------------------------------------------------------------------


class TestPlaceTile(MapsTestCase):
    def setUp(self):
        super().setUp()
        self.plane = _make_plane()

    def test_place_creates_tile(self):
        tile = placement.place_tile(self.room1, self.plane, 0, 0)
        self.assertEqual((tile.plane, tile.x, tile.y), (self.plane, 0, 0))
        self.assertEqual(tile.room_name, self.room1.key)

    def test_place_is_idempotent_at_same_cell(self):
        first = placement.place_tile(self.room1, self.plane, 2, 3)
        second = placement.place_tile(self.room1, self.plane, 2, 3)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(RoomTile.objects.filter(room=self.room1).count(), 1)

    def test_place_moves_existing_tile(self):
        placement.place_tile(self.room1, self.plane, 0, 0)
        moved = placement.place_tile(self.room1, self.plane, 5, 5)
        self.assertEqual((moved.x, moved.y), (5, 5))
        self.assertEqual(RoomTile.objects.filter(room=self.room1).count(), 1)

    def test_place_returns_conflict_when_cell_held(self):
        placement.place_tile(self.room1, self.plane, 0, 0)
        result = placement.place_tile(self.room2, self.plane, 0, 0)
        self.assertIsInstance(result, placement.Conflict)
        self.assertEqual(result.holder.room_id, self.room1.id)
        # No tile was written for room2.
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())

    def test_place_sets_pinned_flag(self):
        tile = placement.place_tile(self.room1, self.plane, 0, 0, pinned=True)
        self.assertTrue(tile.pinned)


class TestPlaceRelative(MapsTestCase):
    def setUp(self):
        super().setUp()
        self.plane = _make_plane()
        placement.place_tile(self.room1, self.plane, 0, 0)

    def _make_exit(self, key, location, destination, aliases=None):
        return create.create_object(
            self.exit_typeclass,
            key=key,
            aliases=aliases or [],
            location=location,
            destination=destination,
        )

    def test_free_form_exit_is_ignored(self):
        exit_obj = self._make_exit("rickety ladder", self.room1, self.room2)
        self.assertIsNone(placement.place_relative(self.room1, exit_obj))
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())

    def test_exit_with_no_destination_is_ignored(self):
        # DefaultExit.basetype_setup() self-loops destination to location
        # when none is given at creation, so a destination-less exit is
        # only reachable by clearing db_destination after the fact.
        exit_obj = self._make_exit("n", self.room1, self.room2)
        exit_obj.db_destination = None
        exit_obj.save()
        self.assertIsNone(placement.place_relative(self.room1, exit_obj))

    def test_unmapped_source_is_ignored(self):
        room3 = _make_room("Room3")
        exit_obj = self._make_exit("n", room3, self.room2)
        self.assertIsNone(placement.place_relative(room3, exit_obj))

    def test_planar_exit_places_destination_offset(self):
        exit_obj = self._make_exit("n", self.room1, self.room2)
        tile = placement.place_relative(self.room1, exit_obj)
        self.assertEqual((tile.plane, tile.x, tile.y), (self.plane, 0, 1))

    def test_planar_exit_is_idempotent(self):
        exit_obj = self._make_exit("n", self.room1, self.room2)
        first = placement.place_relative(self.room1, exit_obj)
        second = placement.place_relative(self.room1, exit_obj)
        self.assertEqual(first.pk, second.pk)

    def test_destination_already_elsewhere_is_conflict(self):
        other_plane = _make_plane("Other")
        placement.place_tile(self.room2, other_plane, 9, 9)
        exit_obj = self._make_exit("n", self.room1, self.room2)
        result = placement.place_relative(self.room1, exit_obj)
        self.assertIsInstance(result, placement.Conflict)

    def test_destination_cell_held_by_other_room_is_conflict(self):
        room3 = _make_room("Room3")
        placement.place_tile(room3, self.plane, 0, 1)
        exit_obj = self._make_exit("n", self.room1, self.room2)
        result = placement.place_relative(self.room1, exit_obj)
        self.assertIsInstance(result, placement.Conflict)
        self.assertEqual(result.holder.room_id, room3.id)

    def test_vertical_exit_creates_stacked_plane(self):
        stacked_plane = _make_plane("Surface Stack", zstack="overworld", elevation=0)
        placement.place_tile(self.room1, stacked_plane, 3, 4)
        exit_obj = self._make_exit("up", self.room1, self.room2)
        tile = placement.place_relative(self.room1, exit_obj)
        self.assertEqual((tile.x, tile.y), (3, 4))
        self.assertEqual(tile.plane.zstack, "overworld")
        self.assertEqual(tile.plane.elevation, 1)

    def test_vertical_exit_from_standalone_plane_is_ignored(self):
        # self.plane has zstack="" — no stack to move within.
        exit_obj = self._make_exit("up", self.room1, self.room2)
        self.assertIsNone(placement.place_relative(self.room1, exit_obj))

    def test_vertical_conflict_does_not_leave_an_orphan_plane(self):
        # `dig up` to a room that's already mapped elsewhere declines to
        # write a tile — so it must not have created the destination
        # plane on the way to that decision, or every such attempt
        # leaves an empty plane behind.
        surface = _make_plane("Surface", zstack="overworld", elevation=0)
        elsewhere = _make_plane("Elsewhere")
        placement.place_tile(self.room1, surface, 0, 0)
        placement.place_tile(self.room2, elsewhere, 9, 9)
        exit_obj = self._make_exit("up", self.room1, self.room2)
        result = placement.place_relative(self.room1, exit_obj)
        self.assertIsInstance(result, placement.Conflict)
        self.assertFalse(MapPlane.all_objects.filter(zstack="overworld", elevation=1).exists())

    def test_vertical_exit_to_correctly_placed_destination_is_a_noop(self):
        # The other early return: the destination is already exactly
        # where this exit computes, on a stacked plane that does exist.
        surface = _make_plane("Surface", zstack="overworld", elevation=0)
        sky = _make_plane("Sky", zstack="overworld", elevation=1)
        placement.place_tile(self.room1, surface, 2, 3)
        existing = placement.place_tile(self.room2, sky, 2, 3)
        exit_obj = self._make_exit("up", self.room1, self.room2)
        result = placement.place_relative(self.room1, exit_obj)
        self.assertEqual(result.pk, existing.pk)

    def test_vertical_exit_reuses_archived_stacked_plane(self):
        # MapPlane.objects is an ArchivedManager, but the
        # evennia_maps_one_plane_per_elevation constraint is enforced by
        # the DB regardless of archive state — looking the neighbour up
        # through the default manager would miss the archived row, try
        # to create a duplicate, and raise IntegrityError.
        surface = _make_plane("Surface", zstack="overworld", elevation=0)
        sky = _make_plane("Sky", zstack="overworld", elevation=1)
        sky.archive()
        placement.place_tile(self.room1, surface, 0, 0)
        exit_obj = self._make_exit("up", self.room1, self.room2)
        tile = placement.place_relative(self.room1, exit_obj)
        self.assertEqual(tile.plane_id, sky.id)
        self.assertEqual(MapPlane.all_objects.filter(zstack="overworld", elevation=1).count(), 1)


class TestResolveStackedPlane(MapsTestCase):
    def test_standalone_plane_has_no_neighbour(self):
        standalone = _make_plane("Interior", zstack="", elevation=0)
        self.assertIsNone(placement.resolve_stacked_plane(standalone, 1))

    def test_scaffolds_missing_neighbour(self):
        surface = _make_plane("Surface", zstack="overworld", elevation=0)
        plane = placement.resolve_stacked_plane(surface, -1)
        self.assertEqual((plane.zstack, plane.elevation), ("overworld", -1))

    def test_is_idempotent(self):
        surface = _make_plane("Surface", zstack="overworld", elevation=0)
        first = placement.resolve_stacked_plane(surface, 1)
        second = placement.resolve_stacked_plane(surface, 1)
        self.assertEqual(first.id, second.id)

    def test_finds_archived_neighbour_without_duplicating(self):
        surface = _make_plane("Surface", zstack="overworld", elevation=0)
        sky = _make_plane("Sky", zstack="overworld", elevation=1)
        sky.archive()
        self.assertEqual(placement.resolve_stacked_plane(surface, 1).id, sky.id)


class TestPlaneKey(MapsTestCase):
    def test_key_from_object_matches_key_from_id(self):
        # layout._validate builds cell keys from values_list rows (pk
        # only) and looks them up against keys built from plane objects.
        # If these two spellings drift, every lookup silently misses and
        # blocked moves stop being reported at all — a failure with no
        # obvious symptom, so it gets a direct test.
        plane = _make_plane()
        self.assertEqual(placement.plane_key(plane), placement.plane_key_for_id(plane.pk))

    def test_pending_plane_does_not_collide_with_a_real_plane(self):
        plane = _make_plane("Real", zstack="overworld", elevation=0)
        pending = placement.PendingPlane("overworld", 1)
        self.assertNotEqual(placement.plane_key(plane), placement.plane_key(pending))

    def test_distinct_pending_planes_have_distinct_keys(self):
        # The reason cells can't key on plane_id alone: two different
        # not-yet-created planes would both key on None.
        up = placement.PendingPlane("overworld", 1)
        down = placement.PendingPlane("overworld", -1)
        self.assertNotEqual(placement.plane_key(up), placement.plane_key(down))


class TestMoveUnplacePin(MapsTestCase):
    def setUp(self):
        super().setUp()
        self.plane = _make_plane()

    def test_move_unplaced_room_returns_none(self):
        self.assertIsNone(placement.move_tile(self.room1, 1, 1))

    def test_move_repositions_tile(self):
        placement.place_tile(self.room1, self.plane, 0, 0)
        moved = placement.move_tile(self.room1, 4, 4)
        self.assertEqual((moved.x, moved.y), (4, 4))

    def test_move_returns_conflict(self):
        placement.place_tile(self.room1, self.plane, 0, 0)
        placement.place_tile(self.room2, self.plane, 1, 1)
        result = placement.move_tile(self.room1, 1, 1)
        self.assertIsInstance(result, placement.Conflict)

    def test_move_refreshes_denormalized_snapshot(self):
        # Both write paths must leave the snapshot in the same state, or
        # +map/check reports drift that depends only on which one ran.
        placement.place_tile(self.room1, self.plane, 0, 0)
        with self.settings(MAPS_TERRAIN_PRECEDENCE=["forest"]):
            self.room1.terrain_tags = {"forest"}
            self.room1.key = "Renamed Room"
            moved = placement.move_tile(self.room1, 4, 4)
        self.assertEqual(moved.terrain, "forest")
        self.assertEqual(moved.room_name, "Renamed Room")

    def test_unplace_removes_tile(self):
        placement.place_tile(self.room1, self.plane, 0, 0)
        self.assertTrue(placement.unplace_tile(self.room1))
        self.assertFalse(RoomTile.objects.filter(room=self.room1).exists())

    def test_unplace_returns_false_when_unmapped(self):
        self.assertFalse(placement.unplace_tile(self.room1))

    def test_set_pin_toggles_flag(self):
        placement.place_tile(self.room1, self.plane, 0, 0)
        tile = placement.set_pin(self.room1, True)
        self.assertTrue(tile.pinned)
        tile = placement.set_pin(self.room1, False)
        self.assertFalse(tile.pinned)

    def test_set_pin_on_unmapped_room_returns_none(self):
        self.assertIsNone(placement.set_pin(self.room1, True))


class TestApplyPlan(MapsTestCase):
    """
    Unit tests for placement.apply_plan().

    Move objects are built by hand (rather than via layout.plan()) so
    these tests exercise apply_plan() in isolation from the BFS/fixed
    point that normally produces them.
    """

    def setUp(self):
        super().setUp()
        self.plane = _make_plane()

    def _move(self, room, plane, x, y, *, created):
        return layout.Move(room=room, plane=plane, x=x, y=y, created=created, pinned=False)

    def test_writes_a_new_room(self):
        result = layout.ReflowPlan(
            report=layout.LayoutReport(),
            moves=[self._move(self.room1, self.plane, 3, 4, created=True)],
        )
        written = placement.apply_plan(result)
        self.assertEqual(written, 1)
        tile = RoomTile.objects.get(room=self.room1)
        self.assertEqual((tile.plane, tile.x, tile.y), (self.plane, 3, 4))

    def test_moves_an_existing_room(self):
        placement.place_tile(self.room1, self.plane, 0, 0)
        result = layout.ReflowPlan(
            report=layout.LayoutReport(),
            moves=[self._move(self.room1, self.plane, 5, 5, created=False)],
        )
        placement.apply_plan(result)
        tile = RoomTile.objects.get(room=self.room1)
        self.assertEqual((tile.x, tile.y), (5, 5))
        self.assertEqual(RoomTile.objects.filter(room=self.room1).count(), 1)

    def test_only_moves_are_written_not_pinned_skips_or_blocked(self):
        # pinned_skips and blocked are reports for the caller to render,
        # not instructions — apply_plan must not act on them.
        blocked = layout.Blocked(
            room=self.room2, plane=self.plane, x=1, y=1, holder_room_id=self.room1.id
        )
        result = layout.ReflowPlan(
            report=layout.LayoutReport(),
            moves=[],
            pinned_skips=[(self.room1, self.plane, 0, 0)],
            blocked=[blocked],
        )
        written = placement.apply_plan(result)
        self.assertEqual(written, 0)
        self.assertFalse(RoomTile.objects.filter(room=self.room1).exists())
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())

    def test_rotates_a_two_cycle(self):
        # RoomA and RoomB swap cells — the case ordered in-place writes
        # cannot handle (neither cell is ever free to write to first),
        # which is why apply_plan deletes every mover before recreating
        # any of them.
        room_a = _make_room("RoomA")
        room_b = _make_room("RoomB")
        placement.place_tile(room_a, self.plane, 0, 0)
        placement.place_tile(room_b, self.plane, 1, 0)
        result = layout.ReflowPlan(
            report=layout.LayoutReport(),
            moves=[
                self._move(room_a, self.plane, 1, 0, created=False),
                self._move(room_b, self.plane, 0, 0, created=False),
            ],
        )
        written = placement.apply_plan(result)
        self.assertEqual(written, 2)
        self.assertEqual(
            (RoomTile.objects.get(room=room_a).x, RoomTile.objects.get(room=room_a).y), (1, 0)
        )
        self.assertEqual(
            (RoomTile.objects.get(room=room_b).x, RoomTile.objects.get(room=room_b).y), (0, 0)
        )

    def test_materialises_a_pending_plane(self):
        surface = _make_plane("Surface", zstack="overworld", elevation=0)
        pending = placement.PendingPlane("overworld", 1)
        result = layout.ReflowPlan(
            report=layout.LayoutReport(),
            moves=[self._move(self.room1, pending, 0, 0, created=True)],
        )
        placement.apply_plan(result)
        real_plane = MapPlane.all_objects.get(zstack="overworld", elevation=1)
        self.assertEqual(real_plane.name, pending.name)
        tile = RoomTile.objects.get(room=self.room1)
        self.assertEqual(tile.plane_id, real_plane.id)
        # Surface (elevation 0) is untouched — confirms the right plane
        # was created, not a duplicate of an unrelated one.
        self.assertNotEqual(real_plane.id, surface.id)

    def test_preserves_created_flag_on_the_signal(self):
        # apply_plan defers tile_placed to transaction.on_commit, which
        # never fires under a transactional TestCase — captureOnCommitCallbacks
        # runs the callbacks so the payload can be asserted at all.
        received = []

        def _on_tile_placed(sender, tile, actor, created, **kwargs):
            received.append((tile.room_id, created))

        tile_placed.connect(_on_tile_placed)
        try:
            new_room = _make_room("NewRoom")
            placement.place_tile(self.room1, self.plane, 0, 0)
            result = layout.ReflowPlan(
                report=layout.LayoutReport(),
                moves=[
                    self._move(new_room, self.plane, 1, 0, created=True),
                    self._move(self.room1, self.plane, 2, 0, created=False),
                ],
            )
            with self.captureOnCommitCallbacks(execute=True):
                placement.apply_plan(result)
        finally:
            tile_placed.disconnect(_on_tile_placed)

        by_room = dict(received)
        self.assertTrue(by_room[new_room.id])
        self.assertFalse(by_room[self.room1.id])

    def test_does_not_signal_when_an_enclosing_transaction_rolls_back(self):
        # The reason for on_commit rather than "fire after the atomic
        # block": apply_plan is normally nested inside the caller's
        # transaction, so leaving its own block is a savepoint release,
        # not a commit. A receiver must not be told about writes that
        # the outer transaction then discards.
        received = []

        def _on_tile_placed(sender, **kwargs):
            received.append(kwargs["tile"].room_id)

        tile_placed.connect(_on_tile_placed)
        try:
            result = layout.ReflowPlan(
                report=layout.LayoutReport(),
                moves=[self._move(self.room1, self.plane, 1, 0, created=True)],
            )
            # Ordering matters: capture outermost, then suppress, then
            # atomic — atomic must see the exception to roll back, and
            # suppress catches it only after that has happened.
            with (
                self.captureOnCommitCallbacks(execute=True),
                contextlib.suppress(RuntimeError),
                transaction.atomic(),
            ):
                placement.apply_plan(result)
                raise RuntimeError("caller fails after apply_plan succeeded")
        finally:
            tile_placed.disconnect(_on_tile_placed)

        self.assertEqual(received, [])
        self.assertFalse(RoomTile.objects.filter(room=self.room1).exists())

    def test_returns_zero_for_an_empty_plan(self):
        result = layout.ReflowPlan(report=layout.LayoutReport())
        self.assertEqual(placement.apply_plan(result), 0)

    def test_raises_integrity_error_when_target_taken_between_plan_and_apply(self):
        # Simulates the exit-creation listener writing a tile after
        # layout.plan() computed its snapshot but before this call runs —
        # the race apply_plan()'s docstring calls out. Nothing is
        # written; the whole transaction rolls back.
        result = layout.ReflowPlan(
            report=layout.LayoutReport(),
            moves=[self._move(self.room1, self.plane, 5, 5, created=True)],
        )
        intruder = _make_room("Intruder")
        placement.place_tile(intruder, self.plane, 5, 5)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            placement.apply_plan(result)
        self.assertFalse(RoomTile.objects.filter(room=self.room1).exists())


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------


class TestWalk(MapsTestCase):
    def setUp(self):
        super().setUp()
        self.plane = _make_plane()

    def _link(self, key, source, destination, aliases=None):
        return create.create_object(
            self.exit_typeclass,
            key=key,
            aliases=aliases or [],
            location=source,
            destination=destination,
        )

    def test_walk_requires_origin_tile(self):
        with self.assertRaises(ValueError):
            layout.walk(self.room1)

    def test_walk_includes_origin_as_unchanged(self):
        placement.place_tile(self.room1, self.plane, 0, 0)
        report = layout.walk(self.room1)
        self.assertEqual(len(report.assignments), 1)
        room, plane, x, y, unchanged = report.assignments[0]
        self.assertEqual((room, plane, x, y, unchanged), (self.room1, self.plane, 0, 0, True))

    def test_walk_proposes_unplaced_neighbor(self):
        self._link("n", self.room1, self.room2)
        placement.place_tile(self.room1, self.plane, 0, 0)
        report = layout.walk(self.room1)
        proposed = {(r.id, x, y) for r, _, x, y, _ in report.assignments}
        self.assertIn((self.room2.id, 0, 1), proposed)
        # Confirms this was proposed by walk(), not already written.
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())

    def test_walk_marks_already_correct_neighbor_unchanged(self):
        self._link("n", self.room1, self.room2)
        placement.place_tile(self.room2, self.plane, 0, 1)
        placement.place_tile(self.room1, self.plane, 0, 0)
        report = layout.walk(self.room1)
        match = [a for a in report.assignments if a[0] == self.room2]
        self.assertEqual(len(match), 1)
        self.assertTrue(match[0][4])

    def test_walk_flags_coordinate_conflict(self):
        # room3 is not reachable from room1, so it takes no part in this
        # reflow — its tile really will still be at (0,1) afterwards.
        room3 = _make_room("Room3")
        self._link("n", self.room1, self.room2)
        placement.place_tile(room3, self.plane, 0, 1)
        placement.place_tile(self.room1, self.plane, 0, 0)
        report = layout.walk(self.room1)
        conflict_rooms = {c.room.id for c in report.conflicts}
        self.assertIn(self.room2.id, conflict_rooms)
        held = next(c for c in report.conflicts if c.room.id == self.room2.id)
        self.assertEqual(held.reason, layout.CELL_HELD)
        self.assertEqual(held.holder_room_id, room3.id)
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())
        # A conflicted position is never offered as an assignment.
        self.assertNotIn(self.room2.id, {r.id for r, *_ in report.assignments})

    def test_walk_does_not_flag_rooms_that_are_themselves_moving(self):
        # Inserting a room into a corridor shifts everything downstream
        # one cell east, so each room wants the cell its predecessor
        # currently holds. Those predecessors are moving too, so none of
        # it is a real conflict — but validating against pre-reflow
        # state reported one false conflict per room in the corridor.
        room_new = _make_room("RoomNew")
        room3 = _make_room("Room3")
        self._link("e", self.room1, room_new)
        self._link("e", room_new, self.room2)
        self._link("e", self.room2, room3)
        placement.place_tile(self.room1, self.plane, 0, 0)
        placement.place_tile(self.room2, self.plane, 1, 0)
        placement.place_tile(room3, self.plane, 2, 0)

        report = layout.walk(self.room1)

        self.assertEqual(report.conflicts, [])
        proposed = {r.id: (x, y) for r, _, x, y, _ in report.assignments}
        self.assertEqual(proposed[room_new.id], (1, 0))
        self.assertEqual(proposed[self.room2.id], (2, 0))
        self.assertEqual(proposed[room3.id], (3, 0))

    def test_walk_flags_two_rooms_resolving_to_one_cell(self):
        # Both spellings resolve to the same offset, so room2 and room3
        # are each proposed for (0,1). First claim wins, second is
        # reported as contested rather than silently overwriting.
        room3 = _make_room("Room3")
        self._link("n", self.room1, self.room2)
        self._link("north", self.room1, room3)
        placement.place_tile(self.room1, self.plane, 0, 0)
        report = layout.walk(self.room1)
        contested = [c for c in report.conflicts if c.reason == layout.CELL_CONTESTED]
        self.assertEqual(len(contested), 1)
        self.assertEqual((contested[0].x, contested[0].y), (0, 1))

    def test_walk_flags_room_reachable_at_two_coordinates(self):
        # room1 -n-> room2 puts room2 at (0,1); room1 -e-> room3 -n->
        # room2 puts it at (1,1). The plan calls for detecting exactly
        # this, but the second path used to be dropped in silence.
        room3 = _make_room("Room3")
        self._link("n", self.room1, self.room2)
        self._link("e", self.room1, room3)
        self._link("n", room3, self.room2)
        placement.place_tile(self.room1, self.plane, 0, 0)
        report = layout.walk(self.room1)
        ambiguous = [c for c in report.conflicts if c.reason == layout.ROOM_AMBIGUOUS]
        self.assertEqual(len(ambiguous), 1)
        self.assertEqual(ambiguous[0].room.id, self.room2.id)
        self.assertIsNone(ambiguous[0].holder_room_id)

    def test_walk_ignores_free_form_exits(self):
        # EvenniaTest's fixture already creates a free-form "out" exit
        # room1 -> room2, so this adds a second one.
        self._link("a rickety ladder", self.room1, self.room2)
        placement.place_tile(self.room1, self.plane, 0, 0)
        report = layout.walk(self.room1)
        self.assertEqual(len(report.unmapped_exits), 2)
        proposed_rooms = {r.id for r, *_ in report.assignments}
        self.assertNotIn(self.room2.id, proposed_rooms)

    def test_walk_multi_hop_chain(self):
        room3 = _make_room("Room3")
        self._link("n", self.room1, self.room2)
        self._link("n", self.room2, room3)
        placement.place_tile(self.room1, self.plane, 0, 0)
        report = layout.walk(self.room1)
        proposed = {(r.id, x, y) for r, _, x, y, _ in report.assignments}
        self.assertIn((self.room2.id, 0, 1), proposed)
        self.assertIn((room3.id, 0, 2), proposed)
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())
        self.assertFalse(RoomTile.objects.filter(room=room3).exists())

    def test_walk_vertical_resolves_pending_plane_without_creating_it(self):
        # walk() must never write a MapPlane row for a stacked plane that
        # doesn't exist yet — a dry run (or a plan that's never applied)
        # would otherwise leave an empty scaffold behind every time.
        stacked = _make_plane("Stack", zstack="overworld", elevation=0)
        self._link("up", self.room1, self.room2)
        placement.place_tile(self.room1, stacked, 0, 0)
        report = layout.walk(self.room1)
        match = next(a for a in report.assignments if a[0] == self.room2)
        self.assertEqual((match[1].zstack, match[1].elevation), ("overworld", 1))
        self.assertIsInstance(match[1], placement.PendingPlane)
        self.assertFalse(MapPlane.all_objects.filter(zstack="overworld", elevation=1).exists())

    def test_walk_does_not_write_room_tiles(self):
        self._link("n", self.room1, self.room2)
        placement.place_tile(self.room1, self.plane, 0, 0)
        layout.walk(self.room1)
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())

    def test_walk_reuses_archived_stacked_plane(self):
        # Regression: walk() went through MapPlane.objects (an
        # ArchivedManager), so an archived neighbour plane was invisible
        # and the scaffolding get_or_create hit the DB-level
        # evennia_maps_one_plane_per_elevation constraint. Unlike the
        # listener, +map/reflow has no try/except — this surfaced as a
        # traceback.
        surface = _make_plane("Surface", zstack="overworld", elevation=0)
        sky = _make_plane("Sky", zstack="overworld", elevation=1)
        sky.archive()
        self._link("up", self.room1, self.room2)
        placement.place_tile(self.room1, surface, 0, 0)
        report = layout.walk(self.room1)
        match = next(a for a in report.assignments if a[0] == self.room2)
        self.assertEqual(match[1].id, sky.id)


class TestPlan(MapsTestCase):
    """Unit tests for layout.plan() — the fixed-point pass on top of walk()."""

    def setUp(self):
        super().setUp()
        self.plane = _make_plane()

    def _link(self, key, source, destination):
        return create.create_object(
            self.exit_typeclass, key=key, location=source, destination=destination
        )

    def test_requires_origin_tile(self):
        with self.assertRaises(ValueError):
            layout.plan(self.room1)

    def test_matches_walk_when_nothing_is_blocked(self):
        self._link("n", self.room1, self.room2)
        placement.place_tile(self.room1, self.plane, 0, 0)
        result = layout.plan(self.room1)
        self.assertEqual(result.blocked, [])
        self.assertEqual(result.pinned_skips, [])
        moved = {(m.room.id, m.x, m.y) for m in result.moves}
        self.assertIn((self.room2.id, 0, 1), moved)

    def test_move_created_flag_true_for_new_room(self):
        self._link("n", self.room1, self.room2)
        placement.place_tile(self.room1, self.plane, 0, 0)
        result = layout.plan(self.room1)
        move = next(m for m in result.moves if m.room.id == self.room2.id)
        self.assertTrue(move.created)

    def test_move_created_flag_false_for_repositioned_room(self):
        self._link("n", self.room1, self.room2)
        placement.place_tile(self.room1, self.plane, 0, 0)
        placement.place_tile(self.room2, self.plane, 9, 9)
        result = layout.plan(self.room1)
        move = next(m for m in result.moves if m.room.id == self.room2.id)
        self.assertFalse(move.created)
        self.assertEqual((move.x, move.y), (0, 1))

    def test_pinned_target_blocks_the_mover(self):
        # RoomA wants (1,0), which Pinned already occupies. Pinned itself
        # proposes a move to (2,0) (which is free), but never actually
        # goes there — so RoomA can never have (1,0).
        room_a = _make_room("RoomA")
        pinned = _make_room("Pinned")
        self._link("e", self.room1, room_a)
        self._link("e", room_a, pinned)
        placement.place_tile(self.room1, self.plane, 0, 0)
        placement.place_tile(pinned, self.plane, 1, 0, pinned=True)

        result = layout.plan(self.room1)

        self.assertEqual(result.moves, [])
        self.assertEqual(len(result.pinned_skips), 1)
        self.assertEqual(result.pinned_skips[0][0], pinned)
        self.assertEqual(len(result.blocked), 1)
        self.assertEqual(result.blocked[0].room, room_a)
        self.assertEqual(result.blocked[0].reason, layout.BLOCKED_BY_PINNED)
        self.assertEqual(result.blocked[0].holder_room_id, pinned.id)

    def test_immovable_participant_blocks_the_mover(self):
        # RoomB is reachable (a participant) and wants (2,0), which an
        # outsider holds — so RoomB is cell_held-conflicted and never
        # moves. RoomA wants RoomB's *current* cell, so RoomA is blocked
        # even though RoomB isn't pinned.
        room_a = _make_room("RoomA")
        room_b = _make_room("RoomB")
        outsider = _make_room("Outsider")
        self._link("e", self.room1, room_a)
        self._link("e", room_a, room_b)
        placement.place_tile(self.room1, self.plane, 0, 0)
        placement.place_tile(room_b, self.plane, 1, 0)
        placement.place_tile(outsider, self.plane, 2, 0)

        result = layout.plan(self.room1)

        moved_room_ids = {m.room.id for m in result.moves}
        self.assertNotIn(room_a.id, moved_room_ids)
        self.assertNotIn(room_b.id, moved_room_ids)
        blocked_by_room = {b.room.id: b for b in result.blocked}
        self.assertEqual(blocked_by_room[room_a.id].reason, layout.BLOCKED_BY_IMMOVABLE)
        self.assertEqual(blocked_by_room[room_a.id].holder_room_id, room_b.id)
        # RoomB itself never appears in .blocked — its own rejection is
        # already reported as a cell_held conflict.
        self.assertNotIn(room_b.id, blocked_by_room)
        conflicted_ids = {c.room.id for c in result.report.conflicts}
        self.assertIn(room_b.id, conflicted_ids)

    def test_cascade_blocks_transitively(self):
        # Room1 -> RoomNew -> Room2 -> Room3(pinned). Inserting RoomNew
        # wants Room2's current cell, but Room2 is itself blocked (it
        # wants Room3's current cell, and Room3 is pinned) — so RoomNew
        # is blocked too, one level removed from the pin.
        room_new = _make_room("RoomNew")
        room3 = _make_room("Room3")
        self._link("e", self.room1, room_new)
        self._link("e", room_new, self.room2)
        self._link("e", self.room2, room3)
        placement.place_tile(self.room1, self.plane, 0, 0)
        placement.place_tile(self.room2, self.plane, 1, 0)
        placement.place_tile(room3, self.plane, 2, 0, pinned=True)

        result = layout.plan(self.room1)

        self.assertEqual(result.moves, [])
        self.assertEqual(len(result.pinned_skips), 1)
        blocked_by_room = {b.room.id: b for b in result.blocked}
        self.assertEqual(blocked_by_room[self.room2.id].reason, layout.BLOCKED_BY_PINNED)
        self.assertEqual(blocked_by_room[room_new.id].reason, layout.BLOCKED_BY_BLOCKED)
        self.assertEqual(blocked_by_room[room_new.id].holder_room_id, self.room2.id)

    def test_cascade_from_an_outsider_blocked_tail(self):
        # The design doc's motivating example for the fixed point, and
        # the shape a single-pass check gets wrong by exactly one room:
        # Room1(0,0)-Room2(1,0)-Room3(2,0) with an outsider parked at
        # (3,0), inserting RoomNew. Room3 is cell_held-conflicted by the
        # outsider so it never moves; Room2 is blocked by Room3; and
        # RoomNew is blocked by Room2 — which a single pass would miss,
        # since Room2 is a mover and so "looks" like it will vacate.
        room_new = _make_room("RoomNew")
        room3 = _make_room("Room3")
        outsider = _make_room("Outsider")
        self._link("e", self.room1, room_new)
        self._link("e", room_new, self.room2)
        self._link("e", self.room2, room3)
        placement.place_tile(self.room1, self.plane, 0, 0)
        placement.place_tile(self.room2, self.plane, 1, 0)
        placement.place_tile(room3, self.plane, 2, 0)
        placement.place_tile(outsider, self.plane, 3, 0)

        result = layout.plan(self.room1)

        self.assertEqual(result.moves, [])
        blocked_by_room = {b.room.id: b for b in result.blocked}
        self.assertEqual(set(blocked_by_room), {self.room2.id, room_new.id})
        self.assertEqual(blocked_by_room[self.room2.id].reason, layout.BLOCKED_BY_IMMOVABLE)
        self.assertEqual(blocked_by_room[self.room2.id].holder_room_id, room3.id)
        self.assertEqual(blocked_by_room[room_new.id].reason, layout.BLOCKED_BY_BLOCKED)
        self.assertEqual(blocked_by_room[room_new.id].holder_room_id, self.room2.id)
        # Room3's own rejection stays a conflict, not a block.
        self.assertEqual([c.room.id for c in result.report.conflicts], [room3.id])

    def test_corridor_insert_has_no_blockers(self):
        # The regression this whole change exists for: inserting a room
        # into an unobstructed corridor must produce a full move set, not
        # a chain of blocks.
        room_new = _make_room("RoomNew")
        room3 = _make_room("Room3")
        self._link("e", self.room1, room_new)
        self._link("e", room_new, self.room2)
        self._link("e", self.room2, room3)
        placement.place_tile(self.room1, self.plane, 0, 0)
        placement.place_tile(self.room2, self.plane, 1, 0)
        placement.place_tile(room3, self.plane, 2, 0)

        result = layout.plan(self.room1)

        self.assertEqual(result.blocked, [])
        moved = {m.room.id: (m.x, m.y) for m in result.moves}
        self.assertEqual(moved[room_new.id], (1, 0))
        self.assertEqual(moved[self.room2.id], (2, 0))
        self.assertEqual(moved[room3.id], (3, 0))

    def test_branch_unaffected_by_a_blocked_sibling_branch(self):
        # Two branches off the origin; one is obstructed by a pinned
        # tile, the other is clear. The clear branch must still move.
        blocked_branch = _make_room("Blocked")
        pinned = _make_room("Pinned")
        clear_branch = _make_room("Clear")
        self._link("e", self.room1, blocked_branch)
        self._link("e", blocked_branch, pinned)
        self._link("n", self.room1, clear_branch)
        placement.place_tile(self.room1, self.plane, 0, 0)
        placement.place_tile(pinned, self.plane, 1, 0, pinned=True)

        result = layout.plan(self.room1)

        blocked_ids = {b.room.id for b in result.blocked}
        self.assertIn(blocked_branch.id, blocked_ids)
        moved = {m.room.id: (m.x, m.y) for m in result.moves}
        self.assertEqual(moved[clear_branch.id], (0, 1))


# ---------------------------------------------------------------------------
# listeners
# ---------------------------------------------------------------------------


class TestExitCreationListener(MapsTestCase):
    def setUp(self):
        super().setUp()
        self.plane = _make_plane()

    def test_dig_style_exit_auto_places_destination(self):
        placement.place_tile(self.room1, self.plane, 0, 0)
        create.create_object(
            self.exit_typeclass, key="north", location=self.room1, destination=self.room2
        )
        tile = RoomTile.objects.filter(room=self.room2).first()
        self.assertIsNotNone(tile)
        self.assertEqual((tile.x, tile.y), (0, 1))

    def test_exit_from_unmapped_source_does_nothing(self):
        create.create_object(
            self.exit_typeclass, key="north", location=self.room1, destination=self.room2
        )
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())

    def test_non_exit_object_creation_does_not_place_anything(self):
        placement.place_tile(self.room1, self.plane, 0, 0)
        create.create_object(
            self.object_typeclass, key="A Rock", location=self.room1, home=self.room1
        )
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())

    def test_free_form_exit_does_not_auto_place(self):
        placement.place_tile(self.room1, self.plane, 0, 0)
        create.create_object(
            self.exit_typeclass,
            key="a rickety ladder",
            location=self.room1,
            destination=self.room2,
        )
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())

    def test_conflicting_placement_does_not_raise(self):
        room3 = _make_room("Room3")
        placement.place_tile(self.room1, self.plane, 0, 0)
        placement.place_tile(room3, self.plane, 0, 1)
        # Should not raise even though (0,1) is already held by room3 —
        # the listener swallows placement.Conflict via place_relative's
        # normal return path, and any unexpected exception is logged,
        # not propagated (a mapping failure must never break dig).
        create.create_object(
            self.exit_typeclass, key="north", location=self.room1, destination=self.room2
        )
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())


class TestTerrainChangedListener(MapsTestCase):
    def test_set_terrain_refreshes_tile_snapshot(self):
        plane = _make_plane()
        placement.place_tile(self.room1, plane, 0, 0)
        with self.settings(MAPS_TERRAIN_PRECEDENCE=["forest", "hills"]):
            self.room1.set_terrain({"hills", "forest"})
        tile = RoomTile.objects.get(room=self.room1)
        self.assertEqual(tile.terrain, "forest")

    def test_set_terrain_on_unmapped_room_is_a_no_op(self):
        # Should not raise even though room1 has no tile.
        self.room1.set_terrain({"forest"})
        self.assertFalse(RoomTile.objects.filter(room=self.room1).exists())


class TestMapsRoomMixin(MapsTestCase):
    def test_has_terrain_false_with_no_tags(self):
        self.assertFalse(self.room1.has_terrain("forest"))

    def test_has_terrain_checks_all_given_tags(self):
        self.room1.terrain_tags = {"forest", "hills"}
        self.assertTrue(self.room1.has_terrain("forest"))
        self.assertTrue(self.room1.has_terrain("forest", "hills"))
        self.assertFalse(self.room1.has_terrain("water"))


# ---------------------------------------------------------------------------
# permissions
# ---------------------------------------------------------------------------


class TestIsStaff(MapsTestCase):
    # perm() checks the puppeting Account's permissions over the
    # Character's own, per evennia.locks.lockfuncs.perm's docstring — so
    # these grant on char2.account, not char2 itself.

    def test_builder_is_staff_by_default(self):
        self.char2.account.permissions.add("Builder")
        self.assertTrue(is_staff(self.char2))

    def test_player_is_not_staff_by_default(self):
        self.assertFalse(is_staff(self.char2))

    def test_custom_lock_is_honoured(self):
        # char1 carries EvenniaTest's default "Developer" permission — the
        # top of Evennia's hierarchy, which would satisfy perm(Admin)
        # regardless of MAPS_STAFF_LOCK and defeat the point of this test.
        # char2 starts with no permissions at all.
        with self.settings(MAPS_STAFF_LOCK="cmd:perm(Admin)"):
            self.char2.account.permissions.add("Builder")
            self.assertFalse(is_staff(self.char2))
            self.char2.account.permissions.add("Admin")
            self.assertTrue(is_staff(self.char2))


# ---------------------------------------------------------------------------
# +map command
# ---------------------------------------------------------------------------


class TestCmdMapRender(MapsCommandTestCase):
    def test_bare_shows_unmapped_message(self):
        result = self.call(CmdMap(), "", caller=self.char1)
        self.assertIn("isn't on the map", result)

    def test_render_shows_current_room_marker(self):
        plane = _make_plane()
        placement.place_tile(self.room1, plane, 0, 0)
        result = self.call(CmdMap(), "", caller=self.char1)
        self.assertIn(plane.name, result)
        self.assertIn("@", result)


class TestCmdMapPlace(MapsCommandTestCase):
    def test_place_creates_plane_and_places_room(self):
        result = self.call(CmdMap(), f"/place #{self.room1.id}=Skylands", caller=self.char1)
        self.assertIn("Skylands", result)
        tile = RoomTile.objects.get(room=self.room1)
        self.assertEqual((tile.x, tile.y), (0, 0))
        self.assertEqual(tile.plane.name, "Skylands")

    def test_place_player_denied(self):
        result = self.call(CmdMap(), f"/place #{self.room1.id}=Skylands", caller=self.char2)
        self.assertIn("staff permissions", result)
        self.assertFalse(RoomTile.objects.filter(room=self.room1).exists())

    def test_place_reports_conflict(self):
        plane = _make_plane("Skylands")
        placement.place_tile(self.room2, plane, 0, 0)
        result = self.call(CmdMap(), f"/place #{self.room1.id}=Skylands", caller=self.char1)
        self.assertIn("already held", result)


class TestCmdMapMove(MapsCommandTestCase):
    def test_move_repositions_room(self):
        plane = _make_plane()
        placement.place_tile(self.room1, plane, 0, 0)
        result = self.call(CmdMap(), f"/move #{self.room1.id}=3,4", caller=self.char1)
        self.assertIn("3, 4", result)
        tile = RoomTile.objects.get(room=self.room1)
        self.assertEqual((tile.x, tile.y), (3, 4))

    def test_move_unmapped_room_shows_error(self):
        result = self.call(CmdMap(), f"/move #{self.room1.id}=3,4", caller=self.char1)
        self.assertIn("isn't on the map", result)

    def test_move_bad_coordinates_shows_usage(self):
        plane = _make_plane()
        placement.place_tile(self.room1, plane, 0, 0)
        result = self.call(CmdMap(), f"/move #{self.room1.id}=abc", caller=self.char1)
        self.assertIn("integers", result)


class TestCmdMapUnplacePin(MapsCommandTestCase):
    def test_unplace_removes_tile(self):
        plane = _make_plane()
        placement.place_tile(self.room1, plane, 0, 0)
        result = self.call(CmdMap(), f"/unplace #{self.room1.id}", caller=self.char1)
        self.assertIn("Removed", result)
        self.assertFalse(RoomTile.objects.filter(room=self.room1).exists())

    def test_pin_and_unpin(self):
        plane = _make_plane()
        placement.place_tile(self.room1, plane, 0, 0)
        self.call(CmdMap(), f"/pin #{self.room1.id}", caller=self.char1)
        self.assertTrue(RoomTile.objects.get(room=self.room1).pinned)
        self.call(CmdMap(), f"/unpin #{self.room1.id}", caller=self.char1)
        self.assertFalse(RoomTile.objects.get(room=self.room1).pinned)


class TestCmdMapReflow(MapsCommandTestCase):
    def _link(self, key, source, destination):
        return create.create_object(
            self.exit_typeclass, key=key, location=source, destination=destination
        )

    def test_reflow_dry_run_does_not_write(self):
        # Link created before the origin is placed, so the exit-creation
        # auto-placement listener stays inert — this test is verifying
        # what /reflow itself does, not what the listener already did.
        plane = _make_plane()
        self._link("n", self.room1, self.room2)
        placement.place_tile(self.room1, plane, 0, 0)
        result = self.call(CmdMap(), f"/reflow #{self.room1.id}", caller=self.char1)
        self.assertIn("dry run", result)
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())

    def test_reflow_apply_writes_tiles(self):
        plane = _make_plane()
        self._link("n", self.room1, self.room2)
        placement.place_tile(self.room1, plane, 0, 0)
        result = self.call(CmdMap(), f"/reflow/apply #{self.room1.id}", caller=self.char1)
        self.assertIn("applying", result)
        tile = RoomTile.objects.get(room=self.room2)
        self.assertEqual((tile.x, tile.y), (0, 1))

    def test_reflow_apply_never_moves_pinned_tile(self):
        plane = _make_plane()
        placement.place_tile(self.room1, plane, 0, 0)
        placement.place_tile(self.room2, plane, 9, 9, pinned=True)
        self._link("n", self.room1, self.room2)
        result = self.call(CmdMap(), f"/reflow/apply #{self.room1.id}", caller=self.char1)
        tile = RoomTile.objects.get(room=self.room2)
        self.assertEqual((tile.x, tile.y), (9, 9))
        self.assertIn("pinned", result)

    def test_reflow_dry_run_predicts_pinned_skip(self):
        # A preview that doesn't report what apply will skip is worse
        # than no preview — the builder would expect the tile to move.
        plane = _make_plane()
        placement.place_tile(self.room1, plane, 0, 0)
        placement.place_tile(self.room2, plane, 9, 9, pinned=True)
        self._link("n", self.room1, self.room2)
        result = self.call(CmdMap(), f"/reflow #{self.room1.id}", caller=self.char1)
        self.assertIn("skipped, pinned", result)
        self.assertIn("1 pinned tile(s) skipped", result)

    def test_reflow_apply_reports_blocked_writes_rather_than_counting_them(self):
        # Room1-Room2-Room3(pinned), RoomNew inserted between Room1 and
        # Room2. RoomNew wants Room2's current cell, but Room2 wants
        # Room3's current cell and Room3 is pinned — so Room2 is blocked,
        # and RoomNew is blocked one level removed from the pin. Neither
        # write must be counted or attempted; the map must be untouched.
        plane = _make_plane()
        room_new = _make_room("RoomNew")
        room3 = _make_room("Room3")
        self._link("e", self.room1, room_new)
        self._link("e", room_new, self.room2)
        self._link("e", self.room2, room3)
        placement.place_tile(self.room1, plane, 0, 0)
        placement.place_tile(self.room2, plane, 1, 0)
        placement.place_tile(room3, plane, 2, 0, pinned=True)
        result = self.call(CmdMap(), f"/reflow/apply #{self.room1.id}", caller=self.char1)
        self.assertIn("0 written", result)
        self.assertIn("2 blocked", result)
        self.assertIn("1 pinned tile(s) skipped", result)
        self.assertFalse(RoomTile.objects.filter(room=room_new).exists())
        tile2 = RoomTile.objects.get(room=self.room2)
        self.assertEqual((tile2.x, tile2.y), (1, 0))

    def test_reflow_apply_shifts_a_corridor(self):
        # The headline regression: what the vacuous version of the test
        # above used to let through. Nothing here is blocked, so the
        # full corridor must move in one apply, not zero.
        plane = _make_plane()
        room_new = _make_room("RoomNew")
        room3 = _make_room("Room3")
        self._link("e", self.room1, room_new)
        self._link("e", room_new, self.room2)
        self._link("e", self.room2, room3)
        placement.place_tile(self.room1, plane, 0, 0)
        placement.place_tile(self.room2, plane, 1, 0)
        placement.place_tile(room3, plane, 2, 0)
        result = self.call(CmdMap(), f"/reflow/apply #{self.room1.id}", caller=self.char1)
        self.assertIn("3 written", result)
        self.assertIn("0 blocked", result)
        for room, expected in ((room_new, (1, 0)), (self.room2, (2, 0)), (room3, (3, 0))):
            tile = RoomTile.objects.get(room=room)
            self.assertEqual((tile.x, tile.y), expected)

    def test_reflow_dry_run_and_apply_agree(self):
        # The property the plan()/apply_plan() split exists to guarantee:
        # a dry run must promise exactly what apply then writes.
        plane = _make_plane()
        room_new = _make_room("RoomNew")
        room3 = _make_room("Room3")
        self._link("e", self.room1, room_new)
        self._link("e", room_new, self.room2)
        self._link("e", self.room2, room3)
        placement.place_tile(self.room1, plane, 0, 0)
        placement.place_tile(self.room2, plane, 1, 0)
        placement.place_tile(room3, plane, 2, 0)
        dry = self.call(CmdMap(), f"/reflow #{self.room1.id}", caller=self.char1)
        applied = self.call(CmdMap(), f"/reflow/apply #{self.room1.id}", caller=self.char1)
        dry_lines = {line for line in dry.splitlines() if "->" in line}
        applied_lines = {line for line in applied.splitlines() if "->" in line}
        self.assertTrue(dry_lines)
        self.assertEqual(dry_lines, applied_lines)

    def test_reflow_apply_is_idempotent(self):
        plane = _make_plane()
        self._link("n", self.room1, self.room2)
        placement.place_tile(self.room1, plane, 0, 0)
        first = self.call(CmdMap(), f"/reflow/apply #{self.room1.id}", caller=self.char1)
        self.assertIn("1 written", first)
        second = self.call(CmdMap(), f"/reflow/apply #{self.room1.id}", caller=self.char1)
        self.assertIn("0 written", second)
        self.assertIn("2 room(s) reachable", second)

    def test_reflow_apply_rotates_a_cycle(self):
        # RoomA/RoomB/RoomC each want a cell another of the three
        # currently holds — a genuine 3-cycle with no free cell to start
        # writing from, unlike the corridor case above (which is really
        # a path and could, in principle, be ordered). This is what
        # justifies delete-then-recreate over any ordering scheme.
        plane = _make_plane()
        room_a = _make_room("RoomA")
        room_b = _make_room("RoomB")
        room_c = _make_room("RoomC")
        self._link("e", self.room1, room_a)
        self._link("n", room_a, room_b)
        self._link("w", room_b, room_c)
        self._link("s", room_c, self.room1)
        placement.place_tile(self.room1, plane, 0, 0)
        # Natural resting cells (from the exits above) are RoomA=(1,0),
        # RoomB=(1,1), RoomC=(0,1). Placed one step rotated off that.
        placement.place_tile(room_a, plane, 1, 1)
        placement.place_tile(room_b, plane, 0, 1)
        placement.place_tile(room_c, plane, 1, 0)
        result = self.call(CmdMap(), f"/reflow/apply #{self.room1.id}", caller=self.char1)
        self.assertIn("3 written", result)
        self.assertIn("0 blocked", result)
        for room, expected in ((room_a, (1, 0)), (room_b, (1, 1)), (room_c, (0, 1))):
            tile = RoomTile.objects.get(room=room)
            self.assertEqual((tile.x, tile.y), expected)

    def test_reflow_writes_the_unobstructed_branch(self):
        # Two branches off the origin; a pinned tile obstructs one, the
        # other must move anyway rather than the whole reflow refusing.
        plane = _make_plane()
        blocked_branch = _make_room("Blocked")
        pinned_room = _make_room("Pinned")
        clear_branch = _make_room("Clear")
        self._link("e", self.room1, blocked_branch)
        self._link("e", blocked_branch, pinned_room)
        self._link("n", self.room1, clear_branch)
        placement.place_tile(self.room1, plane, 0, 0)
        placement.place_tile(pinned_room, plane, 1, 0, pinned=True)
        result = self.call(CmdMap(), f"/reflow/apply #{self.room1.id}", caller=self.char1)
        self.assertIn("1 blocked", result)
        self.assertIn("1 pinned tile(s) skipped", result)
        self.assertFalse(RoomTile.objects.filter(room=blocked_branch).exists())
        clear_tile = RoomTile.objects.get(room=clear_branch)
        self.assertEqual((clear_tile.x, clear_tile.y), (0, 1))

    def test_reflow_blocked_holder_is_found_across_planes(self):
        # Guards against the holder lookup being scoped to the origin
        # room's plane only — the blocker here sits on the *destination*
        # plane reached via a vertical exit, not room1's own plane.
        surface = _make_plane("Surface", zstack="overworld", elevation=0)
        sky = _make_plane("Sky", zstack="overworld", elevation=1)
        room_up = _make_room("RoomUp")
        room_far = _make_room("RoomFar")
        self._link("up", self.room1, room_up)
        self._link("e", room_up, room_far)
        placement.place_tile(self.room1, surface, 0, 0)
        placement.place_tile(room_up, sky, 1, 0, pinned=True)
        result = self.call(CmdMap(), f"/reflow/apply #{self.room1.id}", caller=self.char1)
        self.assertIn("1 blocked", result)
        self.assertIn("is pinned", result)
        self.assertFalse(RoomTile.objects.filter(room=room_far).exists())

    def test_reflow_dry_run_does_not_create_a_stacked_plane(self):
        surface = _make_plane("Surface", zstack="overworld", elevation=0)
        self._link("up", self.room1, self.room2)
        placement.place_tile(self.room1, surface, 0, 0)
        self.call(CmdMap(), f"/reflow #{self.room1.id}", caller=self.char1)
        self.assertFalse(MapPlane.all_objects.filter(zstack="overworld", elevation=1).exists())

    def test_reflow_apply_creates_the_stacked_plane(self):
        surface = _make_plane("Surface", zstack="overworld", elevation=0)
        self._link("up", self.room1, self.room2)
        placement.place_tile(self.room1, surface, 0, 0)
        self.call(CmdMap(), f"/reflow/apply #{self.room1.id}", caller=self.char1)
        sky = MapPlane.all_objects.get(zstack="overworld", elevation=1)
        tile = RoomTile.objects.get(room=self.room2)
        self.assertEqual(tile.plane_id, sky.id)

    def test_reflow_unmapped_origin_shows_error(self):
        result = self.call(CmdMap(), f"/reflow #{self.room1.id}", caller=self.char1)
        self.assertIn("isn't on the map", result)

    def test_reflow_reports_no_conflicts_for_a_corridor_shift(self):
        # The end-to-end version of the layout regression: inserting a
        # room into a corridor is an ordinary building move and must not
        # report a conflict per downstream room.
        plane = _make_plane()
        room_new = _make_room("RoomNew")
        room3 = _make_room("Room3")
        self._link("e", self.room1, room_new)
        self._link("e", room_new, self.room2)
        self._link("e", self.room2, room3)
        placement.place_tile(self.room1, plane, 0, 0)
        placement.place_tile(self.room2, plane, 1, 0)
        placement.place_tile(room3, plane, 2, 0)
        result = self.call(CmdMap(), f"/reflow #{self.room1.id}", caller=self.char1)
        self.assertIn("0 conflict(s)", result)
        self.assertNotIn("Conflicts:", result)

    def test_reflow_explains_a_held_cell(self):
        plane = _make_plane()
        outsider = _make_room("Outsider")
        self._link("n", self.room1, self.room2)
        placement.place_tile(outsider, plane, 0, 1)
        placement.place_tile(self.room1, plane, 0, 0)
        result = self.call(CmdMap(), f"/reflow #{self.room1.id}", caller=self.char1)
        self.assertIn("Conflicts:", result)
        self.assertIn("cell held by Outsider, which this reflow does not move", result)


class TestCmdMapCheck(MapsCommandTestCase):
    def _link(self, key, source, destination):
        return create.create_object(
            self.exit_typeclass, key=key, location=source, destination=destination
        )

    def test_check_reports_unmapped_neighbor(self):
        # Link created before the origin is placed, so the exit-creation
        # auto-placement listener stays inert and room2 stays unmapped.
        plane = _make_plane()
        self._link("n", self.room1, self.room2)
        placement.place_tile(self.room1, plane, 0, 0)
        result = self.call(CmdMap(), "/check", caller=self.char1)
        # Assert the count and the named room, not a bare "1" — that
        # matched dbrefs and coordinates anywhere in the output.
        self.assertIn("Unmapped neighbors (canonical exit, no destination tile): 1", result)
        self.assertIn(f"--n--> {self.room2.key} (unmapped)", result)

    def test_check_reports_nothing_when_map_is_consistent(self):
        plane = _make_plane()
        self._link("n", self.room1, self.room2)
        placement.place_tile(self.room1, plane, 0, 0)
        placement.place_tile(self.room2, plane, 0, 1)
        result = self.call(CmdMap(), "/check", caller=self.char1)
        self.assertIn("Unmapped neighbors (canonical exit, no destination tile): 0", result)

    def test_check_player_denied(self):
        result = self.call(CmdMap(), "/check", caller=self.char2)
        self.assertIn("staff permissions", result)
