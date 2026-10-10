# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object
from evennia.utils.test_resources import BaseEvenniaCommandTest, EvenniaTest

from evennia_links import runtime

from . import stalls
from .batch import money_cap
from .commands import CmdBrowse, CmdBuy, CmdMarket, CmdStall
from .models import DroppedItem, LedgerEntry, Listing, ReviewFlag, Storefront
from .reports import reconciliation
from .review import flag_quiet_stalls
from .services import EconomyError, balance, credit


def item(obj):
    return [{"kind": "item", "key": str(obj.pk), "quantity": 1}]


@override_settings(
    DEFAULT_HOME="#1",
    RP_ECONOMY_REVEALED=True,
    RP_ECONOMY_FROZEN=False,
    RP_ECONOMY_MAX_STALLS=1,
    RP_ECONOMY_STALL_SLOTS=2,
    RP_ECONOMY_STALL_CAP_RAISE=100,
    RP_ECONOMY_FEE_POLICY=None,
    RP_ECONOMY_FLAG_REVIEW_HOOK=None,
)
class StallTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.room1.tags.add("market", category="rp_economy")
        self.obj1.location = self.char2
        credit(self.char1, 100)

    def tearDown(self):
        # Explicit recovery is required before deleting a room/owner with stalls.
        for store in Storefront.objects.filter(status="open"):
            with self.captureOnCommitCallbacks(execute=True):
                stalls.close(self.char1, store.pk)
        super().tearDown()

    def listed(self):
        store = stalls.claim(self.char2)
        with self.captureOnCommitCallbacks(execute=True):
            listing = stalls.list_stock(self.char2, store.pk, item(self.obj1), 10)
        return store, listing

    def test_market_tag_slots_and_one_per_character(self):
        self.char2.location = self.room2
        with self.assertRaisesRegex(EconomyError, "market room"):
            stalls.claim(self.char2)
        self.char2.location = self.room1
        store = stalls.claim(self.char2)
        with self.assertRaisesRegex(EconomyError, "maximum"):
            stalls.claim(self.char2)
        self.room1.db.rp_economy_stall_slots = 1
        with self.assertRaisesRegex(EconomyError, "slots"):
            stalls.claim(self.char1)
        stalls.close(self.char2, store.pk)
        self.assertEqual(stalls.claim(self.char1).slot, 1)

    def test_db_prevents_two_open_stalls_in_one_slot(self):
        store = stalls.claim(self.char2)
        holder = create_object("evennia_economy.typeclasses.StallStock")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Storefront.objects.create(
                owner=self.char1,
                room=self.room1,
                holding=holder,
                name="Other",
                slot=store.slot,
                last_active=timezone.now(),
            )

    def test_claim_listing_and_upkeep_fees_and_upkeep_idempotence(self):
        credit(self.char2, 20)
        with override_settings(RP_ECONOMY_FEE_STALL_CLAIM=3, RP_ECONOMY_FEE_LISTING=2):
            store, _listing = self.listed()
        self.assertEqual(balance(self.char2), 15)
        with override_settings(RP_ECONOMY_FEE_STALL_UPKEEP=4):
            stalls.run_upkeep("test-upkeep")
            stalls.run_upkeep("test-upkeep")
        self.assertEqual(balance(self.char2), 11)
        self.assertEqual(LedgerEntry.objects.filter(fee_kind="stall_upkeep").count(), 1)
        with override_settings(RP_ECONOMY_FEE_STALL_UPKEEP=100):
            stalls.run_upkeep("next-upkeep")
            stalls.run_upkeep("next-upkeep")
        self.assertEqual(ReviewFlag.objects.filter(kind="stall_upkeep").count(), 1)
        store.refresh_from_db()
        self.assertEqual((store.status, store.upkeep_period), ("open", "test-upkeep"))

    def test_item_reserved_offline_sale_and_exactly_once(self):
        store, listing = self.listed()
        self.assertEqual(self.obj1.location, store.holding)
        self.assertIsNone(store.holding.location)
        self.assertNotIn(self.obj1, self.char2.contents)
        # No puppet/session is needed for the seller.
        with self.captureOnCommitCallbacks(execute=True):
            stalls.buy(self.char1, listing.pk)
        self.assertEqual(self.obj1.location, self.char1)
        self.assertEqual((balance(self.char1), balance(self.char2)), (90, 10))
        with self.assertRaisesRegex(EconomyError, "no longer"):
            stalls.buy(self.char1, listing.pk)
        self.assertEqual(
            LedgerEntry.objects.filter(listing_id=listing.pk, kind="exchange").count(), 2
        )
        self.assertEqual(reconciliation()["money"], {"minted": 100, "burned": 0, "held": 100})

    def test_directory_uses_optional_item_keywords_only_while_stock_is_active(self):
        store, listing = self.listed()
        self.assertEqual(stalls.directory(self.char1, "weaver"), [])
        with patch.object(
            type(self.obj1), "get_market_keywords", return_value=["Weaver"], create=True
        ):
            self.assertEqual(stalls.directory(self.char1, "weaver"), [(store, [listing])])
            with self.captureOnCommitCallbacks(execute=True):
                stalls.buy(self.char1, listing.pk)
            self.assertEqual(stalls.directory(self.char1, "weaver"), [])
        with patch.object(type(self.obj1), "get_market_keywords", return_value=None, create=True):
            self.assertEqual(stalls.directory(self.char1, "weaver"), [])

    def test_buy_refuses_own_alt_rechecks_current_membership(self):
        _store, listing = self.listed()
        self.account2.characters.add(self.char1)
        with self.assertRaisesRegex(EconomyError, "same account"):
            stalls.buy(self.char1, listing.pk)
        listing.refresh_from_db()
        self.assertEqual(listing.status, "active")
        self.assertEqual(balance(self.char1), 100)

    def test_purchase_item_hooks_receive_the_seller_and_recheck_refusal(self):
        _store, listing = self.listed()
        with (
            patch.object(self.obj1, "at_pre_give", return_value=False),
            self.assertRaises(EconomyError),
        ):
            stalls.buy(self.char1, listing.pk)
        with (
            patch.object(
                self.obj1, "at_pre_give", side_effect=lambda giver, recipient: giver == self.char2
            ) as before,
            patch.object(self.obj1, "at_give") as after,
            self.captureOnCommitCallbacks(execute=True),
        ):
            stalls.buy(self.char1, listing.pk)
        before.assert_called_once_with(self.char2, self.char1)
        after.assert_called_once_with(self.char2, self.char1)

    def test_purchase_must_be_local_and_funded(self):
        _store, listing = self.listed()
        self.char1.location = self.room2
        with self.assertRaisesRegex(EconomyError, "Visit"):
            stalls.buy(self.char1, listing.pk)
        self.char1.location = self.room1
        Listing.objects.filter(pk=listing.pk).update(price=101)
        with self.assertRaisesRegex(EconomyError, "Insufficient"):
            stalls.buy(self.char1, listing.pk)
        self.assertEqual(balance(self.char2), 0)

    def test_seller_fee_comes_from_proceeds_and_failure_rolls_everything_back(self):
        store, listing = self.listed()
        with override_settings(RP_ECONOMY_FEE_SALE=11), self.assertRaises(EconomyError):
            stalls.buy(self.char1, listing.pk)
        self.assertEqual((balance(self.char1), balance(self.char2)), (100, 0))
        listing.refresh_from_db()
        self.assertEqual(listing.status, "active")
        self.assertEqual(self.obj1.location, store.holding)
        with override_settings(RP_ECONOMY_FEE_SALE=2), self.captureOnCommitCallbacks(execute=True):
            stalls.buy(self.char1, listing.pk)
        self.assertEqual(balance(self.char2), 8)
        self.assertEqual(reconciliation()["money"], {"minted": 100, "burned": 2, "held": 98})

    def test_journal_failure_rolls_back_listing_and_purchase(self):
        store = stalls.claim(self.char2)
        with (
            patch("evennia_economy.stalls.journal", side_effect=RuntimeError),
            self.assertRaises(RuntimeError),
        ):
            stalls.list_stock(self.char2, store.pk, item(self.obj1), 10)
        self.assertFalse(Listing.objects.exists())
        self.assertEqual(
            ObjectDB.objects.filter(pk=self.obj1.pk).values_list("db_location_id", flat=True).get(),
            self.char2.pk,
        )
        with self.captureOnCommitCallbacks(execute=True):
            listing = stalls.list_stock(self.char2, store.pk, item(self.obj1), 10)
        with (
            patch("evennia_economy.stalls.journal", side_effect=RuntimeError),
            self.assertRaises(RuntimeError),
        ):
            stalls.buy(self.char1, listing.pk)
        listing.refresh_from_db()
        self.assertEqual(listing.status, "active")
        self.assertEqual(balance(self.char1), 100)
        self.assertEqual(self.obj1.location, store.holding)

    def test_host_reset_can_delete_returned_stock_before_outer_commit(self):
        store, _listing = self.listed()
        with (
            patch("evennia_economy.assets.logger.exception") as error,
            self.captureOnCommitCallbacks(execute=True),
        ):
            stalls.recover(store.pk)
            self.obj1.delete()
        error.assert_not_called()

    def test_unlist_and_staff_remote_close_return_stock_without_fees(self):
        store, listing = self.listed()
        with self.captureOnCommitCallbacks(execute=True):
            stalls.unlist(self.char2, listing.pk)
        self.assertEqual(self.obj1.location, self.char2)
        with self.captureOnCommitCallbacks(execute=True):
            stalls.list_stock(self.char2, store.pk, item(self.obj1), 10)
        self.char1.location = self.room2
        with override_settings(RP_ECONOMY_FROZEN=True), self.captureOnCommitCallbacks(execute=True):
            stalls.close(self.char1, store.pk)
        self.assertEqual(self.obj1.location, self.char2)
        self.assertFalse(store.listings.filter(status="active").exists())
        with self.assertRaises(EconomyError):
            stalls.close(self.char1, store.pk)

    def test_only_owner_lists_edits_unlists_and_players_close_locally(self):
        store, listing = self.listed()
        for operation in (
            lambda: stalls.edit(self.char1, store.pk, name="Stolen"),
            lambda: stalls.unlist(self.char1, listing.pk),
            lambda: stalls.list_stock(self.char1, store.pk, item(self.obj1), 1),
        ):
            with self.assertRaises(EconomyError):
                operation()
        self.char2.location = self.room2
        with self.assertRaisesRegex(EconomyError, "Visit"):
            stalls.close(self.char2, store.pk)

    def test_freeze_and_hidden_gate_mutations_but_not_discovery(self):
        store, listing = self.listed()
        with override_settings(RP_ECONOMY_FROZEN=True):
            self.assertEqual(len(stalls.directory(self.char2)), 1)
            for operation in (
                lambda: stalls.buy(self.char1, listing.pk),
                lambda: stalls.unlist(self.char2, listing.pk),
                lambda: stalls.edit(self.char2, store.pk, name="Frozen"),
                lambda: stalls.close(self.char2, store.pk),
            ):
                with self.assertRaisesRegex(EconomyError, "closed"):
                    operation()
        with (
            override_settings(RP_ECONOMY_REVEALED=False),
            self.assertRaisesRegex(EconomyError, "not available"),
        ):
            stalls.directory(self.char2)

    def test_stall_raise_uses_current_ownership_and_runtime_value(self):
        before = money_cap(self.char2)
        store = stalls.claim(self.char2)
        self.assertEqual(money_cap(self.char2), before + 100)
        runtime.set("RP_ECONOMY_STALL_CAP_RAISE", 42)
        self.assertEqual(money_cap(self.char2), before + 42)
        stalls.close(self.char2, store.pk)
        self.assertEqual(money_cap(self.char2), before)

    def test_quiet_stalls_flag_once_never_close_and_activity_rearms(self):
        store, _listing = self.listed()
        old = timezone.now() - timedelta(weeks=6)
        Storefront.objects.filter(pk=store.pk).update(last_active=old)
        with (
            patch("evennia_economy.review._notify") as notify,
            self.captureOnCommitCallbacks(execute=True),
        ):
            flag_quiet_stalls()
            flag_quiet_stalls()
        notify.assert_called_once()
        self.assertEqual(ReviewFlag.objects.get().kind, "quiet_stall")
        store.refresh_from_db()
        self.assertEqual(store.status, "open")
        self.assertEqual(self.obj1.location, store.holding)
        stalls.note_login(self.char2)
        self.assertEqual(flag_quiet_stalls(), [])
        flag_quiet_stalls(timezone.now() + timedelta(weeks=6))
        self.assertEqual(ReviewFlag.objects.count(), 2)

    def test_drop_get_between_alts_flags_without_blocking_pickup(self):
        self.account2.characters.add(self.char1)
        self.obj1.location = self.room1
        self.assertTrue(DroppedItem.objects.filter(item=self.obj1).exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.obj1.location = self.char1
        self.assertEqual(self.obj1.location, self.char1)
        self.assertEqual(ReviewFlag.objects.get().kind, "floor_pass")
        self.assertFalse(DroppedItem.objects.exists())
        self.obj1.save()
        self.assertEqual(ReviewFlag.objects.count(), 1)

    def test_floor_pickup_by_self_other_account_or_after_window_is_not_flagged(self):
        for recipient, expired in ((self.char2, False), (self.char1, False), (self.char1, True)):
            self.obj1.location = self.char2
            self.obj1.location = self.room1
            if expired:
                self.account2.characters.add(self.char1)
                DroppedItem.objects.filter(item=self.obj1).update(
                    created=timezone.now() - timedelta(days=8)
                )
            self.obj1.location = recipient
            self.assertFalse(ReviewFlag.objects.exists())

    def test_floor_pickup_uses_current_playable_membership(self):
        self.account2.characters.add(self.char1)
        self.obj1.location = self.room1
        self.account2.characters.remove(self.char1)
        self.obj1.location = self.char1
        self.assertFalse(ReviewFlag.objects.exists())

    def test_directory_search_is_global_purchase_local(self):
        store, listing = self.listed()
        stalls.edit(self.char2, store.pk, name="Generic Outfitters", description="Clothing")
        self.char1.location = self.room2
        self.assertEqual(stalls.directory(self.char1, "outfitters")[0][0].pk, store.pk)
        self.assertEqual(stalls.directory(self.char1, self.obj1.key)[0][1][0].pk, listing.pk)
        self.assertEqual(stalls.directory(self.char1, "missing"), [])

    def test_stock_cannot_be_moved_deleted_or_traded_while_listed(self):
        store, listing = self.listed()
        with self.assertRaises(EconomyError):
            self.obj1.location = self.char1
        # Read the persisted row: a refused host-level setter may have changed its cache.
        self.assertEqual(
            ObjectDB.objects.filter(pk=self.obj1.pk).values_list("db_location_id", flat=True).get(),
            store.holding_id,
        )
        with self.assertRaises(EconomyError), transaction.atomic():
            ObjectDB.objects.filter(pk=self.obj1.pk).delete()
        self.assertFalse(store.holding.delete())
        with self.assertRaises(EconomyError), transaction.atomic():
            ObjectDB.objects.filter(pk=self.char2.pk).delete()
        self.assertEqual(Listing.objects.get(pk=listing.pk).status, "active")


@override_settings(
    DEFAULT_HOME="#1", RP_ECONOMY_REVEALED=True, RP_ECONOMY_FROZEN=False, RP_ECONOMY_FEE_POLICY=None
)
class StallCommandTests(BaseEvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.room1.tags.add("market", category="rp_economy")

    def tearDown(self):
        for store in Storefront.objects.filter(status="open"):
            with self.captureOnCommitCallbacks(execute=True):
                stalls.close(self.char1, store.pk)
        super().tearDown()

    def test_command_claim_list_browse_buy_close(self):
        self.call(CmdStall(), "/claim Test stall", "Claimed stall")
        self.obj1.location = self.char1
        with self.captureOnCommitCallbacks(execute=True):
            self.call(CmdStall(), f"/list item:#{self.obj1.pk}=10", "Listing #")
        listing = Listing.objects.get()
        self.call(CmdBrowse(), "", "Stall #")
        self.call(CmdMarket(), "Test", "#")
        credit(self.char2, 10)
        with self.captureOnCommitCallbacks(execute=True):
            self.call(CmdBuy(), str(listing.pk), "Bought listing", caller=self.char2)
        self.call(CmdStall(), "/close", "Stall #")

    def test_bad_input_and_hidden_command_access(self):
        self.call(CmdBuy(), "potato", "invalid literal")
        self.call(CmdStall(), "/unknown", "Unknown stall switch")
        with override_settings(RP_ECONOMY_REVEALED=False):
            for command in (CmdStall(), CmdBrowse(), CmdBuy(), CmdMarket()):
                self.assertFalse(command.access(self.char2))

    def test_explicit_stall_number_when_host_allows_several(self):
        with override_settings(RP_ECONOMY_MAX_STALLS=2):
            stalls.claim(self.char1, name="First")
            second = stalls.claim(self.char1, name="Second")
        self.obj1.location = self.char1
        with self.captureOnCommitCallbacks(execute=True):
            self.call(CmdStall(), f"/list {second.pk}/item:#{self.obj1.pk}=10", "Listing #")
        self.assertEqual(Listing.objects.get().storefront_id, second.pk)
