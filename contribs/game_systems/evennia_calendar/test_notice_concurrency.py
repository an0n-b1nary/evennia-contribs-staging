# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real overlapping source writers serialize against a physical SQLite database."""

import secrets
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.db import connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from evennia.utils.ansi import strip_ansi
from evennia.utils.create import create_account, create_object

from evennia_calendar import notices
from evennia_calendar.models import RSVP, CalendarEvent, CalendarNotice


@skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox is physically absent")
@override_settings(
    NOTICES_ENABLED=True,
    LINKS_NOTICE_SOURCES={"calendar": "evennia_calendar.integrations.notices.CalendarNoticeSource"},
)
class CalendarWriterTests(TransactionTestCase):
    """The source event and inbox receipt are atomic under simultaneous sessions."""

    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.original_connection = connections["default"]
        self.original_connection.ensure_connection()
        path = Path(self.temp.name) / "calendar-writers.sqlite3"
        with sqlite3.connect(path) as target:
            target.executescript("\n".join(self.original_connection.connection.iterdump()))
        self.original_config = connections.databases["default"].copy()
        config = {**self.original_config, "NAME": str(path), "OPTIONS": {"timeout": 10}}
        connections.databases["default"] = config
        from django.db.backends.sqlite3.base import DatabaseWrapper

        connections["default"] = DatabaseWrapper(config, "default")
        account = create_account("Calendar writer fixture", None, secrets.token_urlsafe(48))
        character = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Calendar writer", nohome=True
        )
        account.characters.add(character)
        self.account = account
        self.event = CalendarEvent.objects.create(
            title="Concurrent draw", scheduled_time=timezone.now() + timedelta(days=4)
        )
        self.rsvp = RSVP.objects.create(
            event=self.event, character=character, status=RSVP.Status.LOTTERY_SELECTED
        )

    def tearDown(self):
        connections.close_all()
        connections.databases["default"] = self.original_config
        connections["default"] = self.original_connection
        self.temp.cleanup()
        super().tearDown()

    def parallel(self, operation):
        def worker(_):
            connections.close_all()
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, range(2)))

    def test_repeated_source_signal_has_one_source_event_and_one_inbox_receipt(self):
        from evennia_notices.models import DeliveryReceipt

        def emit():
            rsvp = RSVP.objects.select_related("event").get(pk=self.rsvp.pk)
            return notices.notify(
                rsvp, "drawn", notices.drawn_message(rsvp.event), origin="lottery"
            )

        self.parallel(emit)
        self.assertEqual(CalendarNotice.objects.count(), 1)
        self.assertEqual(CalendarNotice.objects.get().route_state, "inbox")
        self.assertEqual(DeliveryReceipt.objects.filter(source="calendar").count(), 1)

    def test_repeated_legacy_transfer_has_one_receipt(self):
        from evennia_notices.models import DeliveryReceipt

        row = CalendarNotice.objects.create(
            rsvp=self.rsvp,
            character=self.rsvp.character,
            kind="drawn",
            status=self.rsvp.status,
            message="Current legacy draw",
        )
        results = self.parallel(lambda: notices.route_notice(row.pk))
        self.assertEqual(sorted(results), ["duplicate", "inbox"])
        self.assertEqual(DeliveryReceipt.objects.filter(source="calendar").count(), 1)

    def test_distinct_legacy_aliases_race_to_one_source_receipt(self):
        from evennia_notices.models import DeliveryReceipt

        rows = [
            CalendarNotice.objects.create(
                rsvp=self.rsvp,
                character=self.rsvp.character,
                kind="drawn",
                status=self.rsvp.status,
                message="Current legacy draw",
            )
            for _ in range(2)
        ]
        pending = iter([row.pk for row in rows])
        results = self.parallel(lambda: notices.route_notice(next(pending)))
        self.assertEqual(sorted(results), ["duplicate", "inbox"])
        self.assertEqual(DeliveryReceipt.objects.filter(source="calendar").count(), 1)
        rows = list(CalendarNotice.objects.order_by("pk"))
        self.assertEqual(rows[0].envelope, rows[1].envelope)
        self.assertEqual([row.route_state for row in rows], ["inbox", "inbox"])

    @override_settings(NOTICES_ENABLED=False, LINKS_NOTICE_SOURCES={})
    def test_competing_alias_route_then_concurrent_retry_sends_once(self):
        first, alias = [
            CalendarNotice.objects.create(
                rsvp=self.rsvp,
                character=self.rsvp.character,
                kind="drawn",
                status=self.rsvp.status,
                message="Current legacy draw",
            )
            for _ in range(2)
        ]
        character = self.rsvp.character
        session = SimpleNamespace(get_account=lambda: self.account, get_puppet=lambda: character)
        entered, proceed = Event(), Event()
        stored = notices._stored

        def pause_after_claim(row):
            if row.route_state == "attempting" and not proceed.is_set():
                entered.set()
                if not proceed.wait(timeout=10):
                    raise RuntimeError("Test did not release the callback")
            return stored(row)

        def first_route():
            try:
                return notices.route_notice(alias.pk)
            finally:
                connections.close_all()

        with (
            patch.object(notices, "_connected_sessions", return_value=[session]),
            patch.object(notices, "_stored", side_effect=pause_after_claim),
            patch.object(type(character), "msg") as message,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            route = pool.submit(first_route)
            try:
                self.assertTrue(entered.wait(timeout=10))
                first.refresh_from_db()
                alias.refresh_from_db()
                self.assertEqual((first.route_state, alias.route_state), ("attempting", "pending"))
                self.assertEqual(notices.route_notice(first.pk), "held")
                self.assertEqual(first.envelope, alias.envelope)
                message.assert_not_called()
                session.get_puppet = lambda: None
            finally:
                proceed.set()
            self.assertEqual(route.result(timeout=10), "held")
            first.refresh_from_db()
            self.assertEqual(
                (first.route_state, first.routed_at, first.delivered_at), ("pending", None, None)
            )
            session.get_puppet = lambda: character
            pending = iter((first.pk, alias.pk))
            outcomes = self.parallel(lambda: notices.route_notice(next(pending)))
            self.assertIn("fallback", outcomes)
            self.assertTrue(set(outcomes) <= {"fallback", "held", "duplicate"})
            message.assert_called_once_with(
                strip_ansi(notices.drawn_message(self.event)), session=session
            )

        first.refresh_from_db()
        alias.refresh_from_db()
        self.assertEqual((first.route_state, alias.route_state), ("fallback", "fallback"))
        self.assertIsNotNone(first.delivered_at)
        self.assertEqual(first.delivered_at, alias.delivered_at)
