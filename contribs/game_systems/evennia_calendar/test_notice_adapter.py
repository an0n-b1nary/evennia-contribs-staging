# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Calendar transition identity, durable routing and current inbox presentation."""

from datetime import timedelta
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import call, patch

from django.apps import apps
from django.test import override_settings
from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest

from evennia_calendar import notices
from evennia_calendar.models import RSVP, CalendarEvent, CalendarNotice


@override_settings(NOTICES_ENABLED=False, LINKS_NOTICE_SOURCES={})
class CalendarTransitionTests(EvenniaTest):
    """A repeated transition is one event; a later status cycle is a different event."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.event = CalendarEvent.objects.create(
            title="Example draw", scheduled_time=timezone.now() + timedelta(days=4)
        )
        self.rsvp = RSVP.objects.create(
            event=self.event, character=self.char1, status=RSVP.Status.LOTTERY_SELECTED
        )

    def test_repeated_lottery_signal_reuses_transition(self):
        with patch.object(notices, "is_online", return_value=False):
            notices.on_lottery_selected(None, event=self.event, rsvp=self.rsvp)
            notices.on_lottery_selected(None, event=self.event, rsvp=self.rsvp)
        self.assertEqual(CalendarNotice.objects.count(), 1)

    def test_status_cycle_changes_generation_and_never_revives_old_notice(self):
        with patch.object(notices, "is_online", return_value=False):
            notices.on_lottery_selected(None, event=self.event, rsvp=self.rsvp)
        old = CalendarNotice.objects.get()
        generation = self.rsvp.notice_generation
        self.rsvp.release()
        self.rsvp.status = RSVP.Status.LOTTERY_SELECTED
        self.rsvp.save(update_fields=["status", "updated_at"])
        self.assertNotEqual(self.rsvp.notice_generation, generation)
        from evennia_calendar.integrations.notices import currentness

        old.refresh_from_db()
        self.assertEqual(currentness(old).status, "invalid")
        notices.on_lottery_selected(None, event=self.event, rsvp=self.rsvp)
        self.assertEqual(CalendarNotice.objects.count(), 2)

    def test_unrelated_partial_save_does_not_restore_stale_status_or_generation(self):
        stale = RSVP.objects.get(pk=self.rsvp.pk)
        self.rsvp.release()
        stale.character_name = "Renamed fixture"
        stale.save(update_fields=["character_name"])
        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status, RSVP.Status.RELEASED)
        self.assertEqual(stale.notice_generation, self.rsvp.notice_generation)
        self.assertEqual(self.rsvp.character_name, "Renamed fixture")

    def test_empty_partial_save_is_a_true_no_op(self):
        generation = self.rsvp.notice_generation
        self.rsvp.status = RSVP.Status.RELEASED
        self.rsvp.save(update_fields=[])
        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status, RSVP.Status.LOTTERY_SELECTED)
        self.assertEqual(self.rsvp.notice_generation, generation)

    def test_stale_full_and_transition_saves_are_rejected(self):
        stale = RSVP.objects.get(pk=self.rsvp.pk)
        self.rsvp.release()
        with self.assertRaises(ValueError):
            stale.save()
        with self.assertRaises(ValueError):
            stale.save(update_fields=["status"])
        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status, RSVP.Status.RELEASED)

    def test_expression_lifecycle_write_is_rejected(self):
        from django.db.models import F

        self.rsvp.status = F("status")
        with self.assertRaises(ValueError):
            self.rsvp.save(update_fields=["status"])

    def test_force_insert_failure_preserves_generation(self):
        from django.db import IntegrityError, transaction

        generation = self.rsvp.notice_generation
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self.rsvp.save(force_insert=True)
        self.assertEqual(self.rsvp.notice_generation, generation)

    def test_same_status_save_keeps_generation(self):
        generation = self.rsvp.notice_generation
        self.rsvp.save(update_fields=["status"])
        self.assertEqual(self.rsvp.notice_generation, generation)

    def test_unknown_custom_invitation_never_sends_raw_text(self):
        self.rsvp.status = RSVP.Status.INVITED
        self.rsvp.save(update_fields=["status", "updated_at"])
        with patch.object(self.char1, "msg") as message:
            notices.notify(self.rsvp, "invited", "Unknown private identity")
            notices.deliver_pending(self.char1)
        message.assert_not_called()
        self.assertIsNone(CalendarNotice.objects.get().delivered_at)

    def test_held_rows_do_not_starve_later_eligible_pending_work(self):
        self.rsvp.status = RSVP.Status.INVITED
        self.rsvp.save(update_fields=["status", "updated_at"])
        for _ in range(5):
            CalendarNotice.objects.create(
                rsvp=self.rsvp,
                character=self.char1,
                kind="invited",
                status="invited",
                message="Unknown legacy host",
            )
        other = RSVP.objects.create(
            event=self.event, character=self.char2, status=RSVP.Status.LOTTERY_SELECTED
        )
        row = CalendarNotice.objects.create(
            rsvp=other,
            character=self.char2,
            kind="drawn",
            status=other.status,
            message="Legacy draw",
        )
        pages = [notices.transfer_pending(batch_size=2) for _ in range(3)]
        self.assertTrue(pages[-1]["complete"])
        row.refresh_from_db()
        self.assertTrue(row.envelope)
        self.assertIsNotNone(row.generation)
        self.assertEqual(CalendarNotice.objects.filter(kind="invited", envelope={}).count(), 0)
        self.assertEqual(
            CalendarNotice.objects.filter(kind="invited", delivered_at__isnull=True).count(), 5
        )

    def test_already_delivered_notify_returns_false_without_sending_again(self):
        session = SimpleNamespace(get_account=lambda: self.account, get_puppet=lambda: self.char1)
        with (
            patch.object(notices, "_connected_sessions", return_value=[session]),
            patch.object(self.char1, "msg") as message,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                notices.notify(self.rsvp, "drawn", "Draw", origin="lottery")
            self.assertEqual(message.call_count, 1)
            self.assertFalse(notices.notify(self.rsvp, "drawn", "Draw", origin="lottery"))
            self.assertEqual(message.call_count, 1)

    def session_for_character(self):
        return SimpleNamespace(get_account=lambda: self.account, get_puppet=lambda: self.char1)

    def claim_draw(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            notices.notify(self.rsvp, "drawn", "Draw", origin="lottery")
        row = CalendarNotice.objects.get()
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(row.route_state, "attempting")
        self.assertIsNotNone(row.routed_at)
        self.assertIsNone(row.delivered_at)
        return row, callbacks[0]

    def assert_released_and_delivers_once(self, row, message, session, text):
        row.refresh_from_db()
        self.assertEqual(
            (row.route_state, row.routed_at, row.delivered_at), ("pending", None, None)
        )
        message.assert_not_called()
        with self.captureOnCommitCallbacks(execute=True):
            notices.deliver_pending(self.char1)
        self.assertEqual(notices.route_notice(row.pk), "duplicate")
        message.assert_called_once_with(text, session=session)
        row.refresh_from_db()
        self.assertEqual(row.route_state, "fallback")
        self.assertIsNotNone(row.delivered_at)

    @skipUnless(apps.is_installed("evennia_social"), "Optional Social is physically absent")
    def test_standalone_callback_releases_claim_after_ignore_change(self):
        from evennia_social import ignore

        for account in (self.account, self.account2):
            account.is_superuser = False
            account.permissions.clear()
        self.rsvp.status = RSVP.Status.INVITED
        self.rsvp.save(update_fields=["status", "updated_at"])
        session = self.session_for_character()
        with (
            patch.object(notices, "_connected_sessions", return_value=[session]),
            patch.object(self.char1, "msg") as message,
        ):
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                notices.notify(
                    self.rsvp, "invited", "Known invitation", origin="invitation", actor=self.char2
                )
            row = CalendarNotice.objects.get()
            self.assertEqual(len(callbacks), 1)
            self.assertEqual(row.route_state, "attempting")
            message.assert_not_called()
            ignore.set_entry(self.account, self.char2, ignore.HIDDEN)
            callbacks[0]()
            ignore.remove_entry(self.account, self.char2)
            self.assert_released_and_delivers_once(row, message, session, "Known invitation")

    def test_standalone_releases_claim_after_disconnect_or_preparation_error(self):
        session = self.session_for_character()
        with (
            patch.object(notices, "_connected_sessions", return_value=[session]),
            patch.object(self.char1, "msg") as message,
        ):
            row, finish = self.claim_draw()
            message.assert_not_called()
            with patch.object(session, "get_account", return_value=None):
                finish()
            row.refresh_from_db()
            self.assertEqual(
                (row.route_state, row.routed_at, row.delivered_at), ("pending", None, None)
            )
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                self.assertEqual(notices.route_notice(row.pk), "held")
            self.assertEqual(len(callbacks), 1)
            row.refresh_from_db()
            self.assertEqual(row.route_state, "attempting")
            message.assert_not_called()
            with patch.object(
                session, "get_account", side_effect=RuntimeError("Context unavailable")
            ):
                callbacks[0]()
            self.assert_released_and_delivers_once(row, message, session, "Draw")

    def test_standalone_releases_claim_if_guest_classification_changes(self):
        session = self.session_for_character()
        with (
            patch.object(notices, "_connected_sessions", return_value=[session]),
            patch.object(self.char1, "msg") as message,
        ):
            row, finish = self.claim_draw()
            self.char1.tags.add("character", category="guest")
            finish()
            self.char1.tags.remove("character", category="guest")
            self.assert_released_and_delivers_once(row, message, session, "Draw")

    def test_standalone_sends_individually_after_a_raising_send_and_rechecks_next_puppet(self):
        first, removed, successful, ineligible = (self.session_for_character() for _ in range(4))
        ineligible.get_puppet = lambda: self.char2

        def send(text, *, session):
            if session is first:
                removed.get_puppet = lambda: self.char2
                raise RuntimeError("Socket outcome uncertain")

        with (
            patch.object(
                notices,
                "_connected_sessions",
                return_value=[first, removed, successful, ineligible],
            ),
            patch.object(self.char1, "msg", side_effect=send) as message,
        ):
            row, finish = self.claim_draw()
            message.assert_not_called()
            finish()
            self.assertEqual(notices.route_notice(row.pk), "duplicate")
        self.assertEqual(
            message.call_args_list, [call("Draw", session=first), call("Draw", session=successful)]
        )
        row.refresh_from_db()
        self.assertEqual(row.route_state, "fallback")
        self.assertIsNotNone(row.delivered_at)

    def test_standalone_preserves_uncertainty_if_raising_send_invalidates_rsvp(self):
        first, second = self.session_for_character(), self.session_for_character()

        def send(text, *, session):
            self.rsvp.release()
            raise RuntimeError("Socket outcome uncertain")

        with (
            patch.object(notices, "_connected_sessions", return_value=[first, second]),
            patch.object(self.char1, "msg", side_effect=send) as message,
        ):
            row, finish = self.claim_draw()
            message.assert_not_called()
            finish()
            self.assertEqual(notices.route_notice(row.pk), "held")
        message.assert_called_once_with("Draw", session=first)
        row.refresh_from_db()
        self.assertEqual(row.route_state, "uncertain")
        self.assertIsNone(row.delivered_at)

    def test_standalone_acknowledges_cancellation_before_any_send(self):
        with (
            patch.object(
                notices, "_connected_sessions", return_value=[self.session_for_character()]
            ),
            patch.object(self.char1, "msg") as message,
        ):
            row, finish = self.claim_draw()
            message.assert_not_called()
            CalendarEvent.objects.filter(pk=self.event.pk).update(is_cancelled=True)
            finish()
        message.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.route_state, "invalid")
        self.assertIsNotNone(row.delivered_at)

    def test_guest_delivery_creates_no_new_source_content(self):
        self.char1.tags.add("character", category="guest")
        notices.on_lottery_selected(None, event=self.event, rsvp=self.rsvp)
        self.assertFalse(CalendarNotice.objects.exists())


CALENDAR_SOURCE = {"calendar": "evennia_calendar.integrations.notices.CalendarNoticeSource"}


@skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox is physically absent")
@override_settings(NOTICES_ENABLED=True, LINKS_NOTICE_SOURCES=CALENDAR_SOURCE)
class CalendarInboxTests(EvenniaTest):
    """Exercise the production Calendar source through real Inbox persistence."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.event = CalendarEvent.objects.create(
            title="Lantern fixture",
            scheduled_time=timezone.now() + timedelta(days=4),
            creator=self.char2,
        )
        self.rsvp = RSVP.objects.create(
            event=self.event, character=self.char1, status=RSVP.Status.LOTTERY_SELECTED
        )
        from evennia_links.notices import NoticeContext

        self.context = NoticeContext(self.account, self.char1)

    def emit(self, origin="lottery", actor=None):
        kind = {
            "lottery": "drawn",
            "invitation": "invited",
            "waitlist_offer": "invited",
            "seated": "seated",
            "reminder": "reminder",
        }[origin]
        notices.notify(
            self.rsvp, kind, "Stored text never grants visibility", origin=origin, actor=actor
        )
        return CalendarNotice.objects.order_by("pk").last()

    def project(self, mode="unread"):
        from evennia_notices.services import project

        return project(self.context, mode)

    def test_lottery_read_is_still_outstanding_until_confirmation(self):
        from evennia_notices.services import mutate

        self.emit()
        item = self.project()[0]
        self.assertTrue(item.outstanding)
        self.assertIn("Lantern fixture", item.text)
        self.assertIn(f"+rsvp/confirm {self.event.pk}", str(item.actions))
        mutate(self.context, item.notice.public_ref, "read")
        self.assertTrue(self.project("pending")[0].outstanding)
        with self.assertRaises(ValueError):
            mutate(self.context, item.notice.public_ref, "clear")
        self.rsvp.confirm()
        self.assertEqual(self.project("pending"), [])
        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status, RSVP.Status.CONFIRMED)

    def test_ordinary_invite_from_waitlist_is_clearable_without_changing_rsvp(self):
        from evennia_notices.services import mutate

        self.rsvp.status = RSVP.Status.WAITLISTED
        self.rsvp.save(update_fields=["status", "updated_at"])
        self.rsvp.status = RSVP.Status.INVITED
        self.rsvp.save(update_fields=["status", "updated_at"])
        self.emit("invitation", self.char2)
        item = self.project()[0]
        self.assertFalse(item.outstanding)
        mutate(self.context, item.notice.public_ref, "clear")
        self.rsvp.refresh_from_db()
        self.assertEqual(self.rsvp.status, RSVP.Status.INVITED)
        self.assertEqual(self.project(), [])

    def test_sought_waitlist_offer_stays_pending_after_read(self):
        from evennia_notices.services import mutate

        self.rsvp.status = RSVP.Status.INVITED
        self.rsvp.save(update_fields=["status", "updated_at"])
        self.emit("waitlist_offer", self.char2)
        item = self.project()[0]
        self.assertTrue(item.outstanding)
        mutate(self.context, item.notice.public_ref, "read")
        self.assertEqual(len(self.project("pending")), 1)
        self.rsvp.release()
        self.assertEqual(self.project("pending"), [])

    def test_live_deadline_cancel_and_status_changes_remove_text_and_counts(self):
        for field in ("deadline", "cancel", "release"):
            with self.subTest(field=field):
                from evennia_notices.models import Notice

                Notice.objects.all().delete()
                self.rsvp.refresh_from_db()
                self.rsvp.status = RSVP.Status.LOTTERY_SELECTED
                self.rsvp.save(update_fields=["status", "updated_at"])
                self.event.is_cancelled = False
                self.event.scheduled_time = timezone.now() + timedelta(days=4)
                self.event.save()
                # Every iteration is a real new transition.
                if CalendarNotice.objects.filter(generation=self.rsvp.notice_generation).exists():
                    self.rsvp.release()
                    self.rsvp.status = RSVP.Status.LOTTERY_SELECTED
                    self.rsvp.save(update_fields=["status", "updated_at"])
                self.emit()
                self.assertEqual(len(self.project()), 1)
                if field == "deadline":
                    self.event.scheduled_time = timezone.now() + timedelta(hours=24)
                    self.event.save(update_fields=["scheduled_time"])
                elif field == "cancel":
                    self.event.is_cancelled = True
                    self.event.save(update_fields=["is_cancelled"])
                else:
                    self.rsvp.release()
                self.assertEqual(self.project(), [])

    def test_wrong_selected_character_and_account_select_never_see_character_notice(self):
        from evennia_links.notices import NoticeContext
        from evennia_notices.services import project

        self.emit()
        self.assertEqual(project(NoticeContext(self.account)), [])
        self.assertEqual(project(NoticeContext(self.account2, self.char2)), [])
        self.assertEqual(len(self.project()), 1)

    def test_backend_retry_never_falls_back_or_acknowledges(self):
        from evennia_links.notices import RouteResult

        with (
            patch.object(notices, "route_new_event", return_value=RouteResult("retry")),
            patch.object(self.char1, "msg") as message,
        ):
            row = self.emit()
        self.assertIsNone(row.delivered_at)
        message.assert_not_called()
        frozen = row.envelope
        notices.route_notice(row.pk)
        row.refresh_from_db()
        self.assertEqual(row.route_state, "inbox")
        self.assertEqual(row.envelope, frozen)

    def test_transferred_source_never_replays_when_disabled_or_registry_removed(self):
        row = self.emit()
        from evennia_notices.models import DeliveryReceipt

        self.assertEqual(row.route_state, "inbox")
        with override_settings(NOTICES_ENABLED=False, LINKS_NOTICE_SOURCES={}):
            with patch.object(self.char1, "msg") as message:
                self.assertEqual(notices.route_notice(row.pk), "duplicate")
                notices.deliver_pending(self.char1)
            message.assert_not_called()
        self.assertEqual(DeliveryReceipt.objects.filter(source="calendar").count(), 1)

    def test_unknown_legacy_inviter_is_held_in_every_backend_mode(self):
        self.rsvp.status = RSVP.Status.INVITED
        self.rsvp.save(update_fields=["status", "updated_at"])
        row = CalendarNotice.objects.create(
            rsvp=self.rsvp,
            character=self.char1,
            kind="invited",
            status="invited",
            message="Private historical account",
        )
        for enabled, registry in ((True, CALENDAR_SOURCE), (False, CALENDAR_SOURCE), (False, {})):
            with override_settings(NOTICES_ENABLED=enabled, LINKS_NOTICE_SOURCES=registry):
                self.assertEqual(notices.route_notice(row.pk), "held")
                self.assertEqual(self.project(), [])
        row.refresh_from_db()
        self.assertIsNone(row.delivered_at)
        self.event.is_cancelled = True
        self.event.save(update_fields=["is_cancelled"])
        self.assertEqual(notices.route_notice(row.pk), "invalid")
        self.assertEqual(
            CalendarNotice.objects.get(pk=row.pk).message, "Private historical account"
        )

    def test_legacy_generation_ambiguity_is_not_bound_from_current_status_alone(self):
        old = CalendarNotice.objects.create(
            rsvp=self.rsvp,
            character=self.char1,
            kind="drawn",
            status=self.rsvp.status,
            message="Old draw",
            created_at=self.rsvp.updated_at - timedelta(seconds=1),
        )
        current = CalendarNotice.objects.create(
            rsvp=self.rsvp,
            character=self.char1,
            kind="drawn",
            status=self.rsvp.status,
            message="Current draw",
        )
        self.assertEqual(notices.route_notice(old.pk), "held")
        self.assertEqual(notices.route_notice(current.pk), "inbox")
        self.assertEqual(len(self.project()), 1)
        self.rsvp.release()
        self.assertEqual(notices.route_notice(old.pk), "invalid")

    def test_legacy_current_duplicate_rows_share_one_inbox_event(self):
        for _ in range(2):
            CalendarNotice.objects.create(
                rsvp=self.rsvp,
                character=self.char1,
                kind="drawn",
                status=self.rsvp.status,
                message="Draw",
            )
        result = notices.transfer_pending(self.char1)
        self.assertEqual(result["transferred"], 1)
        self.assertEqual(result["duplicate"], 1)
        from evennia_notices.models import DeliveryReceipt

        self.assertEqual(DeliveryReceipt.objects.filter(source="calendar").count(), 1)
        self.assertEqual(len(self.project()), 1)

    def test_reminder_receipt_survives_transfer_and_repeated_sweep(self):
        self.rsvp.confirm()
        self.emit("reminder")
        self.emit("reminder")
        self.assertEqual(CalendarNotice.objects.filter(kind="reminder").count(), 1)
        self.assertEqual(len(self.project()), 1)

    def test_forged_actor_stripping_and_action_elevation_cannot_render(self):
        from dataclasses import replace

        from evennia_calendar.integrations.notices import CalendarNoticeSource

        self.rsvp.status = RSVP.Status.INVITED
        self.rsvp.save(update_fields=["status", "updated_at"])
        row = self.emit("invitation", self.char2)
        event = notices._stored(row)
        for forged in (replace(event, actors=()), replace(event, action_kind="waitlist_offer")):
            self.assertEqual(
                CalendarNoticeSource().evaluate([forged], self.context)[forged.event_id].status,
                "invalid",
            )

    def test_background_maintenance_retires_expired_character_action(self):
        from evennia_notices.models import NoticeEvent
        from evennia_notices.services import maintain

        self.emit()
        self.event.is_cancelled = True
        self.event.save(update_fields=["is_cancelled"])
        maintain()
        self.assertFalse(NoticeEvent.objects.filter(notice__source="calendar").exists())

    def test_immediate_summary_and_off_preserve_source_action_semantics(self):
        from evennia_notices.services import set_preference

        set_preference(self.context, source="calendar", mode="off")
        self.rsvp.status = RSVP.Status.INVITED
        self.rsvp.save(update_fields=["status", "updated_at"])
        row = self.emit("invitation", self.char2)
        self.assertEqual(row.route_state, "suppressed")
        self.assertEqual(self.project(), [])
        self.rsvp.release()
        self.rsvp.status = RSVP.Status.LOTTERY_SELECTED
        self.rsvp.save(update_fields=["status", "updated_at"])
        self.emit()
        self.assertTrue(self.project()[0].outstanding)

    def test_current_source_uses_no_historical_account_name_in_either_mode(self):
        self.rsvp.status = RSVP.Status.INVITED
        self.rsvp.save(update_fields=["status", "updated_at"])
        self.emit("invitation", self.char2)
        for mode in ("account", "character"):
            with override_settings(EVENNIA_COMMS_IDENTITY=mode):
                text = self.project()[0].text
                self.assertNotIn(self.account2.key, text)
                self.assertNotIn("Stored text", text)
                self.assertIn("invited", text)

    def test_transfer_rollback_keeps_source_pending_and_retries_frozen_identity(self):
        from evennia_notices.models import DeliveryReceipt

        with (
            override_settings(NOTICES_ENABLED=False),
            patch.object(notices, "is_online", return_value=False),
        ):
            row = self.emit()
        original, frozen = CalendarNotice.save, row.envelope

        def fail_ack(instance, *args, **kwargs):
            if instance.route_state == "inbox":
                raise RuntimeError("Interrupted before source acknowledgement")
            return original(instance, *args, **kwargs)

        with patch.object(CalendarNotice, "save", fail_ack):
            self.assertEqual(notices.route_notice(row.pk), "retry")
        row.refresh_from_db()
        self.assertIsNone(row.delivered_at)
        self.assertFalse(DeliveryReceipt.objects.filter(source="calendar").exists())
        self.assertEqual(row.envelope, frozen)
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        self.assertEqual(notices.route_notice(row.pk), "duplicate")
        self.assertEqual(DeliveryReceipt.objects.filter(source="calendar").count(), 1)

    @skipUnless(apps.is_installed("evennia_social"), "Optional Social is physically absent")
    def test_ignore_rechecks_compacted_constituents_without_restoring_hidden_names_or_counts(self):
        from evennia_social import ignore

        for account in (self.account, self.account2):
            account.is_superuser = False
            account.permissions.clear()
        self.rsvp.status = RSVP.Status.INVITED
        self.rsvp.save(update_fields=["status", "updated_at"])
        with override_settings(NOTICES_ROUTINE_LIMIT=1):
            self.emit("invitation", self.char2)
            visible = CalendarEvent.objects.create(
                title="Visible invitation", scheduled_time=timezone.now() + timedelta(days=4)
            )
            other = RSVP.objects.create(
                event=visible, character=self.char1, status=RSVP.Status.INVITED
            )
            notices.notify(other, "invited", "Safe", origin="invitation", actor=self.char1)
            self.assertEqual(len(self.project()), 1)
            ignore.set_entry(self.account, self.char2, ignore.HIDDEN)
            items = self.project()
            self.assertEqual(len(items), 1)
            self.assertIn("Visible invitation", items[0].text)
            self.assertNotIn("Lantern fixture", items[0].text)
            self.assertNotIn("2 Calendar", items[0].text)
            ignore.clear(self.account)
            self.assertNotIn("Lantern fixture", self.project()[0].text)

    def test_prepare_never_transfers_another_selected_character(self):
        from evennia_calendar.integrations.notices import CalendarNoticeSource

        first = CalendarNotice.objects.create(
            rsvp=self.rsvp,
            character=self.char1,
            kind="drawn",
            status=self.rsvp.status,
            message="First",
        )
        other_rsvp = RSVP.objects.create(
            event=self.event, character=self.char2, status=RSVP.Status.LOTTERY_SELECTED
        )
        second = CalendarNotice.objects.create(
            rsvp=other_rsvp,
            character=self.char2,
            kind="drawn",
            status=other_rsvp.status,
            message="Other",
        )
        CalendarNoticeSource().prepare(self.context)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.route_state, "inbox")
        self.assertIsNone(second.delivered_at)
        self.assertEqual(second.envelope, {})

    def test_new_must_act_hints_once_but_backlog_imports_never_emit_old_bodies(self):
        from evennia_notices.models import DeliveryReceipt

        with patch("evennia_notices.services._immediate") as hint:
            with self.captureOnCommitCallbacks(execute=True):
                self.emit()
            self.assertEqual(hint.call_count, 1)
            self.emit()
            self.assertEqual(hint.call_count, 1)
        self.rsvp.release()
        self.rsvp.status = RSVP.Status.LOTTERY_SELECTED
        self.rsvp.save(update_fields=["status", "updated_at"])
        legacy = CalendarNotice.objects.create(
            rsvp=self.rsvp,
            character=self.char1,
            kind="drawn",
            status=self.rsvp.status,
            message="Old queued draw",
        )
        other_event = CalendarEvent.objects.create(
            title="Queued after backend failure", scheduled_time=timezone.now() + timedelta(days=4)
        )
        queued_rsvp = RSVP.objects.create(
            event=other_event, character=self.char1, status=RSVP.Status.LOTTERY_SELECTED
        )
        with (
            override_settings(NOTICES_ENABLED=False),
            patch.object(notices, "is_online", return_value=False),
        ):
            notices.notify(queued_rsvp, "drawn", "Queued new event", origin="lottery")
        with (
            patch("evennia_notices.services._immediate") as hint,
            self.captureOnCommitCallbacks(execute=True),
        ):
            notices.transfer_pending(self.char1)
        hint.assert_not_called()
        self.assertEqual(CalendarNotice.objects.get(pk=legacy.pk).route_state, "inbox")
        imported = DeliveryReceipt.objects.filter(source="calendar").exclude(transfer_id=None)
        self.assertEqual(imported.count(), 2)
        self.assertTrue(all(receipt.stored_event.hint_attempted_at is None for receipt in imported))

    def test_reassigning_rsvp_event_cannot_retarget_an_old_alert(self):
        self.emit()
        other = CalendarEvent.objects.create(
            title="Different subject", scheduled_time=timezone.now() + timedelta(days=4)
        )
        self.rsvp.event = other
        self.rsvp.save(update_fields=["event", "updated_at"])
        self.assertEqual(self.project(), [])
