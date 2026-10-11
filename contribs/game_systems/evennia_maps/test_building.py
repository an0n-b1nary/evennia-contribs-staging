# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Private stacks and exact, atomic cross-plane translation."""

from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import RequestFactory, override_settings
from evennia.utils import create

from evennia_maps import placement
from evennia_maps.models import MapPlane, RoomTile
from evennia_maps.permissions import is_plane_visible, is_room_web_visible
from evennia_maps.tests import MapsApiTestCase, MapsTestCase, _make_plane, _make_room
from evennia_maps.transplant import apply_transplant, plan_transplant


def controlled_preview(room, viewer):
    if room.db.allow_teleport == "secret":
        return bool(viewer and room.access(viewer, "control"))
    return True


def broken_preview(room, viewer):
    raise TypeError("callback body failed")


class TestTransplants(MapsTestCase):
    def setUp(self):
        super().setUp()
        self.source = placement.create_private_stack(self.room1, "Draft")
        self.target = _make_plane("World", zstack="world")
        placement.place_tile(self.room2, self.target, 10, 20)
        self.extra = _make_room("Second draft room")
        placement.place_tile(self.extra, self.source, 1, 0)
        self.rooms = [self.room1, self.extra]

    def plan(self):
        return plan_transplant(
            self.rooms, entry_room=self.room1, anchor_room=self.room2, direction_name="east"
        )

    def positions(self):
        return list(
            RoomTile.objects.order_by("room_id").values_list("pk", "room_id", "plane_id", "x", "y")
        )

    def test_dry_run_then_apply_preserves_tile_identity_and_relative_geometry(self):
        before = self.positions()
        plan = self.plan()
        self.assertEqual(self.positions(), before)
        self.assertFalse(plan.conflicts)
        self.assertEqual([(m.x, m.y) for m in plan.moves], [(11, 20), (12, 20)])
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            self.assertEqual(apply_transplant(plan, actor=self.char1), 2)
        self.assertEqual(len(callbacks), 2)
        self.assertEqual([p[:2] for p in self.positions()], [p[:2] for p in before])
        self.assertEqual(RoomTile.objects.get(room=self.extra).plane, self.target)
        with self.assertRaises(ValidationError):
            apply_transplant(plan)

    def test_collision_blocks_every_move(self):
        blocker = _make_room("World blocker")
        placement.place_tile(blocker, self.target, 12, 20)
        before = self.positions()
        plan = self.plan()
        self.assertTrue(plan.conflicts)
        with self.assertRaises(ValidationError):
            apply_transplant(plan)
        self.assertEqual(self.positions(), before)

    def test_stale_empty_cell_occupied_after_preview(self):
        plan = self.plan()
        placement.place_tile(_make_room("Late blocker"), self.target, 11, 20)
        before = self.positions()
        with self.assertRaisesMessage(ValidationError, "map changed"):
            apply_transplant(plan)
        self.assertEqual(self.positions(), before)

    def test_stale_source_anchor_pin_exit_and_floor_state(self):
        for change in ("source", "anchor", "pin", "exit", "archive"):
            with self.subTest(change=change), transaction.atomic():
                plan = self.plan()
                if change == "source":
                    placement.move_tile(self.extra, 2, 0)
                elif change == "anchor":
                    placement.move_tile(self.room2, 20, 20)
                elif change == "pin":
                    placement.set_pin(self.extra, True)
                elif change == "exit":
                    create.create_object(
                        "evennia.objects.objects.DefaultExit",
                        key="east",
                        location=self.room2,
                        destination=self.room1,
                    )
                else:
                    self.target.is_archived = True
                    self.target.save()
                before = self.positions()
                with self.assertRaises(ValidationError):
                    apply_transplant(plan)
                self.assertEqual(self.positions(), before)
                transaction.set_rollback(True)
        self.target.refresh_from_db()

    def test_adjacency_is_a_warning_and_connected_neighbors_are_excluded(self):
        neighbor = _make_room("Neighbor")
        placement.place_tile(neighbor, self.target, 12, 21)
        plan = self.plan()
        self.assertIn(neighbor.pk, [a.neighbor_room_id for a in plan.adjacency])
        self.assertNotIn(
            self.room2.pk,
            [a.neighbor_room_id for a in plan.adjacency if a.room_id == self.room1.pk],
        )
        self.assertFalse(plan.conflicts)
        self.assertEqual(apply_transplant(plan), 2)

    def test_floors_remain_pending_until_apply_and_are_translated(self):
        upper = _make_room("Upper room")
        source_floor = placement.resolve_stacked_plane(self.source, 1)
        placement.place_tile(upper, source_floor, 1, 0)
        self.rooms.append(upper)
        count = MapPlane.all_objects.count()
        plan = self.plan()
        self.assertEqual(MapPlane.all_objects.count(), count)
        self.assertTrue(any(isinstance(m.plane, placement.PendingPlane) for m in plan.moves))
        apply_transplant(plan)
        tile = RoomTile.objects.get(room=upper)
        self.assertEqual(
            (tile.plane.zstack, tile.plane.elevation, tile.x, tile.y), ("world", 1, 12, 20)
        )

    def test_failed_later_write_rolls_back_all_moves_and_pending_floor(self):
        upper = _make_room("Failing upper room")
        placement.place_tile(upper, placement.resolve_stacked_plane(self.source, 1), 0, 0)
        self.rooms.append(upper)
        before = self.positions()
        plane_count = MapPlane.all_objects.count()
        plan = self.plan()
        real_move = placement.move_tile

        def fail_upper(room, *args, **kwargs):
            if room == upper:
                raise RuntimeError("upper write failed after floor creation")
            return real_move(room, *args, **kwargs)

        with (
            self.captureOnCommitCallbacks(execute=True) as callbacks,
            patch.object(placement, "move_tile", side_effect=fail_upper),
            self.assertRaises(RuntimeError),
        ):
            apply_transplant(plan)
        self.assertEqual(self.positions(), before)
        self.assertEqual(MapPlane.all_objects.count(), plane_count)
        self.assertEqual(callbacks, [])

    def test_outer_rollback_sends_no_notifications(self):
        receiver = patch("evennia_maps.signals.tile_placed.send")
        with receiver as send, self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                apply_transplant(self.plan())
                transaction.set_rollback(True)
            send.assert_not_called()

    def test_pin_and_invalid_geometry_block(self):
        placement.set_pin(self.extra, True)
        self.assertTrue(self.plan().conflicts)
        placement.set_pin(self.extra, False)
        create.create_object(
            "evennia.objects.objects.DefaultExit",
            key="north",
            location=self.room1,
            destination=self.extra,
        )
        self.assertTrue(self.plan().conflicts)

    def test_alias_occupies_attachment_direction(self):
        create.create_object(
            "evennia.objects.objects.DefaultExit",
            key="road",
            aliases=["e"],
            location=self.room2,
            destination=self.room1,
        )
        self.assertTrue(self.plan().conflicts)

    def test_explicit_room_selection_leaves_other_stack_tiles_alone(self):
        interior = _make_room("Unselected interior")
        placement.place_tile(interior, self.source, 5, 5)
        apply_transplant(self.plan())
        self.assertEqual(RoomTile.objects.get(room=interior).plane, self.source)

    def test_invalid_input_and_multifloor_standalone_target_are_refused(self):
        for name in ("in", "up", "bogus"):
            with self.assertRaises(ValidationError):
                plan_transplant(
                    self.rooms, entry_room=self.room1, anchor_room=self.room2, direction_name=name
                )
        upper = _make_room("Upper")
        placement.place_tile(upper, placement.resolve_stacked_plane(self.source, 1), 0, 0)
        self.rooms.append(upper)
        self.target.zstack = ""
        self.target.save()
        self.assertTrue(self.plan().conflicts)


