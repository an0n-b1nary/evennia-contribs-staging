# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from evennia.utils.create import create_object
from evennia.utils.test_resources import BaseEvenniaCommandTest, EvenniaTest

from evennia_links import runtime

from . import assets, batch, conf
from .commands import CmdAccept, CmdBalance, CmdEconomy, CmdGive, CmdOffer
from .exchange import accept_offer, cancel_offer, create_offer
from .models import LedgerEntry, Offer, Purse, ReviewFlag, StipendPayment, UBIPayment
from .reports import account_accrual, reconciliation
from .services import EconomyError, balance, charge_fee, credit, debit, same_account
from .summary import notify_economy_summary


def money(amount):
    return [{"kind": "money", "key": "", "quantity": amount}]


def item(obj):
    return [{"kind": "item", "key": str(obj.pk), "quantity": 1}]


@override_settings(
    DEFAULT_HOME="#1",
    RP_ECONOMY_REVEALED=True,
    RP_ECONOMY_FROZEN=False,
    RP_ECONOMY_WEEKLY_AMOUNT=100,
    RP_ECONOMY_BASE_CAP_WEEKS=5,
    RP_ECONOMY_STARTING_STIPEND=0,
    RP_ECONOMY_REVEAL_STIPEND=0,
    RP_ECONOMY_FEE_POLICY=None,
    RP_ECONOMY_FLAG_REVIEW_HOOK=None,
    RP_ECONOMY_ELIGIBLE=None,
    RP_ECONOMY_TAPER_FRACTION=0.8,
)
class EconomyTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.obj1.location = self.char1

    def gift(self, giver, recipient, spec):
        offer = create_offer(giver, recipient, spec)
        return accept_offer(recipient, offer.pk)

    def test_credit_debit_whole_amounts_and_journal(self):
        credit(self.char1, 10, by=self.char2)
        debit(self.char1, 3, note="Used")
        self.assertEqual(balance(self.char1), 7)
        self.assertEqual(list(LedgerEntry.objects.values_list("amount", flat=True)), [10, 3])
        self.assertEqual(LedgerEntry.objects.first().by_id, self.char2.pk)

    def test_invalid_and_short_amounts_are_read_only(self):
        for amount in (0, -1, True, 1.2, "3", 2**63):
            with self.subTest(amount=amount), self.assertRaises(EconomyError):
                credit(self.char1, amount)
        with self.assertRaises(EconomyError):
            debit(self.char1, 1)
        self.assertFalse(Purse.objects.exists())
        self.assertFalse(LedgerEntry.objects.exists())

    def test_db_rejects_negative_and_duplicate_purse(self):
        credit(self.char1, 10)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Purse.objects.filter(character=self.char1).update(balance=-1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Purse.objects.create(character=self.char1)

    def test_credit_overflow_refused_without_partial_ledger(self):
        credit(self.char1, 2**63 - 1)
        with self.assertRaises(EconomyError):
            credit(self.char1, 1)
        self.assertEqual(balance(self.char1), 2**63 - 1)
        self.assertEqual(LedgerEntry.objects.count(), 1)

    def test_ledger_failure_rolls_back_money(self):
        with (
            patch.object(LedgerEntry.objects, "create", side_effect=RuntimeError),
            self.assertRaises(RuntimeError),
        ):
            credit(self.char1, 10)
        self.assertEqual(balance(self.char1), 0)

    def test_outer_transaction_rolls_back_currency(self):
        with self.assertRaises(RuntimeError), transaction.atomic():
            credit(self.char1, 10)
            raise RuntimeError
        self.assertFalse(LedgerEntry.objects.exists())
        self.assertEqual(balance(self.char1), 0)

    def test_offline_passive_income_no_rp_requirement(self):
        result = batch.run_weekly_batch("test")
        self.assertEqual(result["errors"], [])
        self.assertEqual(set(result["characters"]), {self.char1.pk, self.char2.pk})
        self.assertEqual(balance(self.char2), 100)
        self.assertNotIn(self.obj1.pk, result["characters"])

    def test_shared_eligibility_and_first_eligibility_stipend(self):
        with override_settings(RP_ECONOMY_ELIGIBLE=lambda c: False, RP_ECONOMY_STARTING_STIPEND=20):
            self.assertEqual(batch.ensure_stipends(self.char2), {})
            self.assertEqual(batch.run_weekly_batch("test")["characters"], {})
        with override_settings(RP_ECONOMY_STARTING_STIPEND=20):
            self.assertEqual(batch.ensure_stipends(self.char2), {"starting": 20})
            self.assertEqual(batch.ensure_stipends(self.char2), {})
        self.assertEqual(balance(self.char2), 20)

    def test_reveal_stipend_once_even_after_hide_and_reveal(self):
        with override_settings(
            RP_ECONOMY_REVEALED=False, RP_ECONOMY_STARTING_STIPEND=20, RP_ECONOMY_REVEAL_STIPEND=30
        ):
            batch.run_weekly_batch("test")
            self.assertEqual(balance(self.char2), 120)
            self.assertFalse(StipendPayment.objects.filter(kind="reveal").exists())
            with self.captureOnCommitCallbacks(execute=True):
                runtime.set("RP_ECONOMY_REVEALED", True)
            self.assertEqual(balance(self.char2), 150)
            runtime.set("RP_ECONOMY_REVEALED", False)
            with self.captureOnCommitCallbacks(execute=True):
                runtime.set("RP_ECONOMY_REVEALED", True)
            self.assertEqual(balance(self.char2), 150)

    def test_never_hidden_game_pays_no_reveal_stipend(self):
        with override_settings(RP_ECONOMY_STARTING_STIPEND=20, RP_ECONOMY_REVEAL_STIPEND=30):
            batch.run_weekly_batch("test")
            batch.run_stipends()
        self.assertEqual(balance(self.char2), 120)
        self.assertFalse(StipendPayment.objects.filter(kind="reveal").exists())

    def test_reveal_stipend_goes_to_those_eligible_at_the_reveal_only(self):
        late = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Late", location=self.room1
        )
        with override_settings(RP_ECONOMY_STARTING_STIPEND=20, RP_ECONOMY_REVEAL_STIPEND=30):
            with self.captureOnCommitCallbacks(execute=True):
                runtime.set("RP_ECONOMY_REVEALED", False)
            batch.ensure_stipends(self.char1)  # paid while hidden
            with self.captureOnCommitCallbacks(execute=True):
                runtime.set("RP_ECONOMY_REVEALED", True)
            # char2 never logged in while hidden but was eligible at the reveal.
            self.assertEqual((balance(self.char1), balance(self.char2)), (50, 50))
            self.account2.characters.add(late)  # first eligible after the reveal
            self.assertEqual(batch.ensure_stipends(late), {"starting": 20})
            batch.run_weekly_batch("test")
            batch.run_stipends()
        self.assertEqual(balance(late), 120)
        self.assertFalse(StipendPayment.objects.filter(character=late, kind="reveal").exists())

    def test_reveal_sweep_failure_is_made_good_later(self):
        with override_settings(RP_ECONOMY_STARTING_STIPEND=20, RP_ECONOMY_REVEAL_STIPEND=30):
            with self.captureOnCommitCallbacks(execute=True):
                runtime.set("RP_ECONOMY_REVEALED", False)
            batch.ensure_stipends(self.char2)
            with (
                patch("evennia_economy.batch.credit", side_effect=RuntimeError),
                self.assertLogs("evennia", level="ERROR"),
                self.captureOnCommitCallbacks(execute=True),
            ):
                runtime.set("RP_ECONOMY_REVEALED", True)
            self.assertEqual(balance(self.char2), 20)
            self.assertEqual(batch.ensure_stipends(self.char2), {"reveal": 30})
        self.assertEqual(balance(self.char2), 50)

    def test_reveal_sweep_waits_while_frozen(self):
        with override_settings(RP_ECONOMY_STARTING_STIPEND=0, RP_ECONOMY_REVEAL_STIPEND=30):
            with self.captureOnCommitCallbacks(execute=True):
                runtime.set("RP_ECONOMY_REVEALED", False)
            runtime.set("RP_ECONOMY_FROZEN", True)
            with self.captureOnCommitCallbacks(execute=True):
                runtime.set("RP_ECONOMY_REVEALED", True)
            self.assertIsNone(batch.revealed_at())
            with self.captureOnCommitCallbacks(execute=True):
                runtime.set("RP_ECONOMY_FROZEN", False)
        self.assertIsNotNone(batch.revealed_at())
        self.assertEqual((balance(self.char1), balance(self.char2)), (30, 30))

    def batch_script(self):
        from evennia.utils.create import create_script

        return create_script(
            "evennia_economy.scripts.EconomyBatchScript", key="economy_batch", autostart=False
        )

    def test_scheduler_tick_runs_no_stipend_sweep(self):
        calls = []

        def eligible(character):
            calls.append(character.pk)
            return True

        script = self.batch_script()
        with override_settings(RP_ECONOMY_ELIGIBLE=eligible):
            script.at_repeat()
            self.assertEqual(sorted(calls), sorted([self.char1.pk, self.char2.pk]))
            calls.clear()
            for _ in range(3):
                script.at_repeat()
        self.assertEqual(calls, [])

    def test_ensure_stipends_checks_one_character_only(self):
        calls = []

        def eligible(character):
            calls.append(character.pk)
            return True

        with override_settings(RP_ECONOMY_ELIGIBLE=eligible, RP_ECONOMY_STARTING_STIPEND=5):
            batch.ensure_stipends(self.char2)
            batch.ensure_stipends(self.char2)  # already paid: no eligibility check at all
        self.assertEqual(calls, [self.char2.pk])

    def test_scheduler_retries_only_failures_with_backoff(self):
        script = self.batch_script()
        real_credit = batch.credit
        attempts = []

        def flaky(character, amount, **kwargs):
            attempts.append(character.pk)
            if character.pk == self.char2.pk:
                raise RuntimeError("Credit failed")
            return real_credit(character, amount, **kwargs)

        with (
            patch("evennia_economy.batch.credit", side_effect=flaky),
            self.assertLogs("evennia", level="ERROR"),
        ):
            script.at_repeat()
            script.at_repeat()  # within the backoff: nothing reruns
        self.assertEqual(sorted(attempts), sorted([self.char1.pk, self.char2.pk]))
        pending = script.db.batch_state["pending"]
        self.assertEqual([entry["ids"] for entry in pending], [[self.char2.pk]])
        with patch("evennia_links.periodic.time.time", return_value=pending[0]["due"]):
            script.at_repeat()
        self.assertEqual((balance(self.char1), balance(self.char2)), (100, 100))
        self.assertEqual(script.db.batch_state["pending"], [])

    def test_periods_missed_while_frozen_are_paid_when_unfrozen(self):
        script = self.batch_script()
        with override_settings(RP_ECONOMY_FROZEN=True):
            for week in ("2026-W40", "2026-W41"):
                with patch("evennia_economy.batch.period_key", return_value=week):
                    script.at_repeat()
        self.assertFalse(UBIPayment.objects.exists())
        with patch("evennia_economy.batch.period_key", return_value="2026-W41"):
            script.at_repeat()
        self.assertEqual(
            sorted(UBIPayment.objects.filter(character=self.char2).values_list("week", flat=True)),
            ["2026-W40", "2026-W41"],
        )

    def test_scripts_from_before_the_queue_keep_their_last_period(self):
        script = self.batch_script()
        script.db.last_batch_week = "2026-W40"
        with patch("evennia_economy.batch.period_key", return_value="2026-W40"):
            script.at_repeat()
        self.assertFalse(UBIPayment.objects.exists())

    def test_preview_matches_payment_without_writes(self):
        with override_settings(RP_ECONOMY_STARTING_STIPEND=50, RP_ECONOMY_REVEAL_STIPEND=30):
            preview = batch.run_weekly_batch("test", dry_run=True)
            self.assertFalse(Purse.objects.exists())
            self.assertFalse(StipendPayment.objects.exists())
            self.assertEqual(preview, batch.run_weekly_batch("test"))

    def test_ubi_repeat_cannot_refill_after_spend(self):
        batch.run_weekly_batch("test")
        debit(self.char2, 20)
        self.assertEqual(batch.run_weekly_batch("test")["characters"], {})
        self.assertEqual(balance(self.char2), 80)

    def test_cap_records_zero_and_never_decays(self):
        credit(self.char2, 600)
        batch.run_weekly_batch("test")
        self.assertEqual(balance(self.char2), 600)
        self.assertEqual(UBIPayment.objects.get(character=self.char2).amount, 0)
        debit(self.char2, 200)
        batch.run_weekly_batch("test")
        self.assertEqual(balance(self.char2), 400)

    def test_taper_and_base_cap_tracks_ubi_weeks(self):
        self.assertEqual(
            [batch.income_amount(n, 500) for n in (0, 400, 450, 499, 500, 600)],
            [100, 100, 50, 1, 0, 0],
        )
        self.assertEqual(batch.money_cap(self.char2), 500)
        with override_settings(RP_ECONOMY_WEEKLY_AMOUNT=200):
            self.assertEqual(batch.money_cap(self.char2), 1000)

    def test_ownership_raise_optional_and_coin_denominated(self):
        def workshop(**kwargs):
            return {"workshop": {"money": 300}}

        runtime.cap_contributions.connect(workshop, weak=False)
        try:
            self.assertEqual(batch.money_cap(self.char2), 800)
        finally:
            runtime.cap_contributions.disconnect(workshop)

    def test_failed_income_retries_without_partial_stipends(self):
        with (
            override_settings(RP_ECONOMY_STARTING_STIPEND=10),
            patch("evennia_economy.batch.credit", side_effect=RuntimeError),
        ):
            result = batch.run_weekly_batch("test", characters=[self.char2])
        self.assertEqual(len(result["errors"]), 1)
        self.assertFalse(StipendPayment.objects.exists())
        self.assertFalse(UBIPayment.objects.exists())
        self.assertFalse(Purse.objects.exists())
        self.assertEqual(batch.run_weekly_batch("test")["errors"], [])

    def test_week_and_short_period_boundary(self):
        now = datetime(2026, 10, 5, tzinfo=UTC)
        self.assertEqual(batch.period_key(now), "2026-W40")
        with override_settings(RP_ECONOMY_PERIOD_SECONDS=86400):
            self.assertEqual(batch.period_key(now), "86400s:2026-10-05T00:00:00+00:00")

    def test_all_fee_boundaries_debit_and_log_nonzero(self):
        credit(self.char2, 100)
        with override_settings(RP_ECONOMY_FEE_POLICY=lambda kind, actor, context: 2):
            for kind in conf.FEE_KINDS:
                self.assertEqual(charge_fee(kind, self.char2), 2)
        self.assertEqual(balance(self.char2), 84)
        self.assertEqual(LedgerEntry.objects.filter(kind="fee").count(), 8)

    def test_fee_in_feature_transaction_rolls_back_with_feature(self):
        credit(self.char2, 10)
        with (
            override_settings(RP_ECONOMY_FEE_TRADE=2),
            self.assertRaises(RuntimeError),
            transaction.atomic(),
        ):
            charge_fee("trade", self.char2)
            raise RuntimeError
        self.assertEqual(balance(self.char2), 10)
        self.assertFalse(LedgerEntry.objects.filter(kind="fee").exists())

    def test_invalid_fee_policy_fails_closed(self):
        for amount in (-1, True, 0.5):
            with (
                override_settings(RP_ECONOMY_FEE_POLICY=lambda *a, result=amount: result),
                self.assertRaises(EconomyError),
            ):
                charge_fee("trade", self.char2)

    def test_money_swap_and_gift_journal(self):
        credit(self.char1, 40)
        credit(self.char2, 20)
        offer = create_offer(self.char1, self.char2, money(30), money(10))
        self.assertEqual(balance(self.char1), 40)  # unreserved
        accept_offer(self.char2, offer.pk)
        self.assertEqual((balance(self.char1), balance(self.char2)), (20, 40))
        self.assertEqual(
            LedgerEntry.objects.filter(kind="exchange", exchange_id=offer.pk).count(), 2
        )
        with self.assertRaises(EconomyError):
            accept_offer(self.char2, offer.pk)

    def test_same_account_uses_playable_membership_offline(self):
        self.account.characters.add(self.char2)
        self.assertTrue(same_account(self.char1, self.char2))
        credit(self.char1, 5)
        with self.assertRaises(EconomyError):
            create_offer(self.char1, self.char2, money(1))
        with self.assertRaises(EconomyError):
            create_offer(self.char1, self.char2, item(self.obj1))

    def test_new_same_account_membership_rechecked_at_acceptance(self):
        credit(self.char1, 5)
        offer = create_offer(self.char1, self.char2, money(1))
        self.account.characters.add(self.char2)
        with self.assertRaises(EconomyError):
            accept_offer(self.char2, offer.pk)
        self.assertEqual(balance(self.char2), 0)

    def test_same_account_reads_membership_changed_outside_identity_cache(self):
        from evennia.typeclasses.attributes import Attribute
        from evennia.utils.dbserialize import to_pickle

        cached = self.account.attributes.get("_playable_characters", return_obj=True)
        Attribute.objects.filter(pk=cached.pk).update(db_value=to_pickle([self.char1, self.char2]))
        self.assertTrue(same_account(self.char1, self.char2))

    def test_npc_without_account_can_receive_assets(self):
        npc = create_object(
            "evennia.objects.objects.DefaultCharacter", key="NPC", location=self.room1
        )
        credit(self.char1, 5)
        self.gift(self.char1, npc, money(1))
        self.assertEqual(balance(npc), 1)

    def test_expiry_and_leave_return_expire_offer(self):
        credit(self.char1, 5)
        offer = create_offer(self.char1, self.char2, money(1))
        self.char2.location = self.room2
        self.char2.location = self.room1
        offer.refresh_from_db()
        self.assertEqual(offer.status, "expired")
        with self.assertRaises(EconomyError):
            accept_offer(self.char2, offer.pk)
        offer = create_offer(self.char1, self.char2, money(1))
        Offer.objects.filter(pk=offer.pk).update(expires=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(EconomyError):
            accept_offer(self.char2, offer.pk)

    def test_same_room_required_for_creation(self):
        self.char2.location = self.room2
        with self.assertRaises(EconomyError):
            create_offer(self.char1, self.char2, item(self.obj1))

    def test_open_limit_and_cancellation(self):
        credit(self.char1, 10)
        for _ in range(5):
            create_offer(self.char1, self.char2, money(1))
        with self.assertRaises(EconomyError):
            create_offer(self.char1, self.char2, money(1))
        cancel_offer(self.char1, Offer.objects.first().pk)
        create_offer(self.char1, self.char2, money(1))
        self.assertEqual(Offer.objects.filter(status="open").count(), 5)

    def test_recipient_and_stock_rechecked(self):
        credit(self.char1, 10)
        offer = create_offer(self.char1, self.char2, money(10))
        with self.assertRaises(EconomyError):
            accept_offer(self.char1, offer.pk)
        debit(self.char1, 1)
        with self.assertRaises(EconomyError):
            accept_offer(self.char2, offer.pk)
        self.assertEqual(balance(self.char2), 0)

    def test_fee_shortfall_rolls_back_entire_swap(self):
        credit(self.char1, 10)
        self.obj2.location = self.char2
        offer = create_offer(self.char1, self.char2, money(10), item(self.obj2))
        with override_settings(RP_ECONOMY_FEE_TRADE=1), self.assertRaises(EconomyError):
            accept_offer(self.char2, offer.pk)
        self.assertEqual(balance(self.char1), 10)
        self.assertEqual(balance(self.char2), 0)
        self.assertEqual(self.obj2.location, self.char2)
        self.assertFalse(LedgerEntry.objects.filter(kind="fee").exists())

    def test_real_trade_fee_is_charged_to_outgoing_parties(self):
        credit(self.char1, 20)
        credit(self.char2, 10)
        offer = create_offer(self.char1, self.char2, money(5), money(2))
        with override_settings(RP_ECONOMY_FEE_TRADE=1):
            accept_offer(self.char2, offer.pk)
        self.assertEqual((balance(self.char1), balance(self.char2)), (16, 12))
        self.assertEqual(LedgerEntry.objects.filter(kind="fee").count(), 2)

    def test_item_moves_and_hooks_only_after_commit(self):
        offer = create_offer(self.char1, self.char2, item(self.obj1))
        with (
            patch.object(self.obj1, "at_give") as hook,
            self.captureOnCommitCallbacks(execute=True),
        ):
            accept_offer(self.char2, offer.pk)
            hook.assert_not_called()
        hook.assert_called_once_with(self.char1, self.char2)
        self.assertEqual(self.obj1.location, self.char2)
        self.assertIn(self.obj1, self.char2.contents)
        self.assertNotIn(self.obj1, self.char1.contents)

    def test_item_ownership_and_pre_give_rechecked(self):
        offer = create_offer(self.char1, self.char2, item(self.obj1))
        with (
            patch.object(self.obj1, "at_pre_give", return_value=False),
            self.assertRaises(EconomyError),
        ):
            accept_offer(self.char2, offer.pk)
        self.obj1.location = self.room1
        with self.assertRaises(EconomyError):
            accept_offer(self.char2, offer.pk)

    def test_item_and_money_roll_back_on_journal_failure(self):
        credit(self.char2, 10)
        offer = create_offer(self.char1, self.char2, item(self.obj1), money(5))
        with (
            patch("evennia_economy.exchange.journal", side_effect=RuntimeError),
            self.assertRaises(RuntimeError),
            self.captureOnCommitCallbacks(execute=True),
        ):
            accept_offer(self.char2, offer.pk)
        self.obj1.refresh_from_db()
        self.assertEqual(self.obj1.location, self.char1)
        self.assertEqual(balance(self.char2), 10)
        self.assertFalse(LedgerEntry.objects.filter(kind="exchange").exists())

    def test_public_and_secret_announcements(self):
        credit(self.char1, 10)
        for secret, accept_secret in ((False, False), (True, False), (False, True)):
            offer = create_offer(self.char1, self.char2, money(1), secret=secret)
            with (
                patch.object(self.room1, "msg_contents") as emit,
                self.captureOnCommitCallbacks(execute=True),
            ):
                accept_offer(self.char2, offer.pk, secret=accept_secret)
            self.assertEqual(emit.call_count, 0 if secret or accept_secret else 1)

    def test_frozen_api_batch_exchange_and_fee_refuse_but_reads_work(self):
        credit(self.char1, 10)
        offer = create_offer(self.char1, self.char2, money(1))
        with override_settings(RP_ECONOMY_FROZEN=True):
            for function in (
                lambda: credit(self.char1, 1),
                lambda: debit(self.char1, 1),
                lambda: accept_offer(self.char2, offer.pk),
                lambda: create_offer(self.char1, self.char2, item(self.obj1)),
                lambda: charge_fee("trade", self.char1),
            ):
                with self.assertRaisesRegex(EconomyError, "market is closed"):
                    function()
            self.assertTrue(batch.run_weekly_batch("test")["frozen"])
            self.assertFalse(UBIPayment.objects.exists())
            self.assertEqual(balance(self.char1), 10)
            cancel_offer(self.char1, offer.pk)

    def test_unknown_provider_fails_closed(self):
        with self.assertRaises(EconomyError):
            create_offer(self.char1, self.char2, [{"kind": "missing", "key": "x", "quantity": 1}])

    def test_spec_validation_and_aggregation(self):
        self.assertEqual(assets.normalize(money(2) + money(3)), money(5))
        for spec in (
            [{"kind": "money", "key": "", "quantity": True}],
            item(self.obj1) * 2,
            [{"kind": "item", "key": "oops", "quantity": 1}],
            ["oops"],
        ):
            with self.assertRaises(EconomyError):
                assets.normalize(spec)

    def test_parser_explicit_and_natural_money_and_item(self):
        self.assertEqual(assets.parse_spec(self.char1, "4 coins"), money(4))
        self.assertEqual(assets.parse_spec(self.char1, "money:4"), money(4))
        self.assertEqual(assets.parse_spec(self.char1, f"item:#{self.obj1.pk}"), item(self.obj1))

    def test_roundtrip_cross_asset_flag_and_review_hook(self):
        alt = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Alt", location=self.room1
        )
        self.account.characters.add(alt)
        credit(self.char1, 10)
        self.gift(self.char1, self.char2, money(2))
        self.obj2.location = self.char2
        with (
            patch("evennia_economy.review._notify") as resolve,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.gift(self.char2, alt, item(self.obj2))
        self.assertEqual(ReviewFlag.objects.count(), 1)
        resolve.assert_called_once()
        self.assertEqual(balance(self.char2), 2)  # flag applies no penalty

    def test_no_roundtrip_flag_for_return_to_same_character_or_old_leg(self):
        credit(self.char1, 10)
        self.gift(self.char1, self.char2, money(2))
        self.gift(self.char2, self.char1, money(1))
        self.assertFalse(ReviewFlag.objects.exists())
        alt = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Alt", location=self.room1
        )
        self.account.characters.add(alt)
        LedgerEntry.objects.filter(kind="exchange", from_id=self.char1.pk).update(
            created=timezone.now() - timedelta(days=8)
        )
        self.gift(self.char2, alt, money(1))
        self.assertFalse(ReviewFlag.objects.exists())

    def test_deleting_a_character_burns_its_balance_in_the_journal(self):
        credit(self.char2, 50)
        name = self.char2.key
        self.char2.delete()
        row = LedgerEntry.objects.get(kind="deleted")
        self.assertEqual((row.amount, row.from_name, row.to_id), (50, name, None))
        self.assertEqual(reconciliation()["money"], {"minted": 50, "burned": 50, "held": 0})

    def test_one_failing_post_commit_hook_does_not_skip_the_rest(self):
        offer = create_offer(self.char1, self.char2, item(self.obj1))
        with (
            patch.object(self.char1, "at_object_leave", side_effect=RuntimeError),
            patch.object(self.obj1, "at_post_move") as moved,
            self.assertLogs("evennia", level="ERROR"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            accept_offer(self.char2, offer.pk)
        moved.assert_called_once()
        self.assertEqual(self.obj1.location, self.char2)

    def test_income_cap_notice_is_given_once(self):
        credit(self.char1, 500)
        for week in ("W1", "W2", "W3"):
            batch.run_weekly_batch(week)
            with patch.object(self.char1, "msg") as msg:
                notify_economy_summary(self.char1)
            if week == "W1":
                self.assertIn("at its income cap", msg.call_args.args[0])
            else:
                msg.assert_not_called()

    def test_staff_report_per_account_accrual_and_reconciliation(self):
        batch.run_weekly_batch("test")
        debit(self.char1, 10)
        row = next(row for row in account_accrual() if row["id"] == self.account.pk)
        self.assertEqual((row["ubi"], row["balance"]), (100, 90))
        self.assertEqual(reconciliation()["money"], {"minted": 200, "burned": 10, "held": 190})

    def test_dark_accrual_and_once_login_summary(self):
        with override_settings(RP_ECONOMY_REVEALED=False):
            batch.run_weekly_batch("test")
            with patch.object(self.char1, "msg") as msg:
                self.assertFalse(notify_economy_summary(self.char1))
                msg.assert_not_called()
        with patch.object(self.char1, "msg") as msg:
            self.assertTrue(notify_economy_summary(self.char1))
            self.assertFalse(notify_economy_summary(self.char1))
            msg.assert_called_once()

    def test_reveal_hides_commands_and_help_for_players(self):
        with override_settings(RP_ECONOMY_REVEALED=False):
            for command in (CmdBalance, CmdOffer, CmdAccept):
                self.assertFalse(command().access(self.char2))
                self.assertTrue(command().access(self.char1))
            # give replaces Evennia's own, so it never disappears.
            self.assertTrue(CmdGive().access(self.char2))
            self.assertEqual(CmdGive().help_category, "general")


@override_settings(RP_ECONOMY_REVEALED=True, RP_ECONOMY_FROZEN=False, RP_ECONOMY_FEE_POLICY=None)
class EconomyCommandTests(BaseEvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)

    def test_balance_and_staff_permissions(self):
        self.assertIn("Purse:", self.call(CmdBalance(), "", caller=self.char2))
        self.assertIn("Only staff", self.call(CmdEconomy(), "", caller=self.char2))
        self.call(CmdEconomy(), "/credit Char2=10,Test")
        self.assertEqual(balance(self.char2), 10)
        self.call(CmdEconomy(), "/debit Char2=2,Test")
        self.assertEqual(balance(self.char2), 8)

    def test_offer_accept_list_cancel(self):
        credit(self.char1, 10)
        self.call(CmdOffer(), "Char2=4 coins", "Offer #")
        offer = Offer.objects.latest("pk")
        self.assertIn("4 coins", self.call(CmdOffer(), ""))
        self.call(CmdAccept(), str(offer.pk), caller=self.char2)
        self.assertEqual(balance(self.char2), 4)
        self.call(CmdOffer(), "Char2=1 coin")
        self.call(CmdOffer(), f"/cancel {Offer.objects.latest('pk').pk}", "Offer cancelled.")

    def test_give_uses_same_exchange_checks(self):
        credit(self.char1, 10)
        self.call(CmdGive(), "2 coins to Char2", "You give 2 coins to Char2.")
        self.assertEqual(balance(self.char2), 2)
        self.account.characters.add(self.char2)
        self.assertIn("same account", self.call(CmdGive(), "1 coin=Char2"))
        self.assertFalse(Offer.objects.filter(status="open").exists())

    def test_give_never_takes_an_offer_slot(self):
        credit(self.char1, 10)
        for _ in range(5):
            create_offer(self.char1, self.char2, [{"kind": "money", "key": "", "quantity": 1}])
        self.call(CmdGive(), "1 coin to Char2", "You give 1 coin to Char2.")

    def test_hidden_give_hands_over_items_only(self):
        self.obj1.location = self.char2
        credit(self.char2, 10)
        with override_settings(RP_ECONOMY_REVEALED=False):
            refused = self.call(CmdGive(), "2 coins to Char", caller=self.char2)
            self.assertIn("No unique carried item matches '2 coins'", refused)
            with self.captureOnCommitCallbacks(execute=True):
                self.call(CmdGive(), "Obj to Char", "You give Obj to Char.", caller=self.char2)
        self.assertEqual(self.obj1.location, self.char1)
        self.assertEqual(balance(self.char2), 10)

    def test_frozen_give_moves_items_but_not_money_and_pays_no_fee(self):
        self.obj1.location = self.char2
        credit(self.char2, 10)
        with override_settings(RP_ECONOMY_FROZEN=True, RP_ECONOMY_FEE_TRADE=3):
            with self.captureOnCommitCallbacks(execute=True):
                self.call(CmdGive(), "Obj to Char", "You give Obj to Char.", caller=self.char2)
            frozen = self.call(CmdGive(), "1 coin to Char", caller=self.char2)
            self.assertIn("market is closed", frozen)
        self.assertEqual(self.obj1.location, self.char1)
        self.assertEqual(balance(self.char2), 10)
        self.assertTrue(LedgerEntry.objects.filter(kind="exchange").exists())
