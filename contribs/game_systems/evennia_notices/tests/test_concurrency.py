# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""File-backed SQLite writer tests run serially inside this suite."""

import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.db import connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from evennia.accounts.models import AccountDB

from evennia_links.notices import NoticeContext, NoticeEvent
from evennia_notices.models import DeliveryReceipt, Notice, Recipient
from evennia_notices.models import NoticeEvent as Stored
from evennia_notices.services import _compact_locked, _recipient, mutate, route

from .test_services import SOURCES


@override_settings(LINKS_NOTICE_SOURCES=SOURCES)
class WriterTests(TransactionTestCase):
    """Use a physical isolated DB, not in-memory SQLite's shared-cache lock rules."""

    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "writers.sqlite3"
        original = self.original_connection = connections["default"]
        original.ensure_connection()
        import sqlite3

        target = sqlite3.connect(self.path)
        target.executescript("\n".join(original.connection.iterdump()))
        target.close()
        self.original_config = connections.databases["default"].copy()
        self.file_config = {**self.original_config, "NAME": str(self.path)}
        self.file_config["OPTIONS"] = {"timeout": 10}
        connections.databases["default"] = self.file_config
        from django.db.backends.sqlite3.base import DatabaseWrapper

        connections["default"] = DatabaseWrapper(self.file_config, "default")
        self.account = AccountDB.objects.create(username="notice-writer", email="")
        Recipient.objects.create(account=self.account)
        self.now = timezone.now()

    def tearDown(self):
        connections.close_all()
        connections.databases["default"] = self.original_config
        connections["default"] = self.original_connection
        self.temp.cleanup()
        super().tearDown()

    def parallel(self, operations):
        def worker(operation):
            connections.close_all()
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, operations))

    def emit(self, key):
        return route(
            self.account,
            source="test",
            event=NoticeEvent(key, self.now, replacement_key="slot"),
            context=NoticeContext(self.account),
        )

    def test_same_id_has_one_receipt_and_hint_claim(self):
        results = self.parallel([lambda: self.emit("same"), lambda: self.emit("same")])
        self.assertEqual(sorted(r.status for r in results), ["duplicate", "retained"])
        self.assertEqual(DeliveryReceipt.objects.count(), 1)
        self.assertEqual(Stored.objects.count(), 1)

    def test_same_slot_distinct_events_serialize_on_sqlite(self):
        results = self.parallel([lambda: self.emit("first"), lambda: self.emit("second")])
        self.assertEqual([r.status for r in results], ["retained", "retained"])
        self.assertEqual(DeliveryReceipt.objects.count(), 2)
        self.assertEqual(Notice.objects.filter(retired_at__isnull=True).count(), 1)
        self.assertEqual(Stored.objects.filter(inactive_reason="replaced").count(), 1)

    def test_replacement_races_read_clear_and_compaction_without_state_loss(self):
        from django.db import transaction

        for operation in ("read", "clear", "compact"):
            self.emit(f"before-{operation}")
            old = Notice.objects.get(retired_at__isnull=True)

            def change(operation=operation, old=old):
                if operation == "compact":
                    with transaction.atomic():
                        return _compact_locked(_recipient("account", self.account.pk))
                try:
                    return mutate(NoticeContext(self.account), old.public_ref, operation)
                except ValueError:
                    return None  # Replacement won: stale public action is safely unavailable.

            results = self.parallel(
                [lambda operation=operation: self.emit(f"after-{operation}"), change]
            )
            self.assertEqual(results[0].status, "retained")
            self.assertEqual(Notice.objects.filter(retired_at__isnull=True).count(), 1)
        self.assertEqual(DeliveryReceipt.objects.count(), 6)
