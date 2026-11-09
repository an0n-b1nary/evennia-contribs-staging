# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Profile fixtures import neither Inbox nor Social until their presence is known."""

from importlib import metadata
from importlib.util import find_spec
from unittest.mock import Mock

from django.apps import apps
from django.conf import settings
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
)


class FixtureSource:
    """Explicit independent source; never registered by standalone defaults."""

    label = "Profile examples"

    def evaluate(self, events, context):
        return {e.event_id: Evaluation("visible") for e in events}

    def render(self, events, context):
        return RenderedNotice("Profile example")


class NoticePartnerTests(EvenniaTest):
    """Physical absence and real routing, not app-list mocks."""

    def test_declared_partners_are_physically_absent(self):
        for name in settings.NOTICES_ABSENT_PARTNERS:
            self.assertIsNone(find_spec(name))
            self.assertFalse(apps.is_installed(name))
            with self.assertRaises(metadata.PackageNotFoundError):
                metadata.distribution(name.replace("_", "-"))

    def test_installed_or_absent_routing_uses_exactly_one_path(self):
        fallback = Mock(return_value=RouteResult("delivered"))
        event = NoticeEvent("profile-transition", timezone.now())
        result = notify(
            self.account,
            source="fixture",
            event=event,
            context=NoticeContext(self.account),
            fallback=fallback,
        )
        if apps.is_installed("evennia_notices"):
            self.assertEqual(result.status, "retained")
            fallback.assert_not_called()
            from evennia_notices.services import project

            self.assertEqual(project(NoticeContext(self.account))[0].text, "Profile example")
            with override_settings(LINKS_NOTICE_SOURCES={}, NOTICES_ENABLED=False):
                self.assertEqual(
                    notify(self.account, source="fixture", event=event, fallback=fallback).status,
                    "duplicate",
                )
            fallback.assert_not_called()
        else:
            self.assertEqual(result.status, "delivered")
            fallback.assert_called_once()

    def test_disabled_new_work_uses_fallback_and_source_receipt_prevents_replay(self):
        # Source-owned durable receipt is the contract across physical Inbox removal.
        from evennia.server.models import ServerConfig

        event = NoticeEvent("source-owned-transition", timezone.now())
        fallback = Mock(return_value=RouteResult("delivered"))

        def source_delivery():
            if ServerConfig.objects.conf("profile_source_receipt", default=False):
                return RouteResult("duplicate")
            result = notify(self.account, source="fixture", event=event, fallback=fallback)
            if result.status in {"delivered", "retained", "suppressed", "duplicate"}:
                ServerConfig.objects.conf("profile_source_receipt", True)
            return result

        with override_settings(NOTICES_ENABLED=False):
            self.assertEqual(source_delivery().status, "delivered")
        self.assertEqual(source_delivery().status, "duplicate")
        fallback.assert_called_once()
