# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Ability commands: +abilities, +spend, +upgrade, and the staff +chargen switches.

char1 is a Developer (staff); char2 is an ordinary player.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import override_settings

from evennia_rp_chargen import abilities, services
from evennia_rp_chargen.catalog import seed_catalog
from evennia_rp_chargen.commands import CmdAbilities, CmdChargen, CmdSheet, CmdSpend, CmdUpgrade
from evennia_rp_chargen.models import TagDefinition

from .base import ChargenCommandTest
from .catalog_fixture import CATALOG_SETTINGS


@override_settings(**CATALOG_SETTINGS)
class AbilityCommandTests(ChargenCommandTest):
    def setUp(self):
        super().setUp()
        seed_catalog()

    def test_buy_upgrade_and_view(self):
        self.call(CmdSpend(), "", "Starting allowance: 5.", caller=self.char2)
        self.call(
            CmdSpend(),
            "/ability domain expertise: riddles",
            "You learn Domain Expertise: Riddles and equip it. Paid: 3 starting allowance.",
            caller=self.char2,
        )
        self.call(
            CmdUpgrade(),
            "domain expertise",
            "Domain Expertise: Riddles is now level 2. Paid: 2 starting allowance.",
            caller=self.char2,
        )
        self.call(
            CmdUpgrade(), "domain expertise", "That costs 4, and you have 0", caller=self.char2
        )
        output = self.call(CmdAbilities(), "", None, caller=self.char2)
        self.assertIn("Equipped: Domain Expertise: Riddles 2", output)
        self.assertIn("Loadout: 10 of 20 points used.", output)
        self.assertIn("Starting allowance: 0 of 5 left.", output)
        sheet = self.call(CmdSheet(), "", "Char2", caller=self.char2)
        self.assertIn("Domain Expertise: Riddles 2", sheet)

    def test_equip_and_flaws(self):
        abilities.acquire(self.char2, "domain expertise", "riddles")
        self.call(
            CmdAbilities(),
            "/unequip domain expertise",
            "Domain Expertise: Riddles is no longer equipped.",
            caller=self.char2,
        )
        self.call(
            CmdAbilities(),
            "/equip domain expertise=riddles",
            "Domain Expertise: Riddles is now equipped.",
            caller=self.char2,
        )
        self.call(
            CmdAbilities(),
            "/flaw domain ineptitude: climbing",
            "You now have the flaw Domain Ineptitude: Climbing.",
            caller=self.char2,
        )
        self.call(
            CmdAbilities(),
            "/unflaw domain ineptitude",
            "You no longer have the flaw Domain Ineptitude: Climbing.",
            caller=self.char2,
        )
        self.call(CmdAbilities(), "/equip", "Usage: +abilities/equip", caller=self.char2)
        self.call(CmdAbilities(), "/equip lucky", "You don't have Lucky.", caller=self.char2)

    def test_catalog_and_info(self):
        output = self.call(CmdAbilities(), "/list", "Abilities", caller=self.char2)
        self.assertIn("Domain Expertise: <domain>", output)
        self.assertIn("(3 XP, 10 points, up to level 3)", output)
        self.assertIn("Flaws", output)
        self.call(CmdAbilities(), "/list nonsense", "No abilities match.", caller=self.char2)
        info = self.call(
            CmdAbilities(), "/info domain expertise", "Domain Expertise", caller=self.char2
        )
        self.assertIn("Chosen per domain", info)
        self.assertIn("Upgrades (to level): 2: 2 XP, 3: 4 XP.", info)


@override_settings(**CATALOG_SETTINGS)
class StaffAbilityCommandTests(ChargenCommandTest):
    def setUp(self):
        super().setUp()
        seed_catalog()

    def test_grant_revoke_refund(self):
        self.call(
            CmdChargen(),
            "/grant Char2/lucky",
            "Char2 now has Lucky at level 1 (equipped).",
            caller=self.char1,
        )
        self.call(
            CmdChargen(),
            "/grant Char2/domain expertise: riddles=2",
            "Char2 now has Domain Expertise: Riddles at level 2",
            caller=self.char1,
        )
        self.call(
            CmdChargen(),
            "/grant Char2/lucky=x",
            "The level must be a whole number.",
            caller=self.char1,
        )
        self.call(CmdChargen(), "/grant Char2", "Usage: +chargen/grant", caller=self.char1)
        abilities.acquire(self.char2, "domain expertise", "climbing")
        self.call(
            CmdChargen(),
            "/revoke/refund Char2/domain expertise: climbing",
            "Revoked Domain Expertise: Climbing from Char2. Refunded 3 starting allowance.",
            caller=self.char1,
        )
        self.call(
            CmdChargen(), "/revoke Char2/lucky", "Revoked Lucky from Char2.", caller=self.char1
        )
        self.call(
            CmdChargen(), "/grant Char2/lucky", "You need staff permission", caller=self.char2
        )

    def test_allowance_and_tags(self):
        self.call(
            CmdChargen(),
            "/allowance Char2=12",
            "Char2's starting allowance is now 12 (12 left).",
            caller=self.char1,
        )
        self.assertEqual(services.get_build(self.char2).allowance_total, Decimal(12))
        self.call(
            CmdChargen(),
            "/allowance Char2=default",
            "Char2's starting allowance is now 5",
            caller=self.char1,
        )
        self.call(CmdChargen(), "/allowance Char2=lots", "Give a number", caller=self.char1)
        self.call(
            CmdChargen(),
            "/tag Sea Lore",
            "Added the domain tag Sea Lore ('sea-lore').",
            caller=self.char1,
        )
        self.call(
            CmdChargen(),
            "/tag Sea Lore",
            "A tag with key 'sea-lore' already exists.",
            caller=self.char1,
        )
        self.call(
            CmdChargen(), "/tag Thunder=element", "Added the element tag Thunder", caller=self.char1
        )
        self.assertEqual(TagDefinition.objects.get(key="thunder").kind, "element")
        # A new domain is immediately available to templates.
        abilities.acquire(self.char2, "domain expertise", "sea lore")
