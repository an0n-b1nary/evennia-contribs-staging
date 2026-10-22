# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Single-switch commands through the reference game's cmdset and typeclasses."""

import re

from commands.default_cmdsets import CharacterCmdSet
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTest
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_maps import placement
from evennia_maps.models import MapPlane, RoomTile


class CommandSyntaxSeams(EvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room

    def command(self, key):
        return next(command for command in CharacterCmdSet().commands if command.key == key)

    def test_unhangout_updates_social_directory_and_map_overlay(self):
        from evennia_maps.views import tile_hangout_type

        command = self.command("+roomconfig")
        self.call(command, "/hangout bar")
        self.assertEqual(tile_hangout_type(self.room1), "bar")
        self.call(command, "/hangout/clear")
        self.assertEqual(tile_hangout_type(self.room1), "bar")
        self.call(command, "/unhangout", "Removed Bar hangout designation")
        self.assertIsNone(tile_hangout_type(self.room1))
        result = self.call(self.command("+hangouts"), "/all")
        self.assertNotIn(self.room1.key, result)

    def test_reflow_preview_and_confirmation_preserve_host_room_details(self):
        create_object(
            "typeclasses.exits.Exit", key="north", location=self.room1, destination=self.room2
        )
        self.room2.set_terrain(["urban"])
        plane = MapPlane.objects.create(name="Syntax seam")
        placement.place_tile(self.room1, plane, 0, 0)
        command = self.command("+map")
        self.call(command, f"/reflow/apply #{self.room1.pk}")
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())
        preview = self.call(command, f"/reflow #{self.room1.pk}")
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())
        token = re.search(r"Confirm: \+map/reflow #\d+=(\S+)", preview).group(1)
        self.call(command, f"/reflow #{self.room1.pk}={token}")
        tile = RoomTile.objects.get(room=self.room2)
        self.assertEqual(
            (tile.x, tile.y, tile.room_name, tile.terrain), (0, 1, self.room2.key, "urban")
        )

    def test_activity_switch_reads_real_region_totals(self):
        from django.utils import timezone
        from evennia_rptracker.models import RPSession

        from evennia_regions.models import Region, RegionMembership

        region = Region.create_region("Syntax report region", self.char1)
        RegionMembership.objects.create(region=region, room=self.room1, is_primary=True)
        RPSession.objects.create(
            character=self.char1, room=self.room1, activated_at=timezone.now(), status="active"
        )
        command = self.command("+report")
        result = self.call(command, "/activity 1")
        self.assertIn("Region: Syntax report region", result)
        self.assertNotIn("RP activity:", self.call(command, "activity 1"))
