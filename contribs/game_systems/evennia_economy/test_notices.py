# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Committed income and stipends through standalone and real optional Inbox routes."""

from datetime import timedelta
from secrets import token_urlsafe
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock, patch
from uuid import uuid4

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from evennia.utils.create import create_account, create_object
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_links import runtime

from . import batch, conf, notices
from .models import EconomyNoticeReceipt, LedgerEntry, StipendPayment, UBIPayment
from .services import balance, credit, debit
from .summary import notify_economy_summary

State = EconomyNoticeReceipt.State
SOURCES = {"economy": "evennia_economy.integrations.notices.EconomyNoticeSource"}
PREFERENCE_SOURCES = {
    "economy": "evennia_economy.integrations.notices.EconomyNoticeSource",
    "other": "evennia_economy.test_notices.OtherSource",
}

if apps.is_installed("evennia_notices"):
    from django.urls import include, path
    from evennia.web.urls import urlpatterns as evennia_patterns

    urlpatterns = [path("notices/", include("evennia_notices.urls")), *evennia_patterns]


class OtherSource:
    """Hookless source proving the preference lists stay populated."""

    label = "Unrelated alerts"

    def evaluate(self, events, context):
        return {}

    def render(self, events, context):
        raise ValueError("No notice")


@override_settings(
    RP_ECONOMY_REVEALED=True,
    RP_ECONOMY_FROZEN=False,
    RP_ECONOMY_WEEKLY_AMOUNT=100,
    RP_ECONOMY_BASE_CAP_WEEKS=5,
    RP_ECONOMY_TAPER_FRACTION=0.8,
    RP_ECONOMY_STARTING_STIPEND=100,
    RP_ECONOMY_REVEAL_STIPEND=50,
    RP_ECONOMY_ELIGIBLE=None,
    RP_ECONOMY_FEE_POLICY=None,
    RP_ECONOMY_FLAG_REVIEW_HOOK=None,
)
class EconomyNoticeFixture(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.account = create_account("Economy Owner", None, token_urlsafe(32))
        self.other = create_account("Economy Other", None, token_urlsafe(32))
        self.character = create_object("evennia.DefaultCharacter", key="Economy", nohome=True)
        self.account.characters.add(self.character)
        self.character.account = self.account
        self.character.msg = Mock()
        self.session = self.make_session()
        self.sessions = [self.session]
        registered = patch.object(
            notices, "_registered_sessions", side_effect=lambda: self.sessions
        )
        registered.start()
        self.addCleanup(registered.stop)

    def make_session(self):
        return SimpleNamespace(
            logged_in=True,
            msg=Mock(),
            get_account=lambda: self.account,
            get_puppet=lambda: self.character,
        )

    def pay(self, week, **kwargs):
        result = batch.run_weekly_batch(week, characters=[self.character], **kwargs)
        self.assertEqual(result["errors"], [])
        return UBIPayment.objects.filter(character=self.character, week=week).first()

    def unstaged(self, week):
        """Pay as an older release did, before receipts existed."""
        with patch.object(notices, "stage_payment"):
            return self.pay(week)

    def hide(self):
        runtime.set("RP_ECONOMY_REVEALED", False)

    def reveal(self):
        runtime.set("RP_ECONOMY_REVEALED", True)

    def stipend(self, kind):
        return StipendPayment.objects.get(character=self.character, kind=kind)

    def state(self, *, ubi=None, stipend=None):
        if ubi is not None:
            return EconomyNoticeReceipt.objects.get(ubi=ubi).state
        return EconomyNoticeReceipt.objects.get(stipend=stipend).state

    def make_staff_visible(self):
        """An owner who is also a superuser, puppeting the character while hidden."""
        staff = create_account("Economy Staff", None, token_urlsafe(32))
        staff.is_superuser = True
        staff.save()
        staff.characters.add(self.character)
        self.character.account = staff
        self.character.locks.cache_lock_bypass(self.character)
        self.assertFalse(runtime.get("RP_ECONOMY_REVEALED"))
        self.assertTrue(conf.visible(self.character))
        return staff

    def assert_population(self):
        self.hide()
        batch.ensure_stipends(self.character)
        self.assertFalse(EconomyNoticeReceipt.objects.exists())
        self.reveal()
        self.assertTrue(
            StipendPayment.objects.filter(character=self.character, kind="reveal").exists()
        )
        self.pay("w1")
        self.pay("w2")
        self.assertTrue(StipendPayment.objects.filter(character=self.character).exists())
        self.assertTrue(UBIPayment.objects.filter(character=self.character).exists())
        self.assertFalse(
            EconomyNoticeReceipt.objects.filter(stipend=self.stipend("starting")).exists()
        )
        self.prepare()
        self.assertFalse(
            StipendPayment.objects.filter(
                character=self.character, notice_receipt__isnull=True
            ).exists()
        )
        for ubi in UBIPayment.objects.filter(character=self.character):
            self.assertEqual(EconomyNoticeReceipt.objects.filter(ubi=ubi).count(), 1)


@override_settings(NOTICES_ENABLED=False)
class StandaloneEconomyNoticeTests(EconomyNoticeFixture):
    def show(self):
        return notify_economy_summary(self.character)

    prepare = show

    def test_every_payment_creator_stages_one_receipt(self):
        self.assert_population()

    def test_inbox_preference_follows_only_the_reveal(self):
        from evennia_links.notices import NoticeContext

        from .integrations.notices import EconomyNoticeSource

        source = EconomyNoticeSource()
        context = NoticeContext(self.account, self.character)
        self.assertIs(source.available(context), True)
        self.hide()
        self.assertIs(source.available(context), False)
        staff = self.make_staff_visible()
        self.assertIs(source.available(NoticeContext(staff, self.character)), False)
        self.reveal()
        self.assertIs(source.available(context), True)

    def test_repeated_puppet_sends_one_combined_line_and_writes_marker(self):
        ubi = self.pay("w1")
        start = self.stipend("starting")
        self.assertTrue(self.show())
        self.assertFalse(self.show())
        self.character.msg.assert_called_once_with(
            "Your latest income: 100 coins. Stipends received: 100 coins. See +balance.",
            session=self.session,
        )
        rows = list(EconomyNoticeReceipt.objects.all())
        self.assertEqual({row.state for row in rows}, {State.DELIVERED})
        self.assertEqual(len({row.attempted_at for row in rows}), 1)
        self.assertEqual(self.character.attributes.get(notices.MARKER_KEY), [ubi.pk, [start.pk]])
        self.assertFalse(self.character.attributes.get(notices.FULL_KEY))

    def test_one_shared_attempt_covers_income_and_stipend(self):
        self.pay("w1")
        attempts = []
        send = notices._send_line

        def record(claim, *args):
            attempts.append(
                set(
                    EconomyNoticeReceipt.objects.filter(pk__in=claim.receipt_ids).values_list(
                        "attempt", flat=True
                    )
                )
            )
            return send(claim, *args)

        with patch.object(notices, "_send_line", side_effect=record):
            self.assertTrue(self.show())
        self.assertEqual(len(attempts), 1)
        self.assertEqual(len(attempts[0]), 1)
        self.assertEqual(EconomyNoticeReceipt.objects.count(), 2)

    def test_session_drop_between_claim_and_send_returns_claim_to_pending(self):
        self.pay("w1")
        claim_line = notices._claim_line

        def disconnect(*args):
            claim = claim_line(*args)
            self.session.logged_in = False
            return claim

        with patch.object(notices, "_claim_line", side_effect=disconnect):
            self.assertFalse(self.show())
        self.character.msg.assert_not_called()
        self.assertEqual(
            set(EconomyNoticeReceipt.objects.values_list("state", flat=True)), {State.PENDING}
        )
        self.assertIsNone(self.character.attributes.get(notices.MARKER_KEY))
        self.session.logged_in = True
        self.assertTrue(self.show())
        self.assertFalse(self.show())
        self.character.msg.assert_called_once()

    def test_hidden_after_render_returns_claim_to_pending_without_a_write(self):
        self.pay("w1")
        text = notices.line_text

        def hide(*args):
            result = text(*args)
            settings.RP_ECONOMY_REVEALED = False
            return result

        with (
            override_settings(RP_ECONOMY_REVEALED=True),
            patch.object(notices, "line_text", side_effect=hide),
        ):
            self.assertFalse(self.show())
        self.character.msg.assert_not_called()
        self.assertEqual(
            set(EconomyNoticeReceipt.objects.values_list("state", flat=True)), {State.PENDING}
        )
        self.assertTrue(self.show())
        self.character.msg.assert_called_once()

    def test_each_session_is_independent_and_unknown_write_is_never_replayed(self):
        self.sessions.append(self.make_session())
        ubi = self.pay("w1")
        self.character.msg.side_effect = [RuntimeError("write started"), None]
        self.assertTrue(self.show())
        self.assertEqual(self.character.msg.call_count, 2)
        self.assertEqual(self.state(ubi=ubi), State.DELIVERED)
        later = self.pay("w2")
        self.character.msg.side_effect = RuntimeError("write started")
        self.assertFalse(self.show())
        self.assertEqual(self.state(ubi=later), State.UNCERTAIN)
        self.character.msg.reset_mock()
        self.assertFalse(self.show())
        self.character.msg.assert_not_called()

    def test_confirmed_write_retries_only_failed_terminal_settlement(self):
        ubi = self.pay("w1")
        self.addCleanup(notices._waiting.clear)
        with patch.object(notices, "_finalize", side_effect=RuntimeError("database unavailable")):
            self.assertTrue(self.show())
        self.assertEqual(self.state(ubi=ubi), State.ATTEMPTING)
        self.assertFalse(self.show())
        self.assertEqual(self.state(ubi=ubi), State.DELIVERED)
        self.assertEqual(self.character.attributes.get(notices.MARKER_KEY)[0], ubi.pk)
        self.character.msg.assert_called_once()

    def test_batch_racing_the_claim_sends_only_the_current_week(self):
        first = self.pay("w1")
        claim_line = notices._claim_line

        def race(*args):
            claim = claim_line(*args)
            credit(self.character, 250)
            batch.run_weekly_batch("w2", characters=[self.character])
            return claim

        with patch.object(notices, "_claim_line", side_effect=race):
            self.assertFalse(self.show())
        self.character.msg.assert_not_called()
        second = UBIPayment.objects.get(week="w2")
        start = self.stipend("starting")
        self.assertEqual(self.state(ubi=first), State.PENDING)
        self.assertEqual(self.state(stipend=start), State.PENDING)
        self.assertEqual(self.state(ubi=second), State.PENDING)
        self.assertTrue(self.show())
        self.character.msg.assert_called_once_with(
            "Your latest income: 50 coins. Stipends received: 100 coins."
            " Your purse is near its income cap. See +balance.",
            session=self.session,
        )
        self.assertEqual(self.state(ubi=first), State.SUPERSEDED)
        self.assertEqual(self.state(ubi=second), State.DELIVERED)
        self.assertEqual(self.state(stipend=start), State.DELIVERED)
        self.assertFalse(self.show())
        self.character.msg.assert_called_once()

    def test_stipend_racing_the_claim_is_included_in_the_next_line(self):
        self.pay("w1")
        claim_line = notices._claim_line

        def race(*args):
            claim = claim_line(*args)
            self.hide()
            self.reveal()
            return claim

        with patch.object(notices, "_claim_line", side_effect=race):
            self.assertFalse(self.show())
        self.character.msg.assert_not_called()
        self.assertTrue(self.show())
        self.character.msg.assert_called_once_with(
            "Your latest income: 100 coins. Stipends received: 150 coins. See +balance.",
            session=self.session,
        )
        self.assertEqual(
            set(EconomyNoticeReceipt.objects.values_list("state", flat=True)), {State.DELIVERED}
        )
        self.assertFalse(self.show())

    def test_legacy_seen_latest_week_does_not_block_reveal_stipend(self):
        ubi = self.pay("w1")
        start = self.stipend("starting")
        EconomyNoticeReceipt.objects.all().delete()  # paid before this release
        self.character.attributes.add(notices.MARKER_KEY, [ubi.pk, [start.pk]])
        self.hide()
        self.reveal()
        self.assertTrue(self.show())
        self.character.msg.assert_called_once_with(
            "Your latest income: 100 coins. Stipends received: 150 coins. See +balance.",
            session=self.session,
        )
        self.assertEqual(self.state(stipend=self.stipend("reveal")), State.DELIVERED)
        self.assertFalse(EconomyNoticeReceipt.objects.filter(ubi=ubi).exists())
        self.assertFalse(self.show())
        self.character.msg.assert_called_once()

    def test_uncertain_latest_week_does_not_block_later_stipend(self):
        ubi = self.pay("w1")
        self.character.msg.side_effect = RuntimeError("write started")
        self.assertFalse(self.show())
        self.assertEqual(self.state(ubi=ubi), State.UNCERTAIN)
        self.character.msg.side_effect = None
        self.character.msg.reset_mock()
        self.hide()
        self.reveal()
        self.assertTrue(self.show())
        self.character.msg.assert_called_once_with(
            "Your latest income: 100 coins. Stipends received: 150 coins. See +balance.",
            session=self.session,
        )
        self.assertEqual(self.state(stipend=self.stipend("reveal")), State.DELIVERED)
        self.assertEqual(self.state(ubi=ubi), State.UNCERTAIN)
        self.assertFalse(self.show())
        self.character.msg.assert_called_once()

    def strand_claim(self):
        """A claim committed by a process that stopped before settling it."""
        ubi = self.pay("w1")
        self.assertIsNotNone(notices._claim_line(self.character, "standalone"))
        self.assertEqual(self.state(ubi=ubi), State.ATTEMPTING)
        return ubi

    def backdate(self, ubi):
        EconomyNoticeReceipt.objects.filter(ubi=ubi).update(
            attempted_at=timezone.now() - timedelta(seconds=notices._ATTEMPT_LIFETIME + 60)
        )

    def test_stale_foreign_attempt_stops_blocking_stipend_line(self):
        ubi = self.strand_claim()
        self.backdate(ubi)
        self.hide()
        self.reveal()
        self.assertTrue(self.show())
        self.character.msg.assert_called_once_with(
            "Your latest income: 100 coins. Stipends received: 150 coins. See +balance.",
            session=self.session,
        )
        self.assertEqual(self.state(stipend=self.stipend("reveal")), State.DELIVERED)
        self.assertFalse(self.show())
        self.character.msg.assert_called_once()
        self.assertEqual(self.state(ubi=ubi), State.ATTEMPTING)

    def test_stale_foreign_attempt_alone_sends_nothing(self):
        ubi = self.strand_claim()
        self.backdate(ubi)
        self.assertFalse(self.show())
        self.character.msg.assert_not_called()
        self.assertEqual(self.state(ubi=ubi), State.ATTEMPTING)

    def test_settlement_waiting_in_process_keeps_week_busy(self):
        self.addCleanup(notices._waiting.clear)
        finalize = notices._finalize
        held = set()

        def fail_held(claim, *args):
            if not held or claim.attempt in held:
                held.add(claim.attempt)
                raise RuntimeError("database unavailable")
            return finalize(claim, *args)

        ubi = self.pay("w1")
        with patch.object(notices, "_finalize", side_effect=fail_held):
            self.assertTrue(self.show())
            self.assertEqual(set(notices._waiting), held)
            self.backdate(ubi)
            self.hide()
            self.reveal()
            self.assertFalse(self.show())
            self.assertEqual(self.state(ubi=ubi), State.ATTEMPTING)
            self.assertEqual(self.state(stipend=self.stipend("reveal")), State.PENDING)
        self.character.msg.assert_called_once_with(
            "Your latest income: 100 coins. Stipends received: 100 coins. See +balance.",
            session=self.session,
        )
        self.assertTrue(self.show())
        self.assertEqual(self.state(ubi=ubi), State.DELIVERED)
        self.assertEqual(self.state(stipend=self.stipend("reveal")), State.DELIVERED)
        self.assertFalse(self.show())
        self.assertEqual(
            [call.args[0] for call in self.character.msg.call_args_list],
            [
                "Your latest income: 100 coins. Stipends received: 100 coins. See +balance.",
                "Your latest income: 100 coins. Stipends received: 150 coins. See +balance.",
            ],
        )

    def test_held_unattempted_settlement_is_not_sent_twice(self):
        self.addCleanup(notices._waiting.clear)
        finalize, text = notices._finalize, notices.line_text
        held = set()

        def fail_held(claim, *args):
            if not held or claim.attempt in held:
                held.add(claim.attempt)
                raise RuntimeError("database unavailable")
            return finalize(claim, *args)

        def drop_once(*args):
            result = text(*args)
            if not held:
                self.session.logged_in = False
            return result

        ubi = self.pay("w1")
        with (
            patch.object(notices, "_finalize", side_effect=fail_held),
            patch.object(notices, "line_text", side_effect=drop_once),
        ):
            self.assertFalse(self.show())
            self.assertEqual(set(notices._waiting), held)
            self.session.logged_in = True
            self.backdate(ubi)
            self.hide()
            self.reveal()
            self.assertFalse(self.show())
            self.assertEqual(self.state(ubi=ubi), State.ATTEMPTING)
            self.assertEqual(self.state(stipend=self.stipend("reveal")), State.PENDING)
        self.character.msg.assert_not_called()
        self.assertTrue(self.show())
        self.assertFalse(self.show())
        self.character.msg.assert_called_once_with(
            "Your latest income: 100 coins. Stipends received: 150 coins. See +balance.",
            session=self.session,
        )
        self.assertEqual(
            set(EconomyNoticeReceipt.objects.values_list("state", flat=True)), {State.DELIVERED}
        )

    def test_fresh_foreign_attempt_withholds_stipend_line(self):
        self.strand_claim()
        self.hide()
        self.reveal()
        self.assertFalse(self.show())
        self.character.msg.assert_not_called()
        self.assertEqual(self.state(stipend=self.stipend("reveal")), State.PENDING)

    @override_settings(RP_ECONOMY_REVEAL_STIPEND=0)
    def test_hidden_pending_week_defers_until_reveal(self):
        ubi = self.pay("w1")
        self.hide()
        self.assertFalse(self.show())
        self.assertFalse(self.show())
        self.character.msg.assert_not_called()
        self.assertEqual(self.state(ubi=ubi), State.PENDING)
        self.assertIsNone(self.character.attributes.get(notices.MARKER_KEY))
        self.reveal()
        self.assertTrue(self.show())
        self.assertIn("Your latest income: 100 coins.", self.character.msg.call_args.args[0])
        self.assertEqual(self.state(ubi=ubi), State.DELIVERED)
        self.assertFalse(self.show())
        self.character.msg.assert_called_once()

    def test_dark_weeks_then_reveal_send_latest_and_all_stipends(self):
        self.hide()
        batch.ensure_stipends(self.character)
        self.pay("w1")
        self.pay("w2")
        self.assertFalse(self.show())
        self.assertFalse(EconomyNoticeReceipt.objects.exists())
        self.reveal()
        self.assertTrue(self.show())
        self.character.msg.assert_called_once_with(
            "Your latest income: 100 coins. Stipends received: 150 coins. See +balance.",
            session=self.session,
        )
        self.assertFalse(EconomyNoticeReceipt.objects.filter(ubi__week="w1").exists())

    def test_capped_week_with_new_stipend_sends_line_without_cap_text(self):
        credit(self.character, 400)
        self.pay("w1")
        self.assertTrue(self.show())
        self.assertIn("Your purse is at its income cap.", self.character.msg.call_args.args[0])
        capped = self.pay("w2")
        self.assertFalse(self.show())
        self.assertEqual(self.state(ubi=capped), State.SUPPRESSED)
        self.pay("w3")
        self.hide()
        self.reveal()
        self.character.msg.reset_mock()
        self.assertTrue(self.show())
        self.character.msg.assert_called_once_with(
            "Your latest income: 0 coins. Stipends received: 150 coins. See +balance.",
            session=self.session,
        )

    def test_legacy_cap_baseline_keeps_unseen_capped_week_quiet(self):
        credit(self.character, 400)
        ubi = self.unstaged("w1")
        self.character.attributes.add(notices.FULL_KEY, True)
        self.character.attributes.add(notices.MARKER_KEY, [None, [self.stipend("starting").pk]])
        self.assertFalse(self.show())
        self.character.msg.assert_not_called()
        self.assertEqual(self.state(ubi=ubi), State.SUPPRESSED)
        self.assertTrue(self.character.attributes.get(notices.FULL_KEY))

    @override_settings(RP_ECONOMY_STARTING_STIPEND=0)
    def test_zero_stipend_stays_in_standalone_line(self):
        self.pay("w1")
        self.assertTrue(self.show())
        self.character.msg.assert_called_once_with(
            "Your latest income: 100 coins. Stipends received: 0 coins. See +balance.",
            session=self.session,
        )

    @override_settings(RP_ECONOMY_WEEKLY_AMOUNT=0)
    def test_zero_uncapped_income_is_announced_each_new_week(self):
        self.pay("w1")
        self.assertTrue(self.show())
        self.pay("w2")
        self.assertTrue(self.show())
        self.assertFalse(self.show())
        self.assertEqual(
            [call.args[0] for call in self.character.msg.call_args_list],
            ["Your latest income: 0 coins. Stipends received: 100 coins. See +balance."] * 2,
        )

    def test_malformed_legacy_markers_count_as_never_summarized(self):
        for index, value in enumerate((["2026-10-26", 1], [True, []], "x", [1], [1, [0]]), start=1):
            with self.subTest(value=value):
                self.unstaged(f"malformed-{index}")
                self.character.attributes.add(notices.MARKER_KEY, value)
                self.character.msg.reset_mock()
                with self.assertLogs("evennia", level="WARNING") as logs:
                    self.assertTrue(self.show())
                self.assertIn("marker unreadable", "\n".join(logs.output))
                self.character.msg.assert_called_once()

    def test_preparation_in_outer_transaction_waits_for_commit(self):
        self.pay("w1")
        with transaction.atomic():
            self.assertFalse(self.show())
            self.character.msg.assert_not_called()
            transaction.set_rollback(True)
        self.character.msg.assert_not_called()
        self.assertTrue(self.show())

    def test_dry_run_and_rolled_back_batch_create_no_rows(self):
        self.pay("preview", dry_run=True)
        with transaction.atomic():
            self.pay("rolled-back")
            transaction.set_rollback(True)
        self.assertFalse(EconomyNoticeReceipt.objects.exists())
        self.assertFalse(UBIPayment.objects.exists())


@override_settings(NOTICES_ENABLED=False, RP_ECONOMY_STARTING_STIPEND=0)
class GuestEconomyNoticeTests(EconomyNoticeFixture):
    def setUp(self):
        super().setUp()
        from evennia.accounts.accounts import DefaultGuest

        guest = create_account("Economy Guest", None, token_urlsafe(32), typeclass=DefaultGuest)
        self.account.characters.remove(self.character)
        guest.characters.add(self.character)
        self.account = self.character.account = guest
        self.addCleanup(notices._guests.clear)
        later = patch("twisted.internet.reactor.callLater")
        later.start()
        self.addCleanup(later.stop)

    def show(self):
        return notify_economy_summary(self.character)

    def assert_nothing_saved(self):
        self.assertFalse(EconomyNoticeReceipt.objects.exists())
        self.assertIsNone(self.character.attributes.get(notices.MARKER_KEY))
        self.assertIsNone(self.character.attributes.get(notices.FULL_KEY))

    @override_settings(RP_ECONOMY_STARTING_STIPEND=100)
    def test_connected_guest_gets_one_line_per_payment(self):
        self.pay("g")
        self.assertEqual(
            [call.args[0] for call in self.character.msg.call_args_list],
            [
                "Stipend received: 100 coins. See +balance.",
                "Weekly income: 100 coins. See +balance.",
            ],
        )
        self.assertFalse(self.show())
        self.assert_nothing_saved()

    def test_failed_render_retries_only_for_original_connections(self):
        with patch.object(notices, "payment_text", side_effect=RuntimeError("pre-write")):
            self.pay("g")
        self.character.msg.assert_not_called()
        [claim] = notices._guests.values()
        self.assertFalse(claim.consumed)
        self.sessions[:] = [self.make_session()]
        self.assertFalse(self.show())
        self.sessions[:] = [self.session]
        self.assertTrue(self.show())
        self.assertFalse(self.show())
        self.character.msg.assert_called_once_with(
            "Weekly income: 100 coins. See +balance.", session=self.session
        )
        self.assert_nothing_saved()

    def test_session_drop_between_claim_and_send_is_not_consumed(self):
        text = notices.payment_text

        def disconnect(row):
            self.session.logged_in = False
            return text(row)

        with patch.object(notices, "payment_text", side_effect=disconnect):
            self.pay("g")
        self.character.msg.assert_not_called()
        [claim] = notices._guests.values()
        self.assertFalse(claim.consumed)
        self.session.logged_in = True
        self.assertTrue(self.show())
        self.assertFalse(self.show())
        self.character.msg.assert_called_once()

    def test_expired_claim_without_sessions_is_dropped(self):
        with patch.object(notices, "payment_text", side_effect=RuntimeError("pre-write")):
            self.pay("g")
        self.sessions[:] = []
        self.assertFalse(self.show())
        [(key, claim)] = notices._guests.items()
        notices._expire_guest(key, claim)
        self.assertEqual(notices._guests, {})
        self.sessions[:] = [self.session]
        self.assertFalse(self.show())
        self.character.msg.assert_not_called()

    def test_hidden_payment_and_zero_stipend_make_no_claim(self):
        self.hide()
        self.pay("dark")
        self.assertEqual(notices._guests, {})
        self.reveal()
        StipendPayment.objects.all().delete()
        with transaction.atomic():
            self.assertEqual(batch._stipends(self.character), {"starting": 0})
        self.assertEqual(notices._guests, {})
        self.character.msg.assert_not_called()
        self.assert_nothing_saved()


@skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox is absent")
@override_settings(NOTICES_ENABLED=True, LINKS_NOTICE_SOURCES=SOURCES)
class InboxEconomyNoticeTests(EconomyNoticeFixture):
    def context(self, account=None, *, character=None, session=False):
        from evennia_links.notices import NoticeContext

        return NoticeContext(
            account or self.account,
            character or self.character,
            self.session if session else None,
        )

    def project(self, context=None):
        from evennia_notices.services import project

        return project(context or self.context(), source=notices.SOURCE)

    def prepare(self):
        from .integrations.notices import EconomyNoticeSource

        EconomyNoticeSource().prepare(self.context(session=True))

    def receipts(self):
        from evennia_notices.models import DeliveryReceipt

        return DeliveryReceipt.objects.filter(source="economy")

    def texts(self, context=None):
        return sorted(item.text for item in self.project(context))

    def test_every_payment_creator_stages_one_receipt(self):
        self.assert_population()

    def test_income_and_stipend_are_separate_notices_once(self):
        from evennia_notices.services import summarize

        self.pay("w1")
        self.prepare()
        self.prepare()
        self.assertEqual(self.receipts().count(), 2)
        self.assertEqual(
            self.texts(),
            [
                "Stipend received: 100 coins. See +balance.",
                "Weekly income: 100 coins. See +balance.",
            ],
        )
        self.assertEqual(summarize(self.context(session=True)), (2, 0))
        self.character.msg.assert_not_called()
        self.assertEqual(
            set(EconomyNoticeReceipt.objects.values_list("state", flat=True)), {State.TRANSFERRED}
        )

    def test_failed_route_stays_pending_and_retries_once(self):
        with patch("evennia_notices.services.route", side_effect=RuntimeError("transient")):
            self.pay("w1")
        self.assertEqual(
            set(EconomyNoticeReceipt.objects.values_list("state", flat=True)), {State.PENDING}
        )
        self.prepare()
        self.prepare()
        self.assertEqual(self.receipts().count(), 2)

    def test_backend_switch_never_replays_and_falls_back_for_new_payments(self):
        from evennia_notices.services import mutate

        first = self.pay("w1")
        for item in self.project():
            mutate(self.context(), item.notice.public_ref, "clear")
        with override_settings(NOTICES_ENABLED=False):
            self.assertFalse(notify_economy_summary(self.character))
            self.character.msg.assert_not_called()
            second = self.pay("w2")
            self.assertTrue(notify_economy_summary(self.character))
            self.character.msg.assert_called_once_with(
                "Your latest income: 100 coins. Stipends received: 100 coins. See +balance.",
                session=self.session,
            )
        self.assertEqual(self.state(ubi=first), State.TRANSFERRED)
        self.assertEqual(self.state(ubi=second), State.DELIVERED)
        self.prepare()
        self.assertEqual(self.project(), [])
        self.assertEqual(self.receipts().count(), 2)
        self.assertEqual(self.character.attributes.get(notices.MARKER_KEY)[0], second.pk)

    @override_settings(RP_ECONOMY_STARTING_STIPEND=0, RP_ECONOMY_REVEAL_STIPEND=0)
    def test_hidden_after_transfer_defers_for_owner_and_superuser_and_survives_maintain(self):
        from evennia_links.notices import StoredEvent
        from evennia_notices.models import DeliveryReceipt, NoticeEvent
        from evennia_notices.services import maintain, summarize

        from .integrations.notices import EconomyNoticeSource, event_for

        ubi = self.pay("w1")
        row = EconomyNoticeReceipt.objects.get(ubi=ubi)
        self.assertEqual(row.state, State.TRANSFERRED)
        event = event_for(row)
        [item] = [i for i in self.project() if i.events[0].event_id == event.event_id]
        self.hide()
        staff = self.make_staff_visible()
        stored = StoredEvent(
            **vars(event), recipient_kind="character", recipient_id=self.character.pk
        )
        for account in (self.account, staff):
            context = self.context(account)
            self.assertEqual(self.project(context), [])
            self.assertEqual(summarize(context), (0, 0))
            outcome = EconomyNoticeSource().evaluate([stored], context)[event.event_id]
            self.assertEqual(outcome.status, "defer")
        maintain()
        maintain()
        kept = NoticeEvent.objects.get(notice__source="economy", event_id=event.event_id)
        self.assertIsNone(kept.inactive_at)
        self.assertIsNone(kept.cleared_at)
        self.assertTrue(DeliveryReceipt.objects.filter(event_id=event.event_id).exists())
        self.prepare()
        self.assertEqual(self.state(ubi=ubi), State.TRANSFERRED)
        self.reveal()
        self.assertEqual(self.state(stipend=self.stipend("reveal")), State.SUPPRESSED)
        [again] = self.project()
        self.assertEqual((again.notice.public_ref, again.text), (item.notice.public_ref, item.text))

    def test_dark_weeks_then_reveal_surface_latest_week_and_stipends(self):
        from evennia_notices.services import summarize

        self.hide()
        staff = self.make_staff_visible()
        batch.ensure_stipends(self.character)
        self.pay("w1")
        self.pay("w2")
        self.assertEqual(EconomyNoticeReceipt.objects.filter(character=self.character).count(), 0)
        for account in (self.account, staff):
            self.assertEqual(self.project(self.context(account)), [])
            self.assertEqual(summarize(self.context(account)), (0, 0))
        self.character.account = self.account
        self.reveal()
        self.prepare()
        self.assertEqual(
            self.texts(),
            [
                "Stipend received: 100 coins. See +balance.",
                "Stipend received: 50 coins. See +balance.",
                "Weekly income: 100 coins. See +balance.",
            ],
        )
        self.assertFalse(EconomyNoticeReceipt.objects.filter(ubi__week="w1").exists())
        self.assertEqual(EconomyNoticeReceipt.objects.get(ubi__week="w2").state, State.TRANSFERRED)

    def test_reveal_flip_inside_preference_off_routing_rolls_back_acknowledgement(self):
        from evennia_notices.services import route, set_preference

        set_preference(self.context(), "economy", "off")

        def hide(*args, **kwargs):
            settings.RP_ECONOMY_REVEALED = False
            return route(*args, **kwargs)

        with (
            override_settings(RP_ECONOMY_REVEALED=True),
            patch("evennia_notices.services.route", side_effect=hide),
        ):
            self.pay("reveal-race")
        self.assertEqual(
            set(EconomyNoticeReceipt.objects.values_list("state", flat=True)), {State.PENDING}
        )
        self.assertFalse(self.receipts().exists())
        self.assertIsNone(self.character.attributes.get(notices.MARKER_KEY))
        set_preference(self.context(), "economy", "summary")
        self.prepare()
        self.assertEqual(len(self.project()), 2)

    def test_preference_off_suppresses_without_replay(self):
        from evennia_notices.services import set_preference

        set_preference(self.context(), "economy", "off")
        ubi = self.pay("w1")
        self.assertEqual(self.state(ubi=ubi), State.SUPPRESSED)
        set_preference(self.context(), "economy", "summary")
        self.prepare()
        self.assertEqual(self.project(), [])

    @override_settings(RP_ECONOMY_STARTING_STIPEND=0)
    def test_capped_weeks_are_told_once_and_again_after_leaving_the_cap(self):
        credit(self.character, 500)
        first = self.pay("w1")
        self.assertEqual(
            self.texts(), ["Weekly income: 0 coins. Your purse is at its income cap. See +balance."]
        )
        second = self.pay("w2")
        self.assertEqual(self.state(ubi=second), State.SUPPRESSED)
        self.assertEqual(len(self.project()), 1)
        debit(self.character, 50)
        self.pay("w3")
        self.pay("w4")
        texts = [
            EconomyNoticeReceipt.objects.get(ubi__week=week).full_warning for week in ("w3", "w4")
        ]
        self.assertEqual(texts, [False, True])
        self.assertIn(
            "Weekly income: 50 coins. Your purse is near its income cap. See +balance.",
            self.texts(),
        )
        self.assertEqual(self.state(ubi=first), State.TRANSFERRED)
        self.assertEqual(len(self.project()), 3)

    @override_settings(RP_ECONOMY_STARTING_STIPEND=0)
    def test_zero_stipend_is_not_shown(self):
        from evennia_notices.services import summarize

        batch.ensure_stipends(self.character)
        self.assertEqual(self.state(stipend=self.stipend("starting")), State.SUPPRESSED)
        self.assertFalse(self.receipts().exists())
        self.assertEqual(summarize(self.context()), (0, 0))
        self.pay("w1")
        self.assertEqual(self.texts(), ["Weekly income: 100 coins. See +balance."])

    @override_settings(RP_ECONOMY_WEEKLY_AMOUNT=0, RP_ECONOMY_STARTING_STIPEND=0)
    def test_zero_uncapped_income_is_not_shown(self):
        first, second = self.pay("w1"), self.pay("w2")
        self.prepare()
        self.assertEqual(self.state(ubi=first), State.SUPPRESSED)
        self.assertEqual(self.state(ubi=second), State.SUPPRESSED)
        self.assertEqual(self.project(), [])
        self.assertFalse(self.receipts().exists())

    def test_legacy_marker_imports_unseen_payments_once(self):
        self.unstaged("w1")
        second = self.unstaged("w2")
        start = self.stipend("starting")
        third = self.unstaged("w3")
        with patch.object(notices, "stage_payment"):
            self.hide()
            self.reveal()
        self.character.attributes.add(notices.MARKER_KEY, [second.pk, [start.pk]])
        self.prepare()
        self.prepare()
        self.assertEqual(
            self.texts(),
            [
                "Stipend received: 50 coins. See +balance.",
                "Weekly income: 100 coins. See +balance.",
            ],
        )
        self.assertEqual(
            set(EconomyNoticeReceipt.objects.values_list("ubi_id", flat=True)) - {None},
            {third.pk},
        )
        self.assertEqual(self.receipts().count(), 2)

    def test_current_saver_list_marker_imports_nothing(self):
        self.unstaged("w1")
        ubi = self.unstaged("w2")
        start = self.stipend("starting")
        self.character.attributes.add(notices.MARKER_KEY, [ubi.pk, [start.pk]])
        marker = self.character.attributes.get(notices.MARKER_KEY)
        self.assertNotIsInstance(marker, list)
        self.prepare()
        self.assertEqual(self.project(), [])
        self.assertFalse(EconomyNoticeReceipt.objects.exists())

    def test_first_inbox_payment_imports_unseen_predecessor(self):
        self.unstaged("w1")
        second = self.unstaged("w2")
        start = self.stipend("starting")
        third = self.unstaged("w3")
        self.character.attributes.add(notices.MARKER_KEY, [second.pk, [start.pk]])
        fourth = self.pay("w4")
        self.assertEqual(self.state(ubi=third), State.TRANSFERRED)
        self.assertEqual(self.state(ubi=fourth), State.TRANSFERRED)
        self.prepare()
        self.assertEqual(self.receipts().count(), 2)

    def test_other_characters_and_accounts_never_see_notices(self):
        self.pay("w1")
        alt = create_object("evennia.DefaultCharacter", key="Economy Alt", nohome=True)
        self.account.characters.add(alt)
        self.assertEqual(self.project(self.context(character=alt)), [])
        with self.assertRaisesRegex(ValueError, "Invalid notice context"):
            self.project(self.context(self.other))

    def test_read_and_clear_leave_money_alone(self):
        from evennia_notices.services import mutate

        self.pay("w1")
        before = (
            balance(self.character),
            LedgerEntry.objects.count(),
            UBIPayment.objects.count(),
            StipendPayment.objects.count(),
        )
        for item in self.project():
            mutate(self.context(), item.notice.public_ref, "read")
            mutate(self.context(), item.notice.public_ref, "clear")
        after = (
            balance(self.character),
            LedgerEntry.objects.count(),
            UBIPayment.objects.count(),
            StipendPayment.objects.count(),
        )
        self.assertEqual(before, after)
        self.assertEqual(self.project(), [])

    def test_dry_run_and_rolled_back_batch_create_no_rows_or_receipts(self):
        self.pay("preview", dry_run=True)
        with transaction.atomic():
            self.pay("rolled-back")
            self.assertFalse(self.receipts().exists())
            transaction.set_rollback(True)
        self.assertFalse(EconomyNoticeReceipt.objects.exists())
        self.assertFalse(self.receipts().exists())

    def test_temporary_guest_puppet_leaves_owned_payments_pending(self):
        from evennia.accounts.accounts import DefaultGuest

        guest = create_account(
            "Temporary controller", None, token_urlsafe(32), typeclass=DefaultGuest
        )
        self.character.account = guest
        self.pay("w1")
        self.pay("w2")
        self.assertEqual(
            set(EconomyNoticeReceipt.objects.values_list("state", flat=True)), {State.PENDING}
        )
        self.character.msg.assert_not_called()
        self.character.account = self.account
        self.prepare()
        self.assertEqual(len(self.project()), 3)

    def test_older_interrupted_attempt_does_not_starve_later_income(self):
        with override_settings(NOTICES_ENABLED=False):
            self.pay("w1")
            EconomyNoticeReceipt.objects.update(state=State.ATTEMPTING, attempt=uuid4())
        self.pay("w2")
        self.assertEqual(len(self.project()), 1)
        self.assertEqual(EconomyNoticeReceipt.objects.get(ubi__week="w1").state, State.ATTEMPTING)

    def test_puppet_without_context_leaves_inbox_work_to_the_inbox(self):
        with patch.object(notices, "_route_fresh"):
            self.pay("w1")
        self.assertFalse(notices.prepare_character(self.character))
        self.assertEqual(
            set(EconomyNoticeReceipt.objects.values_list("state", flat=True)), {State.PENDING}
        )
        self.prepare()
        self.assertEqual(len(self.project()), 2)


@skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox is absent")
@override_settings(
    NOTICES_ENABLED=True,
    LINKS_NOTICE_SOURCES=PREFERENCE_SOURCES,
    ROOT_URLCONF=__name__,
    RP_ECONOMY_REVEALED=True,
)
class InboxEconomyPreferenceTests(EvenniaCommandTest):
    """The Economy preference row exists only while the economy is revealed, staff included."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)

    def settings_output(self):
        from evennia_notices.commands import CmdNotices

        return self.call(CmdNotices(), "/settings")

    def page(self, account, character=None):
        from importlib import import_module

        from django.test import RequestFactory

        from evennia_notices import views

        request = RequestFactory().get("/notices/preferences/")
        request.user = account
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        if character is not None:
            request.session["puppet"] = character.pk
        return views.preferences(request).render()

    def assert_hidden(self):
        output = self.settings_output()
        self.assertIn("other: summary; decisions: immediate", output)
        self.assertNotIn("economy", output)
        for response in (self.page(self.account, self.char1), self.page(self.account2)):
            self.assertContains(response, 'value="other"')
            self.assertContains(response, "Unrelated alerts")
            self.assertNotContains(response, 'value="economy"')
            self.assertNotContains(response, "Economy")

    def test_hidden_economy_preference_is_absent_and_refused_for_staff(self):
        from evennia_notices.commands import CmdNotices
        from evennia_notices.models import SourcePreference

        runtime.set("RP_ECONOMY_REVEALED", False)
        # A staff-visibility gate would show the row here; the reveal gate must not.
        self.assertTrue(conf.visible(self.char1))
        self.assert_hidden()
        self.assertEqual(
            self.call(CmdNotices(), "/set economy=off"), self.call(CmdNotices(), "/set nosuch=off")
        )
        self.assertFalse(SourcePreference.objects.filter(source="economy").exists())

    def test_stored_choice_survives_hiding_and_applies_after_live_reveal(self):
        from evennia_notices.commands import CmdNotices
        from evennia_notices.models import SourcePreference

        self.assertEqual(self.call(CmdNotices(), "/set economy=off"), "Notice preference saved.")
        runtime.set("RP_ECONOMY_REVEALED", False)
        self.assert_hidden()
        self.assertEqual(SourcePreference.objects.get(source="economy").mode, "off")
        runtime.set("RP_ECONOMY_REVEALED", True)
        self.assertIn("economy: off; decisions: summary", self.settings_output())
        response = self.page(self.account, self.char1)
        self.assertContains(response, 'value="economy"')
        self.assertContains(response, "Economy")
