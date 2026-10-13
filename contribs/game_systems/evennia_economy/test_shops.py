# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real approved shop promotion, sales, archive and explicit stock transfer."""

from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTestMixin, EvenniaTest

from . import shops, stalls
from .commands import CmdShop
from .models import Storefront
from .services import EconomyError, balance, credit


@skipUnless(apps.is_installed("evennia_building"), "Optional Building is absent")
@override_settings(
    BUILDING_REVEALED=True,
    BUILDING_REUSE_ACKNOWLEDGEMENT="Reuse is allowed.",
    LINKS_ROOM_PERMISSION="evennia_building.access.room_permission",
    LINKS_ROOM_OWNER="evennia_building.access.owner_of",
    RP_ECONOMY_REVEALED=True,
    RP_ECONOMY_FROZEN=False,
    RP_ECONOMY_FEE_POLICY=None,
)
class ShopTests(EvenniaCommandTestMixin, EvenniaTest):
    def setUp(self):
        super().setUp()
        from evennia_building import services
        from evennia_building.models import Property

        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.room1.db.room_type = "ic"
        self.room1.db.allow_teleport = "public"
        self.project = services.new_project(self.char2, "Lantern shop", purpose="shop")
        services.attach(self.char2, self.project, self.room1, "lantern shop")
        self.project.refresh_from_db()
        self.submission = services.submit(
            self.char2,
            self.project,
            expected_version=self.project.version,
            acknowledgement="Reuse is allowed.",
        )
        services.review(
            self.char1,
            self.submission,
            expected_revision=self.submission.revision,
            outcome="approved",
            reason="Fits.",
        )
        self.property = Property.objects.get(promotion=self.submission)
        self.store = Storefront.objects.get(property_id=self.property.pk)
        self.char2.location = self.store.room
        self.char1.location = self.store.room
        self.obj1.location = self.char2
        credit(self.char1, 100)

    def tearDown(self):
        for store in Storefront.objects.filter(status="open"):
            stalls.close(self.char1, store.pk)
        super().tearDown()

    def listing(self):
        with self.captureOnCommitCallbacks(execute=True):
            return stalls.list_stock(
                self.char2,
                self.store.pk,
                [{"kind": "item", "key": str(self.obj1.pk), "quantity": 1}],
                10,
            )

    def test_promotion_creates_one_entrance_shop_and_reconcile_is_idempotent(self):
        self.assertEqual(self.store.room_id, self.property.entrance.db_destination_id)
        self.assertEqual(shops.reconcile(self.char1, self.property.pk).pk, self.store.pk)
        self.assertEqual(Storefront.objects.filter(property_id=self.property.pk).count(), 1)
        self.assertEqual(stalls.cap_contribution(None, self.char2), {"stalls": {"money": 0}})

    def test_offline_purchase_uses_shared_stock_and_ledger(self):
        listing = self.listing()
        with self.captureOnCommitCallbacks(execute=True):
            stalls.buy(self.char1, listing.pk)
        self.assertEqual(self.obj1.location, self.char1)
        self.assertEqual(balance(self.char2), 10)

    def test_archive_suspends_sales_and_directory_but_retains_stock(self):
        from evennia_building import lifecycle

        listing = self.listing()
        lifecycle.archive(self.char1, self.property, reason="Pause.")
        self.assertNotIn(self.store.pk, [store.pk for store, _ in stalls.directory(self.char1)])
        self.char1.location = self.store.room
        with self.assertRaisesRegex(EconomyError, "suspended"):
            stalls.buy(self.char1, listing.pk)
        self.assertEqual(self.obj1.location, self.store.holding)
        lifecycle.restore(self.char1, self.property, reason="Return.")
        with self.captureOnCommitCallbacks(execute=True):
            stalls.buy(self.char1, listing.pk)
        self.assertEqual(self.obj1.location, self.char1)

    def test_transfer_requires_stock_disposition_and_returns_stock_to_old_owner(self):
        from evennia_building import services

        listing = self.listing()
        with self.assertRaisesRegex(ValidationError, "stock disposition"):
            services.transfer(
                self.char1,
                self.property,
                self.char1,
                expected_owner=self.char2.pk,
                reason="New keeper.",
            )
        self.property.refresh_from_db()
        self.assertEqual(self.property.owner_id, self.char2.pk)
        with self.captureOnCommitCallbacks(execute=True):
            services.transfer(
                self.char1,
                self.property,
                self.char1,
                expected_owner=self.char2.pk,
                reason="New keeper.",
                stock_disposition="return",
            )
        self.store.refresh_from_db()
        listing.refresh_from_db()
        self.assertEqual(self.store.owner_id, self.char1.pk)
        self.assertEqual(self.obj1.location, self.char2)
        self.assertEqual(listing.status, "returned")

    def test_explicit_transfer_keeps_listings_with_new_owner(self):
        from evennia_building import services

        listing = self.listing()
        services.transfer(
            self.char1,
            self.property,
            self.char1,
            expected_owner=self.char2.pk,
            reason="Stock included.",
            stock_disposition="transfer",
        )
        listing.refresh_from_db()
        self.store.refresh_from_db()
        self.assertEqual(listing.status, "active")
        self.assertEqual(self.store.owner_id, self.char1.pk)
        self.assertEqual(self.obj1.location, self.store.holding)

    def test_failed_stock_return_rolls_back_property_and_shop(self):
        from evennia_building import services

        self.listing()
        with (
            patch(
                "evennia_economy.stalls._return", side_effect=EconomyError("Provider unavailable")
            ),
            self.assertRaises(ValidationError),
        ):
            services.transfer(
                self.char1,
                self.property,
                self.char1,
                expected_owner=self.char2.pk,
                reason="Move.",
                stock_disposition="return",
            )
        self.property.refresh_from_db()
        self.store.refresh_from_db()
        self.assertEqual(self.property.owner_id, self.char2.pk)
        self.assertEqual(self.store.owner_id, self.char2.pk)
        self.assertEqual(self.obj1.location, self.store.holding)

    def test_shop_can_coexist_with_stall_and_close_reopen_without_second_approval(self):
        self.store.room.tags.add("market", category="rp_economy")
        stalls.claim(self.char2)
        stalls.close(self.char2, self.store.pk)
        shops.reopen(self.char2, self.store.pk)
        self.store.refresh_from_db()
        self.assertEqual(self.store.status, "open")
        self.call(
            CmdShop(),
            "",
            f"#{self.store.pk} {self.store.name} in {self.store.room.key}",
            caller=self.char2,
        )

    def test_reconciliation_requires_staff_and_approved_shop(self):
        with self.assertRaises(EconomyError):
            shops.reconcile(self.char2, self.property.pk)
        self.call(
            CmdShop(),
            "/claim",
            "Submit a shop build for staff approval with +build.",
            caller=self.char2,
        )

    def test_approval_fee_is_charged_once_for_deliberate_reconciliation(self):
        # An approved property from a host that had no shop integration.
        self.store.delete()
        credit(self.char2, 20)
        with override_settings(RP_ECONOMY_FEE_SHOP_APPROVAL=7):
            self.store = shops.reconcile(self.char1, self.property.pk)
            shops.reconcile(self.char1, self.property.pk)
        self.assertEqual(balance(self.char2), 13)

    def test_failed_shop_creation_restores_approval_fee(self):
        self.store.delete()
        credit(self.char2, 20)
        with (
            override_settings(RP_ECONOMY_FEE_SHOP_APPROVAL=7),
            patch.object(
                Storefront.objects, "create", side_effect=RuntimeError("Store creation failed")
            ),
            self.assertRaises(RuntimeError),
        ):
            shops.reconcile(self.char1, self.property.pk)
        self.assertEqual(balance(self.char2), 20)
        self.assertFalse(Storefront.objects.filter(property_id=self.property.pk).exists())

    def test_shop_upkeep_is_separate_idempotent_and_archive_skips_it(self):
        credit(self.char2, 30)
        with override_settings(RP_ECONOMY_FEE_SHOP_UPKEEP=3):
            stalls.run_upkeep("shop-test")
            stalls.run_upkeep("shop-test")
        self.assertEqual(balance(self.char2), 27)
        self.property.state = "archived"
        self.property.save()
        with override_settings(RP_ECONOMY_FEE_SHOP_UPKEEP=3):
            stalls.run_upkeep("shop-next")
        self.assertEqual(balance(self.char2), 27)

    def test_direct_owner_mismatch_suspends_sale_and_management(self):
        listing = self.listing()
        type(self.property).objects.filter(pk=self.property.pk).update(owner=self.char1)
        with self.assertRaises(EconomyError):
            stalls.buy(self.char1, listing.pk)
        with self.assertRaises(EconomyError):
            stalls.edit(self.char2, self.store.pk, name="Stale rights")
