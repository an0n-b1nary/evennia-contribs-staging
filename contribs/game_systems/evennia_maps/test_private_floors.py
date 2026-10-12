"""A visible anchor must not publish a floor containing only restricted rooms."""

from django.test import override_settings

from evennia_maps import placement
from evennia_maps.models import MapPlane
from evennia_maps.permissions import is_plane_visible, visible_planes
from evennia_maps.tests import MapsTestCase


def selective_floor(room, viewer=None):
    return not room.db.restricted


@override_settings(MAPS_ROOM_VISIBILITY="evennia_maps.test_private_floors.selective_floor")
class TestRestrictedFloor(MapsTestCase):
    def test_restricted_floor_has_no_name_detail_or_list_count(self):
        ground = placement.create_private_stack(self.room1, "Common floor")
        upper = placement.resolve_stacked_plane(ground, 1)
        self.room2.db.restricted = True
        placement.place_tile(self.room2, upper, 0, 0)
        self.assertTrue(is_plane_visible(ground, viewer=self.char2))
        self.assertFalse(is_plane_visible(upper, viewer=self.char2))
        self.assertEqual(
            list(visible_planes(MapPlane.objects.filter(zstack=ground.zstack), viewer=self.char2)),
            [ground],
        )
        self.assertTrue(is_plane_visible(upper, viewer=self.char1, staff=True))
        self.room2.db.restricted = False
        self.assertTrue(is_plane_visible(upper, viewer=self.char2))
