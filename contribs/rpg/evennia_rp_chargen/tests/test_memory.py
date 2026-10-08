# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Live per-tag Memory costs, including rebalances of existing loadouts."""

from django.core.exceptions import ValidationError
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_rp_chargen import abilities
from evennia_rp_chargen.catalog import seed_catalog
from evennia_rp_chargen.commands import CmdAbilities
from evennia_rp_chargen.models import AbilityDefinition
from evennia_rp_chargen.services import ChargenError
from evennia_rp_chargen.sheet import render_sheet

from .test_abilities import CatalogTest


class MemoryTests(CatalogTest, EvenniaCommandTest):
    def test_override_and_fallback_are_resolved_on_existing_copies(self):
        abilities.grant(self.char1, "domain expertise", "climbing")
        abilities.grant(self.char1, "domain expertise", "riddles")
        self.assertEqual(abilities.loadout_used(self.char1), 20)
        AbilityDefinition.objects.filter(key="domain-expertise").update(
            budget_cost_overrides={"climbing": 15}
        )
        self.assertEqual(abilities.loadout_used(self.char1), 25)
        self.assertTrue(all(copy.equipped for copy in abilities.owned(self.char1)))
        self.assertIn("Over budget", render_sheet(self.char1))
        abilities.grant(self.char1, "lucky")
        self.assertFalse(abilities.find_owned(self.char1, "lucky").equipped)
        with self.assertRaises(ChargenError):
            abilities.equip(self.char1, "lucky")
        abilities.unequip(self.char1, "domain expertise", "climbing")
        abilities.equip(self.char1, "lucky")
        self.assertEqual(abilities.loadout_used(self.char1), 15)

    def test_zero_cost_override_and_flaws(self):
        AbilityDefinition.objects.filter(key="domain-expertise").update(
            budget_cost_overrides={"climbing": 0}
        )
        copy, _ = abilities.acquire(self.char1, "domain expertise", "climbing")
        self.assertEqual(copy.budget_cost, 0)
        self.assertTrue(copy.equipped)
        AbilityDefinition.objects.filter(key="domain-ineptitude").update(budget_cost=99)
        abilities.take_flaw(self.char1, "domain ineptitude", "climbing")
        self.assertEqual(abilities.loadout_used(self.char1), 0)

    def test_seed_update_and_validation(self):
        ability = AbilityDefinition.objects.get(key="domain-expertise")
        for overrides in ([], {"climbing": -1}, {"climbing": True}, {"climbing": 1.5}, {"fire": 1}):
            ability.budget_cost_overrides = overrides
            with self.assertRaises(ValidationError):
                ability.clean()
        counts = seed_catalog(
            update=True,
            entries=[
                {
                    "key": ability.key,
                    "name": ability.name,
                    "tag_kind": "domain",
                    "budget_cost_overrides": {"climbing": 17},
                }
            ],
        )
        self.assertEqual(counts["updated"], 1)
        ability.refresh_from_db()
        self.assertEqual(ability.budget_cost_overrides, {"climbing": 17})
        plain = AbilityDefinition.objects.get(key="lucky")
        plain.budget_cost_overrides = {"climbing": 1}
        with self.assertRaises(ValidationError):
            plain.clean()

    def test_info_displays_resolved_cost_and_rejects_wrong_kind(self):
        AbilityDefinition.objects.filter(key="domain-expertise").update(
            budget_cost_overrides={"climbing": 17}
        )
        self.assertIn("Loadout: 17", self.call(CmdAbilities(), "/info domain expertise: climbing"))
        self.assertIn("Loadout: 10", self.call(CmdAbilities(), "/info domain expertise: riddles"))
        self.assertIn("varies by tag", self.call(CmdAbilities(), "/info domain expertise"))
        self.assertIn("Unknown", self.call(CmdAbilities(), "/info domain expertise: fire"))
