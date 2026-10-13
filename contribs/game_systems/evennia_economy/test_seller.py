# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Optional backstop availability, price, conservation and rollback."""

from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTestMixin, EvenniaTest

from . import seller
from .commands import CmdBrowse, CmdBuy
from .models import LedgerEntry
from .reports import reconciliation
from .services import EconomyError, balance, credit


@skipUnless(apps.is_installed("evennia_rp_resources"), "Optional Resources is absent")
@override_settings(
    RP_ECONOMY_REVEALED=True,
    RP_ECONOMY_FROZEN=False,
    RP_RESOURCES_REVEALED=True,
    RP_ECONOMY_SYSTEM_SELLER=True,
    RP_ECONOMY_BASIC_PRICES={"wood": 3, "rare": 1, "old": 1},
    RP_ECONOMY_SELLER_PREMIUM=2,
)
class SellerTests(EvenniaCommandTestMixin, EvenniaTest):
    def setUp(self):
        super().setUp()
        from evennia_rp_resources.models import ResourceDefinition

        ResourceDefinition.objects.create(key="wood", name="Wood", category="materials", basic=True)
        ResourceDefinition.objects.create(
            key="rare", name="Rare", category="essences", basic=True, in_trickle=False
        )
        ResourceDefinition.objects.create(
            key="old", name="Old", category="materials", basic=True, archived=True
        )
        self.room1.tags.add("system_seller", category="rp_economy")
        credit(self.char2, 100)

    def test_only_basic_active_trickle_resources_are_sold(self):
        self.assertEqual([(r.key, p) for r, p in seller.catalog(self.char2)], [("wood", 6)])
        for key in ("rare", "old", "missing"):
            with self.assertRaises(EconomyError):
                seller.buy(self.char2, key, 1)

    def test_purchase_burns_money_mints_resources_and_has_unlimited_supply(self):
        from evennia_rp_resources.services import total_held

        seller.buy(self.char2, "wood", 2)
        seller.buy(self.char2, "wood", 2)
        self.assertEqual(balance(self.char2), 76)
        self.assertEqual(total_held(self.char2), 4)
        money = reconciliation()["money"]
        self.assertEqual(money["minted"] - money["burned"], money["held"])
        self.assertEqual(LedgerEntry.objects.filter(kind="system_purchase").count(), 2)

    def test_hidden_disabled_frozen_and_remote_purchases_are_refused(self):
        for changes in (
            {"RP_ECONOMY_SYSTEM_SELLER": False},
            {"RP_ECONOMY_REVEALED": False},
            {"RP_RESOURCES_REVEALED": False},
            {"RP_ECONOMY_FROZEN": True},
        ):
            with override_settings(**changes), self.assertRaises(EconomyError):
                seller.buy(self.char2, "wood", 1)
        self.char2.location = self.room2
        with self.assertRaises(EconomyError):
            seller.buy(self.char2, "wood", 1)
        self.assertEqual(balance(self.char2), 100)

    def test_resource_failure_rolls_back_money_and_ledger(self):
        from evennia_rp_resources.services import ResourceError

        with (
            patch("evennia_rp_resources.services.grant", side_effect=ResourceError("Unavailable")),
            self.assertRaises(ResourceError),
        ):
            seller.buy(self.char2, "wood", 1)
        self.assertEqual(balance(self.char2), 100)
        self.assertFalse(LedgerEntry.objects.filter(kind="system_purchase").exists())

    def test_prices_round_up_and_invalid_amounts_do_not_spend(self):
        with override_settings(RP_ECONOMY_SELLER_PREMIUM=1.5):
            self.assertEqual(seller.buy(self.char2, "wood", 1), 5)
        for amount in (0, -1, True, 2**63):
            with self.assertRaises(EconomyError):
                seller.buy(self.char2, "wood", amount)
        with self.assertRaises(EconomyError):
            seller.buy(self.char2, "wood", 100)
        self.assertEqual(balance(self.char2), 95)

    def test_command_paths(self):
        self.call(CmdBrowse(), "/system", "wood: Wood — 6 coins per unit", caller=self.char2)
        self.call(CmdBuy(), "/system wood=2", "Bought 2 wood for 12 coins.", caller=self.char2)

    def test_guest_cannot_buy_system_resources(self):
        self.char2.tags.add("character", category="guest")
        self.assertEqual(seller.catalog(self.char2), [])
        with self.assertRaises(EconomyError):
            seller.buy(self.char2, "wood", 1)
        self.assertEqual(balance(self.char2), 100)
