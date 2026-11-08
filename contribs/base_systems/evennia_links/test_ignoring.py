# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Tests for Links' optional ignore presentation and policy signals."""

from unittest.mock import patch

from django.dispatch import Signal
from django.test import SimpleTestCase

from evennia_links import ignoring


class TestIgnorePresentation(SimpleTestCase):
    def setUp(self):
        self.signal = Signal()
        self.swap = patch.object(ignoring, "ignore_mode_requested", self.signal)
        self.swap.start()
        self.addCleanup(self.swap.stop)

    def test_no_provider_returns_none(self):
        self.assertIsNone(ignoring.ignore_mode("reader", "author", "boards"))

    def test_each_legal_result_is_supported(self):
        for result in (None, "placeholder", "hide"):
            with self.subTest(result=result):
                self.signal.receivers.clear()
                self.signal.connect(lambda result=result, **kwargs: result, weak=False)
                self.assertEqual(ignoring.ignore_mode("reader", "author", "boards"), result)

    def test_hide_dominates_placeholder(self):
        self.signal.connect(lambda **kwargs: "placeholder", weak=False)
        self.signal.connect(lambda **kwargs: "hide", weak=False)
        self.assertEqual(ignoring.ignore_mode("reader", "author", "boards"), "hide")

    def test_any_provider_error_fails_open_even_with_hide(self):
        self.signal.connect(lambda **kwargs: "hide", weak=False)

        def fail(**kwargs):
            raise ValueError("provider unavailable")

        self.signal.connect(fail, weak=False)
        with self.assertLogs("evennia", level="ERROR") as captured:
            self.assertIsNone(ignoring.ignore_mode("reader", "author", "boards"))
        self.assertEqual(len(captured.records), 1)
        self.assertIn("Ignore presentation provider failed", captured.output[0])

    def test_invalid_provider_result_fails_open_and_logs_once(self):
        self.signal.connect(lambda **kwargs: "hide", weak=False)
        self.signal.connect(lambda **kwargs: False, weak=False)
        with self.assertLogs("evennia", level="ERROR") as captured:
            self.assertIsNone(ignoring.ignore_mode("reader", "author", "boards"))
        self.assertEqual(len(captured.records), 1)
        self.assertIn("invalid mode", captured.output[0])

    def test_provider_receives_viewer_sender_and_kind(self):
        received = {}

        def provider(**kwargs):
            received.update(kwargs)
            return None

        self.signal.connect(provider, weak=False)
        ignoring.ignore_mode("reader", "author", "boards")
        self.assertEqual(received["viewer"], "reader")
        self.assertEqual(received["sender_object"], "author")
        self.assertEqual(received["kind"], "boards")


class TestIgnorePolicyChanging(SimpleTestCase):
    def setUp(self):
        self.signal = Signal()
        self.swap = patch.object(ignoring, "ignore_policy_changing", self.signal)
        self.swap.start()
        self.addCleanup(self.swap.stop)

    def test_no_provider_is_a_noop(self):
        self.assertEqual(ignoring.notify_ignore_policy_changing("account", "boards"), [])

    def test_receiver_gets_account_and_kind(self):
        received = {}
        self.signal.connect(lambda **kwargs: received.update(kwargs), weak=False)
        ignoring.notify_ignore_policy_changing("account", "boards")
        self.assertEqual(received["viewer"], "account")
        self.assertEqual(received["kind"], "boards")

    def test_receiver_failure_propagates_for_transaction_rollback(self):
        def fail(**kwargs):
            raise RuntimeError("cannot snapshot old policy")

        self.signal.connect(fail, weak=False)
        with self.assertRaisesMessage(RuntimeError, "cannot snapshot old policy"):
            ignoring.notify_ignore_policy_changing("account", None)
