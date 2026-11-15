# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Canonical source receipts and authoritative connected-only guest delivery."""

import secrets
from datetime import timedelta
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.apps import apps
from django.test import override_settings
from django.utils import timezone
from evennia.utils.create import create_account, create_object
from evennia.utils.test_resources import EvenniaTest

from evennia_calendar import notices
from evennia_calendar.models import RSVP, CalendarEvent, CalendarNotice

SOURCE = {"calendar": "evennia_calendar.integrations.notices.CalendarNoticeSource"}


@override_settings(NOTICES_ENABLED=True, LINKS_NOTICE_SOURCES=SOURCE)
class CanonicalReceiptTests(EvenniaTest):
    """Every alias consults the same source-owned backend/attempt receipt."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.event = CalendarEvent.objects.create(
            title="Canonical selection", scheduled_time=timezone.now() + timedelta(days=4)
        )
        self.rsvp = RSVP.objects.create(
            event=self.event, character=self.char1, status=RSVP.Status.LOTTERY_SELECTED
        )
        self.notice_session = SimpleNamespace(
            get_account=lambda: self.account, get_puppet=lambda: self.char1, msg=Mock()
        )

    def legacy(self):
        return CalendarNotice.objects.create(
            rsvp=self.rsvp,
            character=self.char1,
            kind="drawn",
            status=self.rsvp.status,
            message="Original legacy source text",
        )

    @skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox physically absent")
    def test_reverse_order_is_one_event_and_preserves_both_source_rows(self):
        from evennia_notices.models import DeliveryReceipt

        first, second = self.legacy(), self.legacy()
        self.assertEqual(notices.route_notice(second.pk), "inbox")
        self.assertEqual(notices.route_notice(first.pk), "duplicate")
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.envelope, second.envelope)
        self.assertEqual(first.envelope["payload"]["notice"], first.pk)
        self.assertEqual(DeliveryReceipt.objects.filter(source="calendar").count(), 1)
        self.assertEqual(CalendarNotice.objects.count(), 2)
        self.assertEqual(first.message, "Original legacy source text")
        self.assertEqual(second.message, "Original legacy source text")

    @override_settings(NOTICES_ENABLED=False, LINKS_NOTICE_SOURCES={})
    def test_alias_never_repeats_completed_fallback_in_either_order(self):
        for reverse in (False, True):
            self.rsvp.release()
            self.rsvp.status = RSVP.Status.LOTTERY_SELECTED
            self.rsvp.save(update_fields=["status", "updated_at"])
            first, second = self.legacy(), self.legacy()
            order = (second, first) if reverse else (first, second)
            with (
                patch.object(notices, "_connected_sessions", return_value=[self.notice_session]),
                patch.object(type(self.char1), "msg") as message,
            ):
                for row in order:
                    with self.captureOnCommitCallbacks(execute=True):
                        notices.route_notice(row.pk)
                self.assertEqual(message.call_count, 1)
            first.refresh_from_db()
            second.refresh_from_db()
            self.assertEqual(first.route_state, "fallback")
            self.assertEqual(second.route_state, "fallback")
            self.assertIsNotNone(second.delivered_at)

    @skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox physically absent")
    def test_alias_honors_canonical_inbox_after_disable_and_registry_removal(self):
        first, second = self.legacy(), self.legacy()
        self.assertEqual(notices.route_notice(first.pk), "inbox")
        with override_settings(NOTICES_ENABLED=False, LINKS_NOTICE_SOURCES={}):
            with (
                patch.object(notices, "_connected_sessions", return_value=[self.notice_session]),
                patch.object(type(self.char1), "msg") as message,
                self.captureOnCommitCallbacks(execute=True),
            ):
                self.assertEqual(notices.route_notice(second.pk), "duplicate")
            message.assert_not_called()
        self.assertEqual(notices.route_notice(second.pk), "duplicate")
        self.assertEqual(CalendarNotice.objects.get(pk=second.pk).route_state, "inbox")

    @override_settings(NOTICES_ENABLED=False, LINKS_NOTICE_SOURCES={})
    def test_attempted_and_uncertain_canonical_claim_blocks_alias_retry(self):
        first, second = self.legacy(), self.legacy()
        with (
            patch.object(notices, "_connected_sessions", return_value=[self.notice_session]),
            patch.object(
                type(self.char1), "msg", side_effect=RuntimeError("Socket outcome uncertain")
            ) as message,
        ):
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                notices.route_notice(second.pk)
                self.assertEqual(notices.route_notice(first.pk), "held")
            self.assertEqual(CalendarNotice.objects.get(pk=first.pk).route_state, "attempting")
            for callback in callbacks:
                callback()
            self.assertEqual(message.call_count, 1)
            self.assertEqual(CalendarNotice.objects.get(pk=first.pk).route_state, "uncertain")
            self.assertEqual(notices.route_notice(second.pk), "held")
            self.assertEqual(message.call_count, 1)
        self.assertIsNone(CalendarNotice.objects.get(pk=second.pk).delivered_at)

    @skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox physically absent")
    def test_legacy_import_and_producer_replay_share_one_transition(self):
        from evennia_notices.models import DeliveryReceipt

        row = self.legacy()
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        notices.on_lottery_selected(None, event=self.event, rsvp=self.rsvp)
        self.assertEqual(DeliveryReceipt.objects.filter(source="calendar").count(), 1)
        self.assertEqual(CalendarNotice.objects.count(), 1)

    @skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox physically absent")
    def test_producer_then_legacy_import_share_one_transition(self):
        from evennia_notices.models import DeliveryReceipt

        row = self.legacy()
        notices.on_lottery_selected(None, event=self.event, rsvp=self.rsvp)
        notices.route_notice(row.pk)
        self.assertEqual(DeliveryReceipt.objects.filter(source="calendar").count(), 1)
        self.assertEqual(CalendarNotice.objects.count(), 1)


@override_settings(NOTICES_ENABLED=True, LINKS_NOTICE_SOURCES=SOURCE)
class GuestReceiptTests(EvenniaTest):
    """Real DefaultGuest ownership works without ordinary playable web scope."""

    def setUp(self):
        super().setUp()
        self.guest_account = create_account(
            "Calendar guest fixture",
            None,
            secrets.token_urlsafe(48),
            typeclass="evennia.accounts.accounts.DefaultGuest",
        )
        self.guest_character = create_object(
            "evennia.objects.objects.DefaultCharacter",
            key="Calendar guest character",
            location=self.room1,
        )
        self.guest_account.characters.add(self.guest_character)
        self.guest_character.account = self.guest_account
        self.event = CalendarEvent.objects.create(
            title="Guest selection fixture", scheduled_time=timezone.now() + timedelta(days=4)
        )
        self.rsvp = RSVP.objects.create(
            event=self.event, character=self.guest_character, status=RSVP.Status.LOTTERY_SELECTED
        )
        self.guest_session = SimpleNamespace(
            get_account=lambda: self.guest_account,
            get_puppet=lambda: self.guest_character,
            msg=Mock(),
        )

    def test_valid_connected_guest_delivers_once_without_new_persistence(self):
        from evennia_links.characters import web_roster
        from evennia_links.guests import is_guest

        self.assertTrue(is_guest(self.guest_account))
        self.assertEqual(web_roster(self.guest_account), [])
        with patch.object(notices, "_connected_sessions", return_value=[self.guest_session]):
            self.assertTrue(notices.notify(self.rsvp, "drawn", "Not trusted", origin="lottery"))
            self.assertFalse(notices.notify(self.rsvp, "drawn", "Not trusted", origin="lottery"))
        self.assertEqual(self.guest_session.msg.call_count, 1)
        self.assertFalse(CalendarNotice.objects.exists())

    def test_stale_released_guest_rsvp_never_emits_old_offer(self):
        RSVP.objects.get(pk=self.rsvp.pk).release()
        with patch.object(notices, "_connected_sessions", return_value=[self.guest_session]):
            self.assertFalse(notices.notify(self.rsvp, "drawn", "Stale text", origin="lottery"))
        self.guest_session.msg.assert_not_called()
        self.assertFalse(CalendarNotice.objects.exists())

    def test_same_status_cycle_and_recipient_change_invalidate_cached_guest_rsvp(self):
        current = RSVP.objects.get(pk=self.rsvp.pk)
        current.release()
        current.status = RSVP.Status.LOTTERY_SELECTED
        current.save(update_fields=["status", "updated_at"])
        with patch.object(notices, "_connected_sessions", return_value=[self.guest_session]):
            self.assertFalse(notices.notify(self.rsvp, "drawn", "Stale cycle", origin="lottery"))
            current.character = self.char1
            current.save(update_fields=["character", "updated_at"])
            self.assertFalse(notices.notify(self.rsvp, "drawn", "Stale owner", origin="lottery"))
        self.guest_session.msg.assert_not_called()
        self.assertFalse(CalendarNotice.objects.exists())

    def test_cached_cancellation_and_deadline_are_reloaded_before_guest_socket(self):
        self.assertEqual(self.rsvp.event.pk, self.event.pk)  # Cache before DB cancellation.
        CalendarEvent.objects.filter(pk=self.event.pk).update(is_cancelled=True)
        with patch.object(notices, "_connected_sessions", return_value=[self.guest_session]):
            self.assertFalse(notices.notify(self.rsvp, "drawn", "Cancelled", origin="lottery"))
            CalendarEvent.objects.filter(pk=self.event.pk).update(
                is_cancelled=False, scheduled_time=timezone.now() + timedelta(hours=24)
            )
            self.assertFalse(notices.notify(self.rsvp, "drawn", "Expired", origin="lottery"))
        self.guest_session.msg.assert_not_called()

    def test_existing_guest_source_row_is_consumed_once_in_both_backend_modes(self):
        for enabled in (True, False):
            self.rsvp.release()
            self.rsvp.status = RSVP.Status.LOTTERY_SELECTED
            self.rsvp.save(update_fields=["status", "updated_at"])
            row = CalendarNotice.objects.create(
                rsvp=self.rsvp,
                character=self.guest_character,
                kind="drawn",
                status=self.rsvp.status,
                message="Existing guest history",
            )
            with (
                override_settings(NOTICES_ENABLED=enabled),
                patch.object(notices, "_connected_sessions", return_value=[self.guest_session]),
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    notices.route_notice(row.pk)
                self.assertEqual(notices.route_notice(row.pk), "duplicate")
            row.refresh_from_db()
            self.assertEqual(row.route_state, "fallback")
            self.assertIsNotNone(row.delivered_at)
            self.assertEqual(row.message, "Existing guest history")
        self.assertEqual(self.guest_session.msg.call_count, 2)
        self.assertEqual(CalendarNotice.objects.count(), 2)

    def test_existing_guest_offline_or_uncertain_delivery_does_not_false_acknowledge(self):
        row = CalendarNotice.objects.create(
            rsvp=self.rsvp,
            character=self.guest_character,
            kind="drawn",
            status=self.rsvp.status,
            message="Existing guest history",
        )
        with patch.object(notices, "_connected_sessions", return_value=[]):
            notices.route_notice(row.pk)
        row.refresh_from_db()
        self.assertIsNone(row.delivered_at)
        with (
            patch.object(notices, "_connected_sessions", return_value=[self.guest_session]),
            patch.object(
                self.guest_session, "msg", side_effect=RuntimeError("Uncertain")
            ) as message,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                notices.route_notice(row.pk)
            self.assertEqual(message.call_count, 1)
            self.assertEqual(notices.route_notice(row.pk), "held")
        row.refresh_from_db()
        self.assertIsNone(row.delivered_at)
        self.assertEqual(row.route_state, "uncertain")

    def test_guest_producer_honors_existing_mixed_consumption_without_new_retention(self):
        first = CalendarNotice.objects.create(
            rsvp=self.rsvp,
            character=self.guest_character,
            kind="drawn",
            status=self.rsvp.status,
            message="Earlier guest queue",
        )
        later = CalendarNotice.objects.create(
            rsvp=self.rsvp,
            character=self.guest_character,
            kind="drawn",
            status=self.rsvp.status,
            message="Delivered guest history",
            delivered_at=timezone.now(),
        )
        stamp = later.delivered_at
        with patch.object(notices, "_connected_sessions", return_value=[self.guest_session]):
            self.assertFalse(notices.notify(self.rsvp, "drawn", "Replayed guest", origin="lottery"))
        self.guest_session.msg.assert_not_called()
        self.assertEqual(CalendarNotice.objects.count(), 2)
        first.refresh_from_db()
        later.refresh_from_db()
        self.assertIsNotNone(first.delivered_at)
        self.assertEqual(later.delivered_at, stamp)

    def test_empty_guest_puppet_retains_no_notice_cursor_or_inbox_record(self):
        from django.apps import apps

        from evennia_calendar.models import CalendarNoticeCursor

        before = CalendarNoticeCursor.objects.count()
        notices.on_post_puppet(self.guest_character, session=self.guest_session)
        self.assertEqual(CalendarNoticeCursor.objects.count(), before)
        self.assertFalse(CalendarNotice.objects.exists())
        if apps.is_installed("evennia_notices"):
            from evennia_notices.models import DeliveryReceipt, Notice, Recipient

            self.assertFalse(Notice.objects.exists())
            self.assertFalse(DeliveryReceipt.objects.exists())
            self.assertFalse(Recipient.objects.exists())

    def test_wrong_connected_puppet_or_owner_and_offline_guest_never_receive(self):
        with patch.object(notices, "_connected_sessions", return_value=[]):
            self.assertFalse(notices.notify(self.rsvp, "drawn", "Offline", origin="lottery"))
        wrong = SimpleNamespace(
            get_account=lambda: self.account2, get_puppet=lambda: self.guest_character, msg=Mock()
        )
        with patch.object(notices, "_connected_sessions", return_value=[wrong]):
            self.assertFalse(notices.notify(self.rsvp, "drawn", "Wrong owner", origin="lottery"))
        wrong.get_account = lambda: self.guest_account
        wrong.get_puppet = lambda: self.char1
        with patch.object(notices, "_connected_sessions", return_value=[wrong]):
            self.assertFalse(notices.notify(self.rsvp, "drawn", "Wrong puppet", origin="lottery"))
        wrong.msg.assert_not_called()
        self.assertFalse(CalendarNotice.objects.exists())

    @skipUnless(apps.is_installed("evennia_social"), "Optional Social physically absent")
    def test_guest_human_offer_rechecks_strict_shared_ignore(self):
        from evennia_social import ignore

        self.account2.is_superuser = False
        self.account2.permissions.clear()
        self.rsvp.status = RSVP.Status.INVITED
        self.rsvp.save(update_fields=["status", "updated_at"])
        ignore.set_entry(self.guest_account, self.char2, ignore.HIDDEN)
        with patch.object(notices, "_connected_sessions", return_value=[self.guest_session]):
            self.assertFalse(
                notices.notify(
                    self.rsvp,
                    "invited",
                    "Ignored invitation",
                    origin="waitlist_offer",
                    actor=self.char2,
                )
            )
        self.guest_session.msg.assert_not_called()
        self.assertFalse(CalendarNotice.objects.exists())


@override_settings(LINKS_NOTICE_SOURCES=SOURCE)
class MixedConsumptionTests(EvenniaTest):
    """Any proven member receipt, not its primary-key order, prevents replay."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.notice_session = SimpleNamespace(
            get_account=lambda: self.account, get_puppet=lambda: self.char1, msg=Mock()
        )

    def pair(self, state):
        event = CalendarEvent.objects.create(
            title="Mixed consumption", scheduled_time=timezone.now() + timedelta(days=4)
        )
        rsvp = RSVP.objects.create(
            event=event, character=self.char1, status=RSVP.Status.LOTTERY_SELECTED
        )
        first = CalendarNotice.objects.create(
            rsvp=rsvp,
            character=self.char1,
            kind="drawn",
            status=rsvp.status,
            message="Earlier pending history",
        )
        stamp = timezone.now()
        later = CalendarNotice.objects.create(
            rsvp=rsvp,
            character=self.char1,
            kind="drawn",
            status=rsvp.status,
            message="Later consumed history",
            route_state="pending" if state == "legacy" else state,
            delivered_at=stamp if state in {"legacy", "inbox", "fallback"} else None,
            routed_at=stamp,
        )
        return rsvp, first, later, stamp

    def test_later_receipt_or_claim_governs_every_entry_and_backend(self):
        for enabled in (True, False):
            for state in ("legacy", "inbox", "fallback", "attempting", "uncertain"):
                if enabled and not apps.is_installed("evennia_notices"):
                    continue
                for entry in ("earlier", "later", "producer"):
                    with self.subTest(enabled=enabled, state=state, entry=entry):
                        rsvp, first, later, stamp = self.pair(state)
                        if apps.is_installed("evennia_notices"):
                            from evennia_notices.models import DeliveryReceipt

                            before = DeliveryReceipt.objects.count()
                        self.notice_session.msg.reset_mock()
                        with (
                            override_settings(NOTICES_ENABLED=enabled),
                            patch.object(
                                notices, "_connected_sessions", return_value=[self.notice_session]
                            ),
                            patch.object(type(self.char1), "msg") as message,
                            self.captureOnCommitCallbacks(execute=True),
                        ):
                            if entry == "producer":
                                notices.notify(rsvp, "drawn", "Replay", origin="lottery")
                            else:
                                notices.route_notice(first.pk if entry == "earlier" else later.pk)
                        self.assertEqual(message.call_count + self.notice_session.msg.call_count, 0)
                        if apps.is_installed("evennia_notices"):
                            self.assertEqual(DeliveryReceipt.objects.count(), before)
                        first.refresh_from_db()
                        later.refresh_from_db()
                        if state in {"legacy", "inbox", "fallback"}:
                            self.assertEqual(later.delivered_at, stamp)
                            self.assertIsNotNone(first.delivered_at)
                        else:
                            self.assertIsNone(first.delivered_at)
                            self.assertIsNone(later.delivered_at)
                        self.assertEqual(later.message, "Later consumed history")

    @skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox physically absent")
    @override_settings(NOTICES_ENABLED=True)
    def test_older_ambiguous_receipt_does_not_consume_current_transition(self):
        from evennia_notices.models import DeliveryReceipt

        rsvp, first, later, _ = self.pair("legacy")
        CalendarNotice.objects.filter(pk=later.pk).update(
            created_at=rsvp.updated_at - timedelta(seconds=1)
        )
        self.assertEqual(notices.route_notice(first.pk), "inbox")
        self.assertEqual(DeliveryReceipt.objects.count(), 1)

    @skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox physically absent")
    @override_settings(NOTICES_ENABLED=True)
    def test_reconciliation_preserves_frozen_envelope_fingerprint_and_history_time(self):
        from dataclasses import asdict

        from evennia_calendar.integrations.notices import event_for
        from evennia_links.notices import NoticeEvent, SubjectRef, notify
        from evennia_notices.models import DeliveryReceipt

        rsvp, first, later, stamp = self.pair("inbox")
        event = NoticeEvent(
            "already-retained-mixed-event",
            later.created_at,
            subject=SubjectRef("rsvp", str(rsvp.pk)),
            payload={
                "notice": later.pk,
                "event": rsvp.event_id,
                "generation": str(rsvp.notice_generation),
                "origin": "lottery",
                "status": rsvp.status,
            },
            action_kind="lottery_selection",
        )
        envelope = asdict(event)
        envelope["occurred_at"] = event.occurred_at.isoformat()
        later.generation, later.origin, later.provenance_known, later.envelope = (
            rsvp.notice_generation,
            "lottery",
            True,
            envelope,
        )
        later.save(update_fields=["generation", "origin", "provenance_known", "envelope"])
        later.refresh_from_db()
        envelope = later.envelope.copy()
        notify(self.char1, source="calendar", event=event_for(later))
        receipt = DeliveryReceipt.objects.get()
        original_fingerprint = receipt.fingerprint
        self.assertEqual(notices.route_notice(first.pk), "duplicate")
        later.refresh_from_db()
        receipt.refresh_from_db()
        self.assertEqual(later.delivered_at, stamp)
        self.assertEqual(later.envelope, envelope)
        self.assertEqual(receipt.fingerprint, original_fingerprint)
        self.assertEqual(DeliveryReceipt.objects.count(), 1)

    @skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox physically absent")
    @override_settings(NOTICES_ENABLED=True)
    def test_unproven_member_does_not_consume_a_known_current_event(self):
        from evennia_notices.models import DeliveryReceipt

        rsvp, first, later, stamp = self.pair("legacy")
        later.event_key, later.generation, later.origin = (
            "unproven-custom-source",
            rsvp.notice_generation,
            "lottery",
        )
        later.save(update_fields=["event_key", "generation", "origin"])
        self.assertEqual(notices.route_notice(first.pk), "inbox")
        self.assertEqual(DeliveryReceipt.objects.count(), 1)
        self.assertEqual(CalendarNotice.objects.get(pk=later.pk).delivered_at, stamp)


