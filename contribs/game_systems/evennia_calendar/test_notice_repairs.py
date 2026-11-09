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
