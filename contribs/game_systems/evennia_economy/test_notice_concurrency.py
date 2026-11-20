# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Concurrent payment and notice work under separate file-backed SQLite connections."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.db import connections, transaction
from django.db.backends.sqlite3.base import DatabaseWrapper
from django.test import override_settings

from . import batch, notices
from .models import EconomyNoticeReceipt, StipendPayment
from .services import balance
from .summary import notify_economy_summary
from .test_notices import SOURCES, EconomyNoticeFixture, State


@override_settings(LINKS_NOTICE_SOURCES=SOURCES, NOTICES_ENABLED=False)
class EconomyNoticeConcurrencyTests(EconomyNoticeFixture):
    def setUp(self):
        original = connections["default"]
        if original.vendor != "sqlite":
            self.skipTest("SQLite writer reservation")
        original.ensure_connection()
        config = original.settings_dict.copy()
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.addCleanup(self.restore_db, original, config)
        db_path = Path(scratch.name) / "economy-writers.sqlite3"
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

    def show(self):
        return notify_economy_summary(self.character)

    def test_two_puppets_claim_the_line_only_once(self):
        self.pay("one-week")
        started, release = Event(), Event()

        def writer(*_args, **_kwargs):
            started.set()
            if not release.wait(15):
                raise AssertionError("Second puppet did not return")

        self.character.msg.side_effect = writer
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.worker, self.show)
            try:
                self.assertTrue(started.wait(10))
                self.assertEqual(
                    set(EconomyNoticeReceipt.objects.values_list("state", flat=True)),
                    {State.ATTEMPTING},
                )
                self.assertFalse(pool.submit(self.worker, self.show).result(10))
            finally:
                release.set()
            self.assertTrue(first.result(15))
        self.character.msg.assert_called_once()

    def test_stipend_and_puppet_race_pays_and_stages_once(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [
                pool.submit(self.worker, lambda: batch.ensure_stipends(self.character)),
                pool.submit(self.worker, lambda: batch.ensure_stipends(self.character)),
                pool.submit(self.worker, self.show),
            ]
            results = [job.result(15) for job in jobs]
        self.assertIn({"starting": 100}, results[:2])
        self.assertEqual(StipendPayment.objects.filter(character=self.character).count(), 1)
        self.assertEqual(EconomyNoticeReceipt.objects.count(), 1)
        self.assertEqual(balance(self.character), 100)
        self.show()
        self.assertEqual(EconomyNoticeReceipt.objects.get().state, State.DELIVERED)
        self.character.msg.assert_called_once()

    @skipUnless(apps.is_installed("evennia_notices"), "Inbox physically absent")
    @override_settings(NOTICES_ENABLED=True)
    def test_preparation_waits_for_payment_and_uses_one_inbox_receipt_each(self):
        from evennia_links.notices import NoticeContext
        from evennia_notices.models import DeliveryReceipt
        from evennia_notices.services import project

        staged, preparing = Event(), Event()
        context = NoticeContext(self.account, self.character, self.session)
        prepare = notices._prepare

        def pay():
            with transaction.atomic():
                self.pay("one-week")
                staged.set()
                self.assertTrue(preparing.wait(10))

        def signal_prepare(*args):
            preparing.set()
            return prepare(*args)

        with (
            ThreadPoolExecutor(max_workers=2) as pool,
            patch.object(notices, "_prepare", side_effect=signal_prepare),
        ):
            producer = pool.submit(self.worker, pay)
            try:
                self.assertTrue(staged.wait(10))
                puppet = pool.submit(
                    self.worker,
                    lambda: notices.prepare_character(self.character, context=context),
                )
                puppet.result(15)
            finally:
                preparing.set()
            producer.result(15)
        self.assertEqual(balance(self.character), 200)
        self.assertEqual(DeliveryReceipt.objects.filter(source="economy").count(), 2)
        self.assertEqual(
            set(EconomyNoticeReceipt.objects.values_list("state", flat=True)), {State.TRANSFERRED}
        )
        self.assertEqual(len(project(context, source="economy")), 2)