@override_settings(NOTICES_ENABLED=True, LINKS_NOTICE_SOURCES=SOURCE)
class SourceRetryTests(EvenniaTest):
    """A configured-source failure retains work and rolls back any partial Inbox."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)

    def rsvp(self):
        event = CalendarEvent.objects.create(
            title="Retry fixture", scheduled_time=timezone.now() + timedelta(days=4)
        )
        return RSVP.objects.create(
            event=event, character=self.char1, status=RSVP.Status.LOTTERY_SELECTED
        )

    def test_unavailable_or_malformed_source_preserves_new_outbox_for_repair(self):
        registries = ({"calendar": "unavailable_calendar_source.Adapter"}, ["malformed"])
        for registry in registries:
            with self.subTest(registry=registry):
                rsvp = self.rsvp()
                with (
                    override_settings(LINKS_NOTICE_SOURCES=registry),
                    patch.object(type(self.char1), "msg") as message,
                ):
                    notices.on_lottery_selected(None, event=rsvp.event, rsvp=rsvp)
                message.assert_not_called()
                rows = list(CalendarNotice.objects.filter(rsvp=rsvp))
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertIsNone(row.delivered_at)
                self.assertEqual(row.route_state, "pending")
                self.assertTrue(row.envelope)
                frozen = row.envelope.copy()
                if apps.is_installed("evennia_notices"):
                    self.assertEqual(notices.route_notice(row.pk), "inbox")
                    row.refresh_from_db()
                    self.assertEqual(row.envelope, frozen)

    @skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox physically absent")
    def test_backend_exception_after_retention_rolls_back_inbox_but_keeps_source(self):
        from evennia_notices import services
        from evennia_notices.models import DeliveryReceipt, NoticeEvent

        original = services.route

        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("Backend outcome uncertain after retention")

        rsvp = self.rsvp()
        with (
            patch.object(services, "route", side_effect=interrupted),
            patch.object(services, "_immediate") as hint,
            patch.object(type(self.char1), "msg") as message,
            self.captureOnCommitCallbacks(execute=True),
        ):
            notices.on_lottery_selected(None, event=rsvp.event, rsvp=rsvp)
        message.assert_not_called()
        hint.assert_not_called()
        row = CalendarNotice.objects.get(rsvp=rsvp)
        self.assertIsNone(row.delivered_at)
        self.assertEqual(row.route_state, "pending")
        self.assertFalse(DeliveryReceipt.objects.exists())
        self.assertFalse(NoticeEvent.objects.exists())
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        self.assertEqual(DeliveryReceipt.objects.count(), 1)
