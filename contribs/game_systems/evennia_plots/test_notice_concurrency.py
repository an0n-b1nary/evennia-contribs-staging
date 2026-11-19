# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Use independent SQLite connections to exercise Plots writer and route ordering."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from unittest.mock import patch

from django.db import connections, transaction
from django.db.backends.sqlite3.base import DatabaseWrapper
from django.db.models.query import QuerySet
from django.test import TransactionTestCase, override_settings
from evennia.utils.create import create_account, create_object

from evennia_links.notices import NoticeContext
from evennia_plots import notices, signals, threads
from evennia_plots.models import PlotNoticeReceipt, PlotThread, StoryThread
from evennia_plots.test_notice_adapter import HAS_INBOX, REGISTRY, SESSION_LIST, connected

State = PlotNoticeReceipt.State
Kind = PlotNoticeReceipt.Kind


@override_settings(LINKS_NOTICE_SOURCES=REGISTRY, NOTICES_ENABLED=False)
class PlotNoticeConcurrencyTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        original = connections["default"]
        if original.vendor != "sqlite":
            self.skipTest("Physical independent SQLite writer contention")
        original.ensure_connection()
        original_config = original.settings_dict.copy()
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.addCleanup(self._restore, original, original_config)
        db_path = Path(scratch.name) / "plot-writers.sqlite3"
        with sqlite3.connect(db_path) as db:
            original.connection.backup(db)
        config = {**original_config, "NAME": str(db_path), "OPTIONS": {"timeout": 10}}
        connections.databases["default"] = config
        connections["default"] = DatabaseWrapper(config, "default")
        self.account = create_account("Plot race owner", "", "twenty-giant-falcons-83")
        self.requester_account = create_account(
            "Plot race requester", "", "twenty-giant-falcons-83"
        )
        self.owner = create_object("evennia.DefaultCharacter", key="Race owner", nohome=True)
        self.requester = create_object(
            "evennia.DefaultCharacter", key="Race requester", nohome=True
        )
        self.account.characters.add(self.owner)
        self.requester_account.characters.add(self.requester)

    def tearDown(self):
        self.doCleanups()
        super().tearDown()

    def _restore(self, original, config):
        connections.close_all()
        connections.databases["default"] = config
        connections["default"] = original

    def plot(self):
        plot = PlotThread.create_thread(
            "Plot race", self.owner, thread_policy=PlotThread.ThreadPolicy.REQUEST
        )
        plot.activate()
        return plot

    def request(self, plot):
        return threads.add_thread(plot, self.requester, "Pending race request")

    def overlap(self, winner, later):
        entered = Event()

        def observe(execute, sql, params, many, context):
            if sql.startswith('UPDATE "evennia_plots_plotthread"'):
                entered.set()
            return execute(sql, params, many, context)

        def worker():
            try:
                with connections["default"].execute_wrapper(observe):
                    return later()
            except threads.ThreadError as exc:
                return exc
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                prior = winner()
                future = pool.submit(worker)
                self.assertTrue(entered.wait(timeout=5), "Second writer did not reach plot guard")
            return prior, future.result(timeout=10)

    def test_accept_and_decline_race_records_exactly_one_original_decision(self):
        for accept_first in (True, False):
            with self.subTest(accept_first=accept_first):
                request = self.request(self.plot())
                first = threads.accept if accept_first else threads.decline
                later = threads.decline if accept_first else threads.accept
                _, loser = self.overlap(
                    lambda first=first, request=request: first(request, self.owner),
                    lambda later=later, request=request: later(
                        StoryThread.objects.get(pk=request.pk), self.owner
                    ),
                )
                self.assertIsInstance(loser, threads.ThreadError)
                row = PlotNoticeReceipt.objects.get(
                    thread=request, kind__in=(Kind.ACCEPT, Kind.DECLINE)
                )
                self.assertEqual(row.kind, Kind.ACCEPT if accept_first else Kind.DECLINE)
                self.assertEqual(row.actor_id, self.owner.pk)
                self.assertEqual(row.character_id, self.requester.pk)

    def test_archive_serializes_against_accept_request_and_withdraw(self):
        for action in ("accept", "request", "withdraw"):
            for archives_first in (True, False):
                with self.subTest(action=action, archives_first=archives_first):
                    plot = self.plot()
                    request = None if action == "request" else self.request(plot)

                    def close(plot=plot):
                        PlotThread.objects.get(pk=plot.pk).archive()

                    def act(plot=plot, request=request, action=action):
                        if action == "request":
                            return self.request(plot)
                        current = StoryThread.objects.get(pk=request.pk)
                        if action == "accept":
                            return threads.accept(current, self.owner)
                        return threads.withdraw(current, self.requester)

                    if archives_first:
                        _, loser = self.overlap(close, act)
                        self.assertIsInstance(loser, threads.ThreadError)
                        if request is not None:
                            request.refresh_from_db()
                            self.assertEqual(request.status, StoryThread.Status.DECLINED)
                            self.assertIsNone(request.decided_by_id)
                    else:
                        applied, _ = self.overlap(act, close)
                        if action == "accept":
                            request.refresh_from_db()
                            self.assertEqual(request.status, StoryThread.Status.LOOSE_END)
                            self.assertEqual(request.decided_by_id, self.owner.pk)
                            self.assertEqual(
                                PlotNoticeReceipt.objects.filter(
                                    thread=request, kind=Kind.ACCEPT
                                ).count(),
                                1,
                            )
                        elif action == "request":
                            applied.refresh_from_db()
                            self.assertEqual(applied.status, StoryThread.Status.DECLINED)
                            self.assertIsNone(applied.decided_by_id)
                        else:
                            self.assertFalse(StoryThread.objects.filter(pk=request.pk).exists())
                    plot.refresh_from_db()
                    self.assertEqual(plot.status, PlotThread.Status.ARCHIVED)
                    self.assertFalse(
                        plot.story_threads.filter(
                            status__in=(StoryThread.Status.REQUESTED, StoryThread.Status.OPEN)
                        ).exists()
                    )

    def test_direct_close_uses_same_guard_and_archive_rolls_back_both_sweeps(self):
        plot = self.plot()
        first = self.request(plot)
        result, loser = self.overlap(
            plot.close_story_threads, lambda: threads.accept(first, self.owner)
        )
        self.assertEqual(result, (0, 1))
        self.assertIsInstance(loser, threads.ThreadError)
        first.refresh_from_db()
        self.assertIsNone(first.decided_by_id)

        open_thread = threads.add_thread(plot, self.owner, "Open during archive")
        pending = self.request(plot)
        original_update = QuerySet.update

        def reject_second_sweep(query, **fields):
            if query.model == StoryThread and fields.get("status") == StoryThread.Status.DECLINED:
                raise RuntimeError("Second sweep failed")
            return original_update(query, **fields)

        with (
            patch.object(QuerySet, "update", autospec=True, side_effect=reject_second_sweep),
            patch.object(signals.plot_thread_archived, "send") as signal,
            self.assertRaisesRegex(RuntimeError, "Second sweep failed"),
        ):
            plot.archive()
        signal.assert_not_called()
        self.assertEqual(plot.status, PlotThread.Status.ACTIVE)
        self.assertIsNone(plot.archived_at)
        open_thread.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(open_thread.status, StoryThread.Status.OPEN)
        self.assertEqual(pending.status, StoryThread.Status.REQUESTED)

    def test_owner_grant_wins_once_and_request_snapshots_only_current_generation(self):
        other_account = create_account("Second race owner", "", "twenty-giant-falcons-83")
        other = create_object("evennia.DefaultCharacter", key="Second race owner", nohome=True)
        other_account.characters.add(other)
        plot = self.plot()
        owner, loser = self.overlap(
            lambda: threads.add_owner(plot, self.owner, other),
            lambda: threads.add_owner(plot, self.owner, other),
        )
        self.assertIsInstance(loser, threads.ThreadError)
        self.assertEqual(PlotNoticeReceipt.objects.filter(kind=Kind.GRANT, owner=owner).count(), 1)

        _, request = self.overlap(
            lambda: threads.remove_owner(plot, self.owner, other),
            lambda: self.request(plot),
        )
        self.assertEqual(
            list(
                PlotNoticeReceipt.objects.filter(thread=request).values_list(
                    "character_id", flat=True
                )
            ),
            [self.owner.pk],
        )
        _, later_owner = self.overlap(
            lambda: self.request(plot), lambda: threads.add_owner(plot, self.owner, other)
        )
        self.assertNotEqual(owner.pk, later_owner.pk)
        self.assertFalse(
            PlotNoticeReceipt.objects.filter(kind=Kind.REQUEST, owner=later_owner).exists()
        )

    def test_concurrent_puppet_does_not_repeat_an_inflight_send(self):
        plot = self.plot()
        puppet = connected(self.account, self.owner)
        started, release = Event(), Event()

        def send(_text):
            started.set()
            if not release.wait(timeout=10):
                raise AssertionError("Another puppet did not return")

        puppet.msg.side_effect = send
        with patch(SESSION_LIST, return_value=[puppet]), ThreadPoolExecutor(max_workers=2) as pool:

            def work(operation):
                try:
                    return operation()
                finally:
                    connections.close_all()

            first = pool.submit(work, lambda: self.request(plot))
            try:
                self.assertTrue(started.wait(timeout=5))
                row = PlotNoticeReceipt.objects.get()
                self.assertEqual(row.state, State.ATTEMPTING)
                second = connected(self.account, self.owner)
                pool.submit(work, lambda: notices._puppet(self.owner, session=second)).result(
                    timeout=10
                )
            finally:
                release.set()
            first.result(timeout=10)
        puppet.msg.assert_called_once()
        row.refresh_from_db()
        self.assertEqual(row.state, State.FALLBACK_DELIVERED)

    @override_settings(NOTICES_ENABLED=True)
    def test_initial_offer_and_quiet_transfer_use_the_same_claim(self):
        if not HAS_INBOX:
            self.skipTest("Inbox physically absent")
        from evennia_notices.models import DeliveryReceipt, SourcePreference

        plot = self.plot()
        context = NoticeContext(self.account, self.owner)
        with patch.object(notices, "_safe_route"):
            request = self.request(plot)
        row = PlotNoticeReceipt.objects.get(thread=request)
        SourcePreference.objects.create(account=self.account, source="plots", mode="immediate")
        puppet = connected(self.account, self.owner)
        start = Barrier(2, timeout=10)

        def run(fresh):
            try:
                start.wait()
                if fresh:
                    notices._safe_route(row, fresh=True)
                else:
                    notices.prepare(context)
            finally:
                connections.close_all()

        with patch(SESSION_LIST, return_value=[puppet]), ThreadPoolExecutor(max_workers=2) as pool:
            first, second = [pool.submit(run, fresh) for fresh in (True, False)]
            first.result(timeout=15)
            second.result(timeout=15)
        self.assertEqual(DeliveryReceipt.objects.filter(source="plots").count(), 1)
        self.assertLessEqual(puppet.msg.call_count, 1)
        row.refresh_from_db()
        self.assertEqual(row.state, State.INBOX)