@override_settings(MAPS_ROOM_VISIBILITY=__name__ + ".controlled_preview")
class TestPrivateStacks(MapsTestCase):
    def setUp(self):
        super().setUp()
        self.room1.db.allow_teleport = "secret"
        self.room1.locks.add(f"control:id({self.char1.pk})")
        self.plane = placement.create_private_stack(self.room1, "Private preview")

    def test_unique_stacks_and_floor_privacy_inheritance(self):
        other = placement.create_private_stack(self.room2, "Other preview")
        self.assertNotEqual(other.zstack, self.plane.zstack)
        floor = placement.resolve_stacked_plane(self.plane, 1)
        self.assertEqual(floor.visibility_room, self.room1)
        self.assertTrue(is_plane_visible(floor, viewer=self.char1))
        self.assertFalse(is_plane_visible(floor, viewer=self.char2))
        self.assertFalse(is_plane_visible(floor))
        self.assertTrue(is_plane_visible(floor, staff=True))

    def test_deleting_anchor_cannot_publish_empty_or_other_floor(self):
        floor = placement.resolve_stacked_plane(self.plane, 1)
        self.room1.delete()
        self.assertFalse(MapPlane.all_objects.filter(pk__in=[self.plane.pk, floor.pk]).exists())

    @override_settings(MAPS_ROOM_VISIBILITY=__name__ + ".broken_preview")
    def test_callback_body_typeerror_fails_closed(self):
        self.assertFalse(is_room_web_visible(self.room1, self.char1))
        self.assertFalse(is_plane_visible(self.plane, viewer=self.char1))


