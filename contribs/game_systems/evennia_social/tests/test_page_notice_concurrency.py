# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real commits from separate SQLite connections at the page routing boundary."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import Mock, patch

from django.db import connections, transaction
from django.db.backends.sqlite3.base import DatabaseWrapper
from django.test import TransactionTestCase, override_settings
from evennia.utils.create import create_account, create_message, create_object

from evennia_links.notices import NoticeContext
from evennia_social import notices
from evennia_social.commands.messaging import CmdPage
from evennia_social.models import PageDelivery
from evennia_social.tests.base import SocialTestCharacter
from evennia_social.tests.test_page_notices import REGISTRY, SESSION_LIST


@override_settings(LINKS_NOTICE_SOURCES=REGISTRY, NOTICES_ENABLED=True)
class PageWriterTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        original = connections["default"]
        original.ensure_connection()
        config = original.settings_dict.copy()
        scratch = self.enterContext(TemporaryDirectory())
        db_path = Path(scratch) / "page-writers.sqlite3"
        with sqlite3.connect(db_path) as clone:
            original.connection.backup(clone)
        self.addCleanup(self.restore_database, original, config)
        file_config = {**config, "NAME": str(db_path), "OPTIONS": {"timeout": 10}}
        connections.databases["default"] = file_config
        connections["default"] = DatabaseWrapper(file_config, "default")
        self.account = create_account("PageWriterFixture", None, None)
        self.sender = create_object(SocialTestCharacter, key="Writer Fixture")
        self.recipient = create_object(SocialTestCharacter, key="Receiver Fixture")
        self.account.characters.add(self.recipient)
        self.session = Mock()
        self.session.get_account.return_value = self.account
        self.session.get_puppet.return_value = self.recipient

    def restore_database(self, original, config):
        connections.close_all()
        connections.databases["default"] = config
        connections["default"] = original

    def tearDown(self):
        self.doCleanups()
        super().tearDown()

    def fork(self, pool, operation):
        def worker():
            try:
                return operation()
            finally:
                connections.close_all()

        return pool.submit(worker)

    @override_settings(NOTICES_ENABLED=False)
    def test_concurrent_puppets_do_not_reclaim_started_write(self):
        page = create_message(
            self.sender,
            "Private page",
            receivers=[self.recipient],
            locks=f"read:id({self.recipient.pk})",
            tags=[("page", "comms")],
        )
        started, release = Event(), Event()

        def send(text):
            started.set()
            if not release.wait(timeout=10):
                raise RuntimeError("Other puppet did not complete")

        self.session.msg.side_effect = send
        with patch(SESSION_LIST, return_value=[self.session]), ThreadPoolExecutor(2) as pool:
            first = self.fork(pool, lambda: notices._standalone(self.recipient))
            try:
                self.assertTrue(started.wait(timeout=5))
                self.assertEqual(PageDelivery.objects.get(message=page).state, "claimed")
                second = self.fork(pool, lambda: notices._standalone(self.recipient))
                second.result(timeout=10)
            finally:
                release.set()
            first.result(timeout=10)
        self.session.msg.assert_called_once()
        self.assertEqual(PageDelivery.objects.get(message=page).state, "fallback")

    def test_source_commit_and_prepare_keep_all_recipients(self):
        from django.apps import apps

        if not apps.is_installed("evennia_notices"):
            self.skipTest("Inbox is physically optional")
        from evennia_notices.models import DeliveryReceipt

        sibling = create_object(SocialTestCharacter, key="Sibling Receiver")
        self.account.characters.add(sibling)
        command = CmdPage()
        command.caller = self.sender
        entered = Event()

        def prepare():
            entered.set()
            return notices.prepare(NoticeContext(self.account, self.recipient))

        with ThreadPoolExecutor(1) as pool:
            with transaction.atomic():
                command._send_page(self.sender, [self.recipient, sibling], "Private multi-page")
                worker = self.fork(pool, prepare)
                self.assertTrue(entered.wait(timeout=5))
            worker.result(timeout=10)
        self.assertEqual(PageDelivery.objects.filter(state="inbox").count(), 2)
        self.assertEqual(DeliveryReceipt.objects.filter(source="social-pages").count(), 2)
