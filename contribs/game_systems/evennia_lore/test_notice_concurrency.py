# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real overlapping source writers serialize against a physical SQLite database."""

import secrets
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import skipUnless

from django.apps import apps
from django.db import connections
from django.test import TransactionTestCase, override_settings
from evennia.utils.create import create_account, create_object

from evennia_lore import notices
from evennia_lore.models import LoreEntry, LoreNotice


@skipUnless(apps.is_installed("evennia_notices"), "Optional Inbox is physically absent")
@override_settings(
    NOTICES_ENABLED=True,
    LINKS_NOTICE_SOURCES={"lore": "evennia_lore.integrations.notices.LoreNoticeSource"},
)
class LoreWriterTests(TransactionTestCase):
    """The source event and inbox receipt are atomic under simultaneous sessions."""

    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.original_connection = connections["default"]
        self.original_connection.ensure_connection()
        path = Path(self.temp.name) / "lore-writers.sqlite3"
        with sqlite3.connect(path) as target:
            target.executescript("\n".join(self.original_connection.connection.iterdump()))
        self.original_config = connections.databases["default"].copy()
        config = {**self.original_config, "NAME": str(path), "OPTIONS": {"timeout": 10}}
        connections.databases["default"] = config
        from django.db.backends.sqlite3.base import DatabaseWrapper

        connections["default"] = DatabaseWrapper(config, "default")
        account = create_account("Lore writer fixture", None, secrets.token_urlsafe(48))
        character = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Lore writer", nohome=True
        )
        account.characters.add(character)
        self.entry = LoreEntry.create_entry("Concurrent Lore", author=character, body="Content")

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

    def test_concurrent_same_decision_creates_one_event(self):
        from evennia_notices.models import DeliveryReceipt

        self.parallel(lambda: LoreEntry.objects.get(pk=self.entry.pk).affirm())
        self.assertEqual(LoreNotice.objects.count(), 1)
        self.assertEqual(DeliveryReceipt.objects.filter(source="lore").count(), 1)
        self.assertEqual(LoreNotice.objects.get().route_state, "inbox")

    def test_concurrent_import_has_one_receipt(self):
        from unittest.mock import patch

        from evennia_notices.models import DeliveryReceipt

        with patch.object(notices, "_safe_route", return_value="retry"):
            self.entry.affirm()
        row = LoreNotice.objects.get()
        self.parallel(lambda: notices.route_notice(row.pk))
        self.assertEqual(DeliveryReceipt.objects.filter(source="lore").count(), 1)
