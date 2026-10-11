# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""B1 seams under real map, region, social and web-character partners."""

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from evennia.objects.models import ObjectDB
from evennia.utils import create
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_links.rooms import can, owner_of
from evennia_maps.models import MapPlane, RoomTile
from evennia_regions.models import Region, RegionMembership
from evennia_social.commands.roomconfig import _can_configure_room
from evennia_social.mood import can_set_mood
from world.sandbox import content


def demo_rights(actor, room, action):
    return actor == room.db.demo_owner and action == "configure"


def demo_owner(room):
    return room.db.demo_owner


@override_settings(ROOT_URLCONF="world.sandbox.tests")
class BuildingFoundationSeams(EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        call_command("seed_sandbox", verbosity=0)
        self.entry = ObjectDB.objects.get(db_key=content.PRIVATE_PREVIEW_ROOMS[0])
        self.account2.characters.add(self.char2)

    def test_reseeding_rebuilds_exactly_two_private_floors_without_publishing_them(self):
        call_command("seed_sandbox", verbosity=0)
        planes = MapPlane.objects.filter(name__in=content.PRIVATE_PREVIEW_PLANES)
        self.assertEqual(planes.count(), 2)
        self.assertEqual(len({p.zstack for p in planes}), 1)
        self.assertEqual(RoomTile.objects.filter(plane__in=planes).count(), 2)
        page = self.client.get(reverse("evennia_maps:plane-list"))
        self.assertEqual(page.status_code, 200)
        for name in content.PRIVATE_PREVIEW_PLANES:
            self.assertNotIn(name, page.content.decode())

    def test_selected_character_controls_svg_live_api_and_region_room_preview(self):
        self.entry.locks.add(f"control:id({self.char2.pk})")
        region = Region.objects.first()
        RegionMembership.objects.create(region=region, room=self.entry, room_name=self.entry.key)
        plane = MapPlane.objects.get(name=content.PRIVATE_PREVIEW_PLANES[0])
        paths = [
            reverse("evennia_maps:plane-detail", args=[plane.pk]),
            reverse("evennia_maps:plane-live-map", args=[plane.pk]),
            reverse("evennia_regions:room-detail", args=[self.entry.pk]),
            f"/api/v1/planes/{plane.pk}/",
            f"/api/v1/planes/{plane.pk}/tiles/",
            f"/api/v1/planes/{plane.pk}/tiles/{self.entry.pk}/detail/",
        ]
        self.client.force_login(self.account2)
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        region_url = reverse("evennia_regions:region-detail", args=[region.pk])
        self.assertContains(self.client.get(region_url), self.entry.key)
        alt = create.create_object(
            "typeclasses.characters.Character", key="Uninvited previewer", home=self.room1
        )
        self.account2.characters.add(alt)
        self.client.get(alt.web_get_puppet_url() + "?next=/")
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertNotContains(self.client.get(region_url), self.entry.key)
        listing = self.client.get("/api/v1/planes/").json()["results"]
        self.assertNotIn(plane.pk, [row["id"] for row in listing])

    def test_home_map_counts_do_not_disclose_private_drafts(self):
        from django.test import RequestFactory
        from web.website.views.index import _map_summary

        public = _map_summary()
        self.assertEqual(public["plane_count"], MapPlane.objects.count() - 2)
        self.entry.locks.add(f"control:id({self.char2.pk})")
        request = RequestFactory().get("/")
        request.user = self.account2
        owner = _map_summary(request)
        self.assertEqual(owner["plane_count"], public["plane_count"] + 2)
        self.assertEqual(owner["tile_count"], public["tile_count"] + 1)

    @override_settings(
        LINKS_ROOM_PERMISSION=__name__ + ".demo_rights", LINKS_ROOM_OWNER=__name__ + ".demo_owner"
    )
    def test_social_and_future_consumers_share_the_provider(self):
        self.room1.db.demo_owner = self.char2
        self.room1.locks.add("control:false()")
        self.assertTrue(_can_configure_room(self.char2, self.room1))
        self.assertTrue(can_set_mood(self.char2, self.room1))
        self.assertEqual(owner_of(self.room1), self.char2)
        self.assertFalse(can(self.char2, self.room1, "install"))


class BuildingFoundationCommandSeams(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        call_command("seed_sandbox", verbosity=0)

    def test_seeded_transplant_report_is_read_only(self):
        from commands.sandbox import CmdSandbox

        before = list(RoomTile.objects.order_by("pk").values_list("pk", "plane_id", "x", "y"))
        result = self.call(CmdSandbox(), "/transplant", caller=self.char1)
        self.assertIn("Transplant preview (no changes saved)", result)
        self.assertIn(content.PRIVATE_PREVIEW_ROOMS[1], result)
        self.assertEqual(
            list(RoomTile.objects.order_by("pk").values_list("pk", "plane_id", "x", "y")), before
        )
        self.call(CmdSandbox(), "/transplant", "Builder permission is required", caller=self.char2)
