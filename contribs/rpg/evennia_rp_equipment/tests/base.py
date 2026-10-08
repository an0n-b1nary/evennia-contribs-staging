# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Shared fixtures for the equipment suites.

Every test runs on evennia_rp_rules' TEST_RULESET (stats Brawn, Brains and
Charm on the tier scale Low / Mid / High, at most 3 + pips and 3 weakness;
domain tags Climbing and Riddles) with the small catalog below.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import override_settings
from evennia.objects.objects import DefaultCharacter
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from evennia_rp_chargen import abilities
from evennia_rp_chargen import services as chargen
from evennia_rp_chargen.catalog import seed_catalog
from evennia_rp_chargen.stats import StatHandler

from evennia_rp_equipment import services
from evennia_rp_equipment.typeclasses import EquipmentCharacterMixin
from evennia_rp_rules.testing import RulesetTestMixin

CATALOG = [
    {
        "key": "domain-expertise",
        "name": "Domain Expertise",
        "category": "domain",
        "tag_kind": "domain",
        "acquisition": "xp",
        "xp_cost": 3,
        "budget_cost": 5,
        "effects": [{"kind": "tag_bonus", "tags": ["@tag"], "score": 2}],
    },
    {
        "key": "domain-ineptitude",
        "name": "Domain Ineptitude",
        "category": "domain",
        "tag_kind": "domain",
        "is_flaw": True,
        "acquisition": "free",
        "effects": [{"kind": "tag_bonus", "tags": ["@tag"], "score": -2}],
    },
    {
        "key": "lucky",
        "name": "Lucky",
        "acquisition": "staff",
        "budget_cost": 5,
        "effects": [{"kind": "score_bonus", "score": 1}],
    },
]

SETTINGS = {
    "RP_CHARGEN_CATALOG_SEED": f"{__name__}.CATALOG",
    "RP_CHARGEN_LOADOUT_BUDGET": 20,
    "RP_CHARGEN_STARTING_ALLOWANCE": 20,
}


class GearCharacter(EquipmentCharacterMixin, DefaultCharacter):
    """A character that shows what it wears."""


GEAR_CHARACTER = f"{__name__}.GearCharacter"


class GearTestMixin(RulesetTestMixin):
    character_typeclass = GEAR_CHARACTER

    def setUp(self):
        super().setUp()
        seed_catalog()

    def make_sheet(self, character, *, finalize=True, **ratings):
        """Give `character` a sheet: unnamed stats default to Low."""
        chargen.ensure_build(character)
        handler = StatHandler(character)
        for key in self.ruleset.stats:
            handler.set(key, self.ruleset.parse_rating(ratings.get(key, "Low")))
        if finalize:
            chargen.finalize(character)
        abilities.set_allowance(character, Decimal(20))
        return chargen.get_build(character)

    def make_item(self, character, name="axe", *requirements, slot="weapon", line=""):
        item = services.make(character, name, slot=slot)
        for text in requirements:
            services.add_requirement(character, item, text)
        if line:
            services.set_worn_line(character, item, line)
        return item

    def rating(self, character, stat="brawn"):
        return StatHandler(character).get(stat).display()


@override_settings(**SETTINGS)
class GearTest(GearTestMixin, EvenniaTest):
    pass


@override_settings(**SETTINGS)
class GearCommandTest(GearTestMixin, EvenniaCommandTest):
    pass
