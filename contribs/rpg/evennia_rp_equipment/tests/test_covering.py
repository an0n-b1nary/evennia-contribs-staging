# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Covering changes presentation while the actual worn gear retains its guards."""

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from evennia.utils.ansi import strip_ansi
from evennia_rp_chargen import services as chargen
from evennia_rp_chargen.services import ChargenError

from evennia_rp_equipment import outfits, services
from evennia_rp_equipment.audit import problems
from evennia_rp_equipment.display import worn_items, worn_lines

from .base import GearTest


@override_settings(RP_EQUIPMENT_SLOT_COVERS={"cloak": ("body",)})
class CoveringTests(GearTest):
    def setUp(self):
        super().setUp()
        self.make_sheet(self.char2, brawn="Mid++")
        self.armour = self.make_item(
            self.char2, "armour", "Brawn +2", slot="body", line="bronze armour"
        )
        self.cloak = self.make_item(self.char2, "cloak", slot="cloak", line="a long cloak")
        self.second = self.make_item(self.char2, "shirt", slot="body", line="a linen shirt")
        for item in (self.armour, self.second, self.cloak):
            services.wear(self.char2, item)

    def test_ordinary_look_hides_all_items_in_covered_slot_but_close_look_includes_them(self):
        seen = strip_ansi(self.char2.return_appearance(self.char1))
        self.assertIn("a long cloak", seen)
        self.assertNotIn("bronze armour", seen)
        self.assertNotIn("a linen shirt", seen)
        self.assertEqual(worn_lines(self.char2), ["a long cloak"])
        self.assertEqual(len(worn_items(self.char2)), 3)
        self.assertIn("bronze armour", worn_lines(self.char2, include_covered=True))
        self.assertNotIn("You see:", seen)  # covered equipment doesn't become loose inventory

    def test_covered_items_keep_build_movement_and_destroy_guards(self):
        with self.assertRaisesMessage(ChargenError, "held by your armour"):
            chargen.set_edge(self.char2, "brawn", 0)
        self.assertFalse(self.armour.move_to(self.char1, quiet=True, move_type="give"))
        with self.assertRaisesMessage(services.GearError, "Remove"):
            services.destroy(self.char2, self.armour)
        # Audits also inspect hidden gear after a direct sheet write outside services.
        self.armour.requirement_data = [{"kind": "pips", "stat": "gone", "count": 1}]
        self.assertTrue(any("armour" in line for line in problems()))

    def test_removal_or_teleport_of_the_covering_item_reveals_inner_lines(self):
        services.remove(self.char2, self.cloak)
        self.assertIn("bronze armour", worn_lines(self.char2))
        services.wear(self.char2, self.cloak)
        self.cloak.move_to(self.room1, quiet=True, move_type="teleport")
        self.assertIn("bronze armour", worn_lines(self.char2))

    def test_saving_keeps_hidden_gear_and_reapplying_restores_covering(self):
        outfits.save(self.char2, "Layers")
        services.remove(self.char2, self.armour)
        services.remove(self.char2, self.cloak)
        outfits.apply(self.char2, "Layers")
        self.assertTrue(self.armour.is_worn)
        self.assertEqual(worn_lines(self.char2), ["a long cloak"])

    @override_settings(RP_EQUIPMENT_SLOT_COVERS={})
    def test_no_configuration_preserves_existing_display(self):
        self.assertEqual(len(worn_lines(self.char2)), 3)

    @override_settings(RP_EQUIPMENT_SLOT_COVERS={" Cloak ": (" BODY ",), "robe": ("cloak",)})
    def test_nested_covering_is_normalized_and_a_hidden_layer_still_covers(self):
        robe = self.make_item(self.char2, "robe", slot="robe")
        services.wear(self.char2, robe)
        self.assertEqual(worn_lines(self.char2), ["robe"])
        services.remove(self.char2, robe)
        self.assertEqual(worn_lines(self.char2), ["a long cloak"])

    def test_invalid_or_cyclic_host_rules_fail_clearly(self):
        for rules in (
            {"body": ("body",)},
            {"body": ("cloak",), "cloak": ("body",)},
            {"cloak": "body"},
        ):
            with (
                self.settings(RP_EQUIPMENT_SLOT_COVERS=rules),
                self.assertRaises(ImproperlyConfigured),
            ):
                worn_lines(self.char2)
