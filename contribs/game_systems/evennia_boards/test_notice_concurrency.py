# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Exercise Boards writers and socket claims against a physical SQLite database."""

import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch

from django.apps import apps
from django.db import connections, transaction
from django.db.backends.sqlite3.base import DatabaseWrapper
from django.test import TransactionTestCase, override_settings
from evennia.accounts.models import AccountDB

from evennia_boards import notices
from evennia_boards.models import Board, Post, StandaloneNoticeClaim, Subscription
from evennia_boards.notice_test_helpers import connected_session
from evennia_boards.test_notice_adapter import SOURCE


@override_settings(LINKS_NOTICE_SOURCES=SOURCE, NOTICES_ENABLED=False)
class BoardsWriterTests(TransactionTestCase):
    """Use a cloned test database to test actual commits between connections."""

    def setUp(self):
        super().setUp()
        original = connections["default"]
        original.ensure_connection()
        config = original.settings_dict.copy()
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.addCleanup(self.restore_database, original, config)
        db_path = Path(scratch.name) / "boards-writers.sqlite3"
        with sqlite3.connect(db_path) as db:
            original.connection.backup(db)
        file_config = {**config, "NAME": str(db_path), "OPTIONS": {"timeout": 10}}
        connections.databases["default"] = file_config
        connections["default"] = DatabaseWrapper(file_config, "default")
        self.account = AccountDB.objects.create(username="board-writer")
        self.board = Board.objects.create(name="Concurrent Boards")

    def tearDown(self):
        # Restore before TransactionTestCase flushes the original database.
        self.doCleanups()
        super().tearDown()

    def restore_database(self, original, config):
        """Restore the original suite connection."""
        connections.close_all()
        connections.databases["default"] = config
        connections["default"] = original

    def create_post(self):
        """Write through the shared board writer and commit callback."""
        return Post.create_post(self.board, None, "Private title", "Private prose")

    def subscribe(self):
        """Use the ordinary subscription generation allocation."""
        return Subscription.objects.create(account=self.account, board=self.board)

    def fork(self, pool, operation):
        """Run one operation in a separate database connection."""

        def worker():
            try:
                return operation()
            finally:
                connections.close_all()

        return pool.submit(worker)

    def test_subscription_fence_orders_with_both_sides_of_post_insert(self):
        for post_first in (True, False):
            with self.subTest(post_first=post_first), ThreadPoolExecutor(max_workers=1) as pool:
                entered = Event()

                def other_insert(entered=entered, post_first=post_first):
                    entered.set()
                    return self.subscribe() if post_first else self.create_post()

                previous = Post.all_objects.filter(board=self.board).order_by("pk").last()
                with transaction.atomic():
                    first = self.create_post() if post_first else self.subscribe()
                    second = self.fork(pool, other_insert)
                    self.assertTrue(entered.wait(timeout=5))
                result = second.result(timeout=10)
                post, sub = (first, result) if post_first else (result, first)
                self.assertEqual(sub.inbox_start_post_id, post.pk if post_first else previous.pk)
                sub.delete()

    @override_settings(NOTICES_ENABLED=True)
    def test_two_committed_post_callbacks_keep_the_latest_slot(self):
        if not apps.is_installed("evennia_notices"):
            self.skipTest("Inbox is physically optional")
        from evennia_notices.models import NoticeEvent

        sub = self.subscribe()
        both_committed = Barrier(2, timeout=10)
        route = notices.post_committed

        def overlap(*args):
            both_committed.wait()
            route(*args)

        with (
            patch.object(notices, "post_committed", side_effect=overlap),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first = self.fork(pool, self.create_post)
            second = self.fork(pool, self.create_post)
            latest = max(first.result(timeout=15).pk, second.result(timeout=15).pk)
        sub.refresh_from_db()
        self.assertEqual(sub.discovery_post_id, latest)
        self.assertEqual(sub.inbox_witness_post_id, latest)
        [item] = NoticeEvent.objects.filter(inactive_at__isnull=True, notice__source="boards")
        self.assertEqual(item.payload["post"], latest)

    def test_overlapping_login_does_not_repeat_a_started_claim(self):
        sub = self.subscribe()
        post = self.create_post()
        started, release = Event(), Event()

        def send(_text):
            started.set()
            if not release.wait(timeout=10):
                raise AssertionError("Concurrent login never returned")

        with connected_session(self.account) as session, ThreadPoolExecutor(max_workers=2) as pool:
            session.msg.side_effect = send
            first = self.fork(pool, lambda: notices.notify_login(self.account, session))
            try:
                self.assertTrue(started.wait(timeout=5))
                self.assertEqual(StandaloneNoticeClaim.objects.get().status, "attempting")
                second = self.fork(pool, lambda: notices.notify_login(self.account, session))
                second.result(timeout=10)
            finally:
                release.set()
            first.result(timeout=10)
            session.msg.assert_called_once()
        self.assertEqual(StandaloneNoticeClaim.objects.get().status, "delivered")
        sub.refresh_from_db()
        self.assertEqual(sub.discovery_post_id, post.pk)