@override_settings(MAPS_ROOM_VISIBILITY=__name__ + ".controlled_preview")
class TestPrivateWeb(MapsApiTestCase):
    def setUp(self):
        super().setUp()
        self.account2.characters.add(self.char2)
        self.room1.db.allow_teleport = "secret"
        self.room1.locks.add(f"control:id({self.char2.pk})")
        self.plane = placement.create_private_stack(self.room1, "Hidden workshop")
        self.floor = placement.resolve_stacked_plane(self.plane, 1)
        self.public = _make_plane("Public street", zstack="world")
        placement.place_tile(self.room2, self.public, 0, 0)
        create.create_object(
            "evennia.objects.objects.DefaultExit",
            key="workshop",
            location=self.room2,
            destination=self.room1,
        )

    def test_unauthorized_private_metadata_is_hidden_from_api(self):
        self.room1.locks.add(f"control:id({self.char1.pk})")
        response = self.client2.get(self.base + "/planes/", format="json")
        ids = [row["id"] for row in response.data["results"]]
        self.assertNotIn(self.plane.pk, ids)
        self.assertNotIn(self.floor.pk, ids)
        for plane in (self.plane, self.floor):
            for suffix in ("/", "/tiles/"):
                self.assertEqual(
                    self.client2.get(f"{self.base}/planes/{plane.pk}{suffix}").status_code, 404
                )
        tiles = self.client2.get(f"{self.base}/planes/{self.public.pk}/tiles/", format="json").data[
            "results"
        ]
        self.assertIsNone(tiles[0]["portal_plane_id"])

    def test_offline_owner_gets_tiles_bounds_and_portal_into_private_stack(self):
        response = self.client2.get(f"{self.base}/planes/{self.plane.pk}/", format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["bounds"], {"min_x": 0, "max_x": 0, "min_y": 0, "max_y": 0})
        tiles = self.client2.get(f"{self.base}/planes/{self.public.pk}/tiles/", format="json").data[
            "results"
        ]
        self.assertEqual(tiles[0]["portal_plane_id"], self.plane.pk)
        self.assertEqual(self.client2.get(f"{self.base}/planes/{self.floor.pk}/").status_code, 200)

    def test_interior_portal_links_back_to_the_world(self):
        tiles = self.client2.get(f"{self.base}/planes/{self.plane.pk}/tiles/", format="json").data[
            "results"
        ]
        self.assertEqual(tiles[0]["portal_plane_id"], self.public.pk)

    def test_private_html_routes_and_layers_use_the_same_rule(self):
        from django.contrib.auth.models import AnonymousUser
        from django.http import Http404

        from evennia_maps.views import PlaneListView, PlaneLiveMapView, PlaneMapView

        factory = RequestFactory()
        request = factory.get("/map/")
        request.session = {}
        request.user = AnonymousUser()
        response = PlaneListView.as_view()(request)
        response.render()
        self.assertNotIn(self.plane.name, response.content.decode())
        for view in (PlaneMapView, PlaneLiveMapView):
            with self.assertRaises(Http404):
                view.as_view()(request, pk=self.plane.pk)
        request.session = {}
        request = factory.get("/map/")
        request.session = {}
        request.user = self.account2
        response = PlaneLiveMapView.as_view()(request, pk=self.plane.pk)
        self.assertEqual(
            {layer["id"] for layer in response.context_data["layers"]},
            {self.plane.pk, self.floor.pk},
        )
        response.render()
        from django.utils.html import escapejs

        self.assertIn(escapejs(self.floor.name), response.content.decode())
        svg = PlaneMapView.as_view()(request, pk=self.plane.pk)
        svg.render()
        self.assertIn(self.room1.key, svg.content.decode())

    def test_a_hidden_sibling_floor_is_not_named(self):
        self.floor.visibility_room = self.room2
        self.floor.save()
        self.room2.db.allow_teleport = "secret"
        self.room2.locks.add(f"control:id({self.char1.pk})")
        from evennia_maps.views import PlaneLiveMapView

        request = RequestFactory().get("/map/")
        request.session = {}
        request = RequestFactory().get("/map/")
        request.session = {}
        request.user = self.account2
        response = PlaneLiveMapView.as_view()(request, pk=self.plane.pk)
        self.assertEqual(
            [layer["id"] for layer in response.context_data["layers"]], [self.plane.pk]
        )
