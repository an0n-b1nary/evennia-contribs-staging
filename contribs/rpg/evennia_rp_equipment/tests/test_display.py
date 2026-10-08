# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Worn lines in a character's description, in slot order; worn items out of "You see"."""

from __future__ import annotations

from django.test import override_settings
from evennia.utils.ansi import strip_ansi

from evennia_rp_equipment import services
from evennia_rp_equipment.display import worn_lines

from .base import GearTest


class DisplayTests(GearTest):
    def look(self, target, looker):
        return strip_ansi(target.return_appearance(looker))

    def test_worn_lines_follow_the_description_in_slot_order(self):
        boots = self.make_item(self.char1, "boots", slot="feet", line="scuffed riding boots")
        hat = self.make_item(self.char1, "hat", slot="head", line="a wide-brimmed hat")
        sash = self.make_item(self.char1, "sash", slot="", line="a red sash")
        for item in (boots, sash, hat):
            services.wear(self.char1, item)
        self.assertEqual(
            worn_lines(self.char1),
            ["a wide-brimmed hat", "scuffed riding boots", "a red sash"],
        )
        seen = self.look(self.char1, self.char2)
        self.assertIn("Wearing:\n  a wide-brimmed hat\n  scuffed riding boots\n  a red sash", seen)

    @override_settings(RP_EQUIPMENT_SLOTS=("feet", "head"))
    def test_the_order_is_configurable(self):
        for name, slot in (("hat", "head"), ("boots", "feet")):
            services.wear(self.char1, self.make_item(self.char1, name, slot=slot))
        self.assertEqual(worn_lines(self.char1), ["boots", "hat"])

    def test_an_item_without_a_worn_line_shows_its_name(self):
        services.wear(self.char1, self.make_item(self.char1, "plain ring", slot="accessory"))
        self.assertIn("plain ring", self.look(self.char1, self.char2))

    def test_worn_items_leave_the_you_see_list_and_carried_ones_stay(self):
        services.wear(self.char1, self.make_item(self.char1, "cloak", line="a dark cloak"))
        self.make_item(self.char1, "lantern")
        seen = self.look(self.char1, self.char2)
        self.assertIn("You see: a lantern", seen)
        self.assertNotIn("You see: a cloak", seen)
        self.assertIn("a dark cloak", seen)

    def test_nothing_worn_adds_nothing(self):
        self.assertNotIn("Wearing:", self.look(self.char1, self.char2))
