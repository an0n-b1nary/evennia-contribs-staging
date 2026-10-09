# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reference game seam: terrain display on the seeded map (evennia_maps 0.6)."""

from importlib import import_module

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from evennia.utils.test_resources import EvenniaTest
from rest_framework.test import APIClient
from typeclasses.characters import Character
from typeclasses.rooms import Room

from world.sandbox.tests import SeededSandboxMixin


class TestSeededTerrainDisplay(SeededSandboxMixin, EvenniaTest):
    room_typeclass = Room
    character_typeclass = Character

    def _plane(self):
        from evennia_maps.models import MapPlane
        from world.sandbox import content

        return MapPlane.objects.get(name=content.PLANE_NAME)

    def test_static_map_tints_the_unsprited_terrain_and_shows_the_key(self):
        from evennia_maps.views import PlaneMapView

        plane = self._plane()
        request = RequestFactory().get(f"/map/{plane.pk}/")
        request.user = AnonymousUser()
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        response = PlaneMapView.as_view()(request, pk=plane.pk)
        response.render()
        html = response.content.decode()
        self.assertIn('aria-label="Terrain key"', html)
        self.assertIn("Dry scrub", html)
        # The Causeway's scrub has a colour and no sprite.
        scrub = settings.MAPS_TERRAINS["scrub"]["color"]
        self.assertIn(f'class="evennia-maps-fallback" fill="{scrub}"', html)
        self.assertIn("/static/sandbox/terrain/", html)

    def test_tile_feed_carries_labels_colours_and_region_names(self):
        plane = self._plane()
        client = APIClient()
        client.force_authenticate(self.account)
        response = client.get(f"/api/v1/planes/{plane.pk}/tiles/?page_size=100", format="json")
        self.assertEqual(response.status_code, 200)
        tiles = {tile["room_name"]: tile for tile in response.data["results"]}
        causeway = tiles["The Causeway"]
        self.assertEqual(causeway["terrain_label"], "Dry scrub")
        self.assertEqual(causeway["terrain_color"], settings.MAPS_TERRAINS["scrub"]["color"])
        self.assertEqual(causeway["sprite_url"], "")
        self.assertEqual(tiles["The Warren"]["terrain_label"], "")
        self.assertTrue(any(tile["primary_region_name"] for tile in tiles.values()))
