# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Routing regressions independent of an installed inbox distribution."""

from typing import ClassVar
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
    available_sources,
    notify,
    source_available,
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


class GatedSource(ExampleSource):
    """Source whose preferences are offered only while its class switch is on."""

    open = False
    calls: ClassVar[list] = []

    def available(self, context):
        type(self).calls.append(context)
        return type(self).open


class RaisingGate(ExampleSource):
    def available(self, context):
        raise RuntimeError("private detail")


class TruthyGate(ExampleSource):
    def available(self, context):
        return "yes"


class NonCallableGate(ExampleSource):
    available = True


class NoneGate(ExampleSource):
    available = None


class RaisingLookup(ExampleSource):
    @property
    def available(self):
        raise RuntimeError("private detail")


GATED = {
    "example": "evennia_links.test_notices.ExampleSource",
    "gated": "evennia_links.test_notices.GatedSource",
    "later": "evennia_links.test_notices.ExampleSource",
}


@override_settings(LINKS_NOTICE_SOURCES=GATED)
class SourceAvailabilityTests(EvenniaTest):
    """The optional hook gates preference listing live and fails closed."""

    def setUp(self):
        super().setUp()
        GatedSource.open = False
        GatedSource.calls = []
        self.addCleanup(setattr, GatedSource, "open", False)
        self.context = NoticeContext(self.account, self.char1)

    def test_missing_hook_is_available(self):
        registry = source_registry()
        self.assertTrue(source_available(registry["example"], self.context))
        self.assertIn("example", available_sources(self.context))

    def test_gate_filters_in_registry_order_with_registry_objects(self):
        registry = source_registry()
        self.assertEqual(list(available_sources(self.context)), ["example", "later"])
        GatedSource.open = True
        sources = available_sources(self.context)
        self.assertEqual(list(sources), ["example", "gated", "later"])
        for slug, source in sources.items():
            self.assertIs(source, registry[slug])

    def test_hook_receives_the_exact_context(self):
        source_available(source_registry()["gated"], self.context)
        self.assertEqual(len(GatedSource.calls), 1)
        self.assertIs(GatedSource.calls[0], self.context)

    def test_availability_is_not_cached_with_the_registry(self):
        source_registry()
        self.assertNotIn("gated", available_sources(self.context))
        GatedSource.open = True
        self.assertIn("gated", available_sources(self.context))
        GatedSource.open = False
        self.assertNotIn("gated", available_sources(self.context))

    @override_settings(
        LINKS_NOTICE_SOURCES={
            "example": "evennia_links.test_notices.ExampleSource",
            "broken": "evennia_links.test_notices.RaisingGate",
        }
    )
    def test_raising_hook_hides_with_one_generic_warning(self):
        with self.assertLogs("evennia", "WARNING") as logs:
            self.assertEqual(list(available_sources(self.context)), ["example"])
        self.assertEqual(len(logs.output), 1)
        self.assertNotIn("private detail", logs.output[0])
        self.assertNotIn("broken", logs.output[0])

    def test_raising_hook_lookup_hides_with_one_generic_warning(self):
        with self.assertLogs("evennia", "WARNING") as logs:
            self.assertFalse(source_available(RaisingLookup(), self.context))
        self.assertEqual(len(logs.output), 1)
        self.assertNotIn("private detail", logs.output[0])

    @override_settings(
        LINKS_NOTICE_SOURCES={
            "example": "evennia_links.test_notices.ExampleSource",
            "truthy": "evennia_links.test_notices.TruthyGate",
        }
    )
    def test_only_true_admits_and_other_returns_hide_silently(self):
        with self.assertNoLogs("evennia", "WARNING"):
            self.assertEqual(list(available_sources(self.context)), ["example"])

    def test_raising_hook_lookup_is_a_registry_configuration_error(self):
        with (
            override_settings(
                LINKS_NOTICE_SOURCES={"lookup": "evennia_links.test_notices.RaisingLookup"}
            ),
            self.assertRaisesMessage(RuntimeError, "private detail"),
        ):
            source_registry()

    def test_non_callable_hook_is_rejected_and_none_means_no_hook(self):
        with (
            override_settings(
                LINKS_NOTICE_SOURCES={"bad": "evennia_links.test_notices.NonCallableGate"}
            ),
            self.assertRaisesMessage(ValueError, "availability must be callable"),
        ):
            source_registry()
        with override_settings(
            LINKS_NOTICE_SOURCES={"none": "evennia_links.test_notices.NoneGate"}
        ):
            self.assertEqual(list(available_sources(self.context)), ["none"])


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
