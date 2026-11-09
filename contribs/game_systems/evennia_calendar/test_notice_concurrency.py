# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real overlapping source writers serialize against a physical SQLite database."""

import secrets
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless

from django.apps import apps
from django.db import connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
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
