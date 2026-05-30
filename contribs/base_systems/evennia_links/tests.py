# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_links abstract bases.

Uses throwaway concrete subclasses to exercise the abstract model APIs
without requiring the full game's domain models.
"""

from evennia.utils.test_resources import EvenniaTest

from evennia_links import (
    AbstractArchived,
    AbstractAuthoredLink,
    AbstractLink,
    AbstractVersion,
    ArchivedManager,
    connect_on_ready,
)


class TestAbstractLinkAbstractness(EvenniaTest):
    def test_abstract_link_is_abstract(self):
        self.assertTrue(AbstractLink._meta.abstract)

    def test_abstract_authored_link_is_abstract(self):
        self.assertTrue(AbstractAuthoredLink._meta.abstract)

    def test_abstract_version_is_abstract(self):
        self.assertTrue(AbstractVersion._meta.abstract)

    def test_abstract_archived_is_abstract(self):
        self.assertTrue(AbstractArchived._meta.abstract)


class TestConnectOnReady(EvenniaTest):
    def test_connect_on_ready_connects_receiver(self):
        from django.dispatch import Signal

        sig = Signal()
        calls = []

        def my_receiver(sender, **kwargs):
            calls.append(kwargs)

        connect_on_ready(sig, my_receiver)
        sig.send(sender=None, foo="bar")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["foo"], "bar")

    def test_connect_on_ready_dedupes(self):
        from django.dispatch import Signal

        sig = Signal()
        calls = []

        def my_receiver(sender, **kwargs):
            calls.append(1)

        connect_on_ready(sig, my_receiver)
        connect_on_ready(sig, my_receiver)  # second call should be ignored
        sig.send(sender=None)
        self.assertEqual(len(calls), 1)
