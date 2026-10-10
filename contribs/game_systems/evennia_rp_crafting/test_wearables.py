# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from unittest import skipUnless

from django.apps import apps
from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from . import services
from .commands import CmdCraft
from .errors import CraftingError
from .tests import CraftingFixture


@skipUnless(apps.is_installed("evennia_rp_equipment"), "equipment absent")
class WearableTests(CraftingFixture, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        from evennia_rp_rules.ruleset import reset_ruleset_cache
        from evennia_rp_rules.testing import TEST_RULESET

        override = override_settings(RP_RULES_RULESET=TEST_RULESET)
        override.enable()
        reset_ruleset_cache()
        self.addCleanup(reset_ruleset_cache)
        self.addCleanup(override.disable)
        self.unlock("weaving")

    def wearable(self, config=None, selected=None):
        return services.craft(
            self.char1,
            "weaving",
            "wearable",
            "woven cloak",
            "A striped cloak.",
            config or {"worn_line": "a striped cloak", "slot": "body"},
            selected or {"wood": 1},
        )

    def test_crafted_gear_does_not_consume_plain_cap_and_keeps_its_hallmark(self):
        from evennia_rp_equipment import services as equipment
        from evennia_rp_equipment.commands import render_info

        with override_settings(RP_EQUIPMENT_ITEM_CAP=1):
            equipment.make(self.char1, "plain hat")
            cloak = self.wearable()
            self.assertEqual(equipment.made_count(self.char1), 1)
        hallmark = cloak.get_display_provenance()
        equipment.set_desc(self.char1, cloak, "Revised prose.")
        self.assertIn(hallmark, render_info(cloak, self.char2))
        cloak.move_to(self.char2, quiet=True, move_type="give")
        self.assertTrue(cloak.sealed)
        cloak.move_to(self.char1, quiet=True, move_type="give")
        with self.assertRaises(equipment.GearError):
            equipment.set_desc(self.char1, cloak, "Trying to change it back")

    def test_aura_cost_and_worn_line_use_real_equipment_hooks(self):
        from evennia_rp_equipment import services as equipment

        with self.assertRaises(CraftingError):
            self.wearable({"worn_line": "a striped cloak", "aura_line": "soft sparks"})
        cloak = self.wearable(
            {"worn_line": "a striped cloak", "aura_line": "soft sparks"}, {"wood": 1, "spark": 1}
        )
        equipment.wear(self.char1, cloak)
        self.assertIn("soft sparks", cloak.get_worn_line(self.char2))
        self.assertFalse(cloak.at_pre_drop(self.char1))
        self.assertFalse(cloak.at_pre_give(self.char1, self.char2))
        equipment.remove(self.char1, cloak)
        self.assertTrue(cloak.at_pre_give(self.char1, self.char2))

    def test_requirements_and_build_guard_apply_to_crafted_gear(self):
        from evennia_rp_chargen import services as chargen
        from evennia_rp_chargen.stats import StatHandler
        from evennia_rp_equipment import services as equipment

        chargen.ensure_build(self.char1)
        handler = StatHandler(self.char1)
        for key in ("brawn", "brains", "charm"):
            handler.set(key, handler.ruleset.parse_rating("Mid+" if key == "brawn" else "Low"))
        chargen.finalize(self.char1)
        cloak = self.wearable({"requirements": ["Brawn +1"]})
        equipment.wear(self.char1, cloak)
        with self.assertRaises(chargen.ChargenError):
            chargen.set_edge(self.char1, "brawn", 0)
        equipment.remove(self.char1, cloak)
        chargen.set_edge(self.char1, "brawn", 0)
        with self.assertRaises(equipment.GearError):
            equipment.wear(self.char1, cloak)

    def test_draft_requirements_round_trip_through_persistent_attribute_storage(self):
        for args in (
            "/new weaving/wearable = drafted cloak",
            "/desc = A useful cloak.",
            "/line = a useful cloak",
            "/require = Brawn +1",
            "/require = Brains +1",
            "/unrequire 2",
            "/resources = wood:1",
        ):
            self.call(CmdCraft(), args, "Craft draft saved")
        self.call(CmdCraft(), "", "Draft: drafted cloak")
        self.call(CmdCraft(), "/finish", "You craft drafted cloak")
        item = self.char1.search("drafted cloak")
        self.assertEqual(item.requirement_data, [{"kind": "pips", "stat": "brawn", "count": 1}])
