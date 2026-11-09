# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Routing regressions independent of an installed inbox distribution."""

from unittest.mock import Mock, patch

from django.test import override_settings
from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest

from evennia_links.notices import (
    Evaluation,
    NoticeContext,
    NoticeEvent,
    RenderedNotice,
    RouteResult,
    notify,
    source_registry,
    validate_event,
)


class ExampleSource:
    """Model-free source used to test the public seam."""

    label = "Examples"

    def evaluate(self, events, context):
        return {event.event_id: Evaluation("visible") for event in events}

    def render(self, events, context):
        return RenderedNotice("Example activity")


@override_settings(LINKS_NOTICE_SOURCES={"example": "evennia_links.test_notices.ExampleSource"})
class NoticeRoutingTests(EvenniaTest):
    """Fallback is singular and backend uncertainty never fans out."""

    def setUp(self):
        super().setUp()
        self.event = NoticeEvent("transition-1", timezone.now())

    def test_absent_backend_custom_fallback_runs_once(self):
        fallback = Mock(return_value=RouteResult("delivered"))
        with patch("evennia_links.notices.apps.is_installed", return_value=False):
            self.assertEqual(
                notify(self.account, source="example", event=self.event, fallback=fallback).status,
                "delivered",
            )
        fallback.assert_called_once()

    def test_offline_default_does_not_acknowledge(self):
        with (
            patch("evennia_links.notices.apps.is_installed", return_value=False),
            patch("evennia_links.notices.connected_contexts", return_value=[]),
        ):
            self.assertEqual(
                notify(self.account, source="example", event=self.event).status, "fallback_pending"
            )

    def test_default_fallback_only_messages_eligible_session(self):
        session = Mock()
        session.get_account.return_value = self.account
        session.get_puppet.return_value = None
        context = NoticeContext(self.account, session=session)
        with patch("evennia_links.notices.apps.is_installed", return_value=False):
            result = notify(self.account, source="example", event=self.event, context=context)
        self.assertEqual(result.status, "delivered")
        session.msg.assert_called_once_with("Example activity")

    def test_malformed_input_cannot_call_fallback(self):
        fallback = Mock()
        with self.assertRaises(ValueError):
            notify(
                self.account,
                source="example",
                event=NoticeEvent("bad", timezone.now(), payload={"bad": object()}),
                fallback=fallback,
            )
        fallback.assert_not_called()
        with self.assertRaises(ValueError):
            validate_event(NoticeEvent("bad", timezone.now(), action_kind="invitation"))

    def test_registry_follows_settings_override(self):
        self.assertIn("example", source_registry())
        with override_settings(LINKS_NOTICE_SOURCES={}):
            self.assertEqual(source_registry(), {})
        self.assertIn("example", source_registry())

    def test_wrong_character_context_is_not_inferred(self):
        self.account.characters.remove(self.char2)
        with self.assertRaises(ValueError):
            notify(
                self.account,
                source="example",
                event=self.event,
                context=NoticeContext(self.account, self.char2),
            )
