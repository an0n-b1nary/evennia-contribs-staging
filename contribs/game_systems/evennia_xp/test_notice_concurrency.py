# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Separate file-backed SQLite connections exercise first writes and claims."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch

from django.db import connections, transaction
from django.db.backends.sqlite3.base import DatabaseWrapper
from django.test import TransactionTestCase, override_settings

from . import notices
from .models import CharacterXP, XPLog, XPNoticeReceipt
from .test_notice_inbox import HAS_INBOX, REGISTRY
from .test_notice_standalone import NoticeFixture


@override_settings(LINKS_NOTICE_SOURCES=REGISTRY, NOTICES_ENABLED=False)
class NoticeConcurrencyTests(NoticeFixture, TransactionTestCase):
    def setUp(self):
        original = connections["default"]
        if original.vendor != "sqlite":
            self.skipTest("SQLite writer reservation")
        original.ensure_connection()
        config = original.settings_dict.copy()
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.addCleanup(self.restore_db, original, config)
        db_path = Path(scratch.name) / "xp-writers.sqlite3"
        with sqlite3.connect(db_path) as db:
            original.connection.backup(db)
        current = {**config, "NAME": str(db_path), "OPTIONS": {"timeout": 10}}
        connections.databases["default"] = current
        connections["default"] = DatabaseWrapper(current, "default")
        super().setUp()

    def tearDown(self):
        self.doCleanups()
        super().tearDown()

    @staticmethod
    def restore_db(original, config):
        connections.close_all()
        connections.databases["default"] = config
        connections["default"] = original

    @staticmethod
    def worker(operation):
        try:
            return operation()
        finally:
            connections.close_all()

    def test_distinct_first_awards_share_aggregate_and_week_receipt(self):
        start = Barrier(2, timeout=10)

        def pay(ref):
            with transaction.atomic():
                start.wait()
                return self.award(ref)

        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(self.worker, lambda ref=ref: pay(ref)) for ref in (1, 2)]
            self.assertTrue(all(task.result(timeout=15) is not None for task in tasks))
        self.assertIsNone(self.award(1))
        self.assertEqual(XPLog.objects.count(), 2)
        self.assertEqual(CharacterXP.objects.get().current_balance, 2.50)
        self.assertEqual(XPNoticeReceipt.objects.count(), 1)
        self.assertTrue(self.show())
        self.assertIn("2.50 XP total", self.character.msg.call_args.args[0])

    def test_concurrent_puppet_does_not_repeat_an_inflight_send(self):
        self.award()
        started, release = Event(), Event()

        def writer(*_args, **_kwargs):
            started.set()
            if not release.wait(timeout=15):
                raise AssertionError("Other puppet did not return")

        self.character.msg.side_effect = writer
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.worker, self.show)
            try:
                self.assertTrue(started.wait(timeout=10))
                self.assertEqual(XPNoticeReceipt.objects.get().state, notices.State.ATTEMPTING)
                self.assertFalse(pool.submit(self.worker, self.show).result(timeout=10))
            finally:
                release.set()
            self.assertTrue(first.result(timeout=15))
        self.character.msg.assert_called_once()

    @skipUnless(HAS_INBOX, "Inbox physically absent")
    @override_settings(NOTICES_ENABLED=True)
    def test_concurrent_arrival_and_puppet_share_one_inbox_store(self):
        from evennia_links.notices import NoticeContext
        from evennia_notices.models import DeliveryReceipt
        from evennia_notices.services import project

        with patch.object(notices, "_safe_route"):
            self.award()
            self.award(2)
        row = XPNoticeReceipt.objects.get()
        context = NoticeContext(self.account, self.character, self.sessions[0])
        start = Barrier(2, timeout=10)

        def run(fresh):
            start.wait()
            if fresh:
                notices._safe_route(self.character, row.pk, fresh=True)
            else:
                notices.prepare_character(self.character, context=context)

        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [
                pool.submit(self.worker, lambda fresh=fresh: run(fresh)) for fresh in (True, False)
            ]
            for task in tasks:
                task.result(timeout=15)
        self.assertEqual(DeliveryReceipt.objects.filter(source="xp").count(), 1)
        self.assertEqual(XPNoticeReceipt.objects.get().state, notices.State.TRANSFERRED)
        [item] = project(context, source="xp")
        self.assertIn("2.50 XP total", item.text)
