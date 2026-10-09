# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real terrain and absence seams for a fresh resources host."""

from importlib.util import find_spec

from django.apps import apps
from django.conf import settings
from django.test import override_settings
from evennia.objects.objects import DefaultRoom
from evennia.utils.test_resources import EvenniaTest
from evennia_rp_resources.batch import run_weekly_batch
from evennia_rp_resources.gathering import pool, terrain_for
from evennia_rp_resources.models import ResourceDefinition
from evennia_rp_resources.services import total_held

if apps.is_installed("evennia_maps"):
    from evennia_maps.typeclasses import MapsRoomMixin

    class ResourcePartnerRoom(MapsRoomMixin, DefaultRoom):
        pass
else:
    ResourcePartnerRoom = DefaultRoom


class ResourcePartnerTests(EvenniaTest):
    room_typeclass = ResourcePartnerRoom

    def test_real_installed_and_importable_state(self):
        for name in settings.RESOURCES_ABSENT_PARTNERS:
            self.assertFalse(apps.is_installed(name))
            self.assertIsNone(find_spec(name))

    @override_settings(
        MAPS_TERRAIN_PRECEDENCE=["forest"],
        RP_RESOURCES_OPEN_TERRAINS=None,
        BASE_ROOM_TYPECLASS="evennia.objects.objects.DefaultRoom",
    )
    def test_real_terrain_pool_and_passive_batch(self):
        if apps.is_installed("evennia_maps"):
            self.room1.set_terrain({"forest"})
        else:
            self.room1.tags.add("forest", category="terrain")
        self.assertEqual(terrain_for(self.room1), "forest")
        ResourceDefinition.objects.create(
            key="wood", name="Wood", category="materials", terrains=["forest"]
        )
        ResourceDefinition.objects.create(
            key="grain", name="Grain", category="provisions", terrains=[]
        )
        self.assertEqual({resource.key for resource in pool()}, {"wood", "grain"})
        self.account2.characters.add(self.char2)
        result = run_weekly_batch("2026-W40")
        self.assertEqual(result["errors"], [])
        self.assertEqual(total_held(self.char2), 6)
        self.assertEqual(run_weekly_batch("2026-W40")["characters"], {})
