# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Unavailable sources are absent from every preference surface and refused like unknown ones."""

from importlib import import_module
from typing import ClassVar
from unittest.mock import patch

from django.conf import settings
from django.test import RequestFactory, override_settings
from django.urls import include, path
from django.utils import timezone
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from evennia.web.urls import urlpatterns as evennia_patterns

from evennia_links.notices import NoticeContext, NoticeEvent
from evennia_notices import views
from evennia_notices.commands import CmdNotices
from evennia_notices.models import SourcePreference
from evennia_notices.services import route, set_preference

from .test_services import Source

urlpatterns = [path("notices/", include("evennia_notices.urls")), *evennia_patterns]


class GatedSource(Source):
    """Preferences are offered only while the class switch is on."""

    label = "Gated examples"
    open = False
    calls: ClassVar[list] = []

    def available(self, context):
        type(self).calls.append(context)
        return type(self).open


class RaisingGate(Source):
    label = "Broken examples"

    def available(self, context):
        raise RuntimeError("private detail")


SOURCES = {
    "test": "evennia_notices.tests.test_services.Source",
    "gated": "evennia_notices.tests.test_availability.GatedSource",
    "broken": "evennia_notices.tests.test_availability.RaisingGate",
}
UNKNOWN = "Unknown source or preference"


class GateMixin:
    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        GatedSource.open = False
        GatedSource.calls = []
        self.addCleanup(setattr, GatedSource, "open", False)

    def demote(self):
        """Drop the default test staff permissions so the account is a plain player."""
        for target in (self.account, self.char1):
            target.permissions.remove("Developer")
            target.permissions.add("Player")


@override_settings(LINKS_NOTICE_SOURCES=SOURCES)
class CommandAvailabilityTests(GateMixin, EvenniaCommandTest):
    """+notices/settings and +notices/set treat a hidden source as absent."""

    def settings_output(self):
        with self.assertLogs("evennia", "WARNING"):
            return self.call(CmdNotices(), "/settings")

    def assert_hidden(self, output):
        self.assertIn("test: summary; decisions: immediate", output)
        self.assertNotIn("gated", output)
        self.assertNotIn("Gated", output)
        self.assertNotIn("broken", output)

    def test_settings_omits_hidden_sources_for_staff_and_players(self):
        self.assert_hidden(self.settings_output())
        self.demote()
        self.assert_hidden(self.settings_output())
        GatedSource.open = True
        output = self.settings_output()
        self.assertIn("test: summary; decisions: immediate", output)
        self.assertIn("gated: summary; decisions: immediate", output)
        self.assertNotIn("broken", output)

    def test_set_refusal_matches_unknown_source(self):
        unknown = self.call(CmdNotices(), "/set nosuch=off")
        self.assertEqual(unknown, UNKNOWN)
        self.assertEqual(self.call(CmdNotices(), "/set gated=off"), unknown)
        with self.assertLogs("evennia", "WARNING"):
            self.assertEqual(self.call(CmdNotices(), "/set broken=off"), unknown)
        self.assertFalse(SourcePreference.objects.exists())
        GatedSource.open = True
        self.assertEqual(self.call(CmdNotices(), "/set gated=off"), "Notice preference saved.")

    def test_stored_choice_survives_hiding_and_applies_after_reveal(self):
        GatedSource.open = True
        self.assertEqual(self.call(CmdNotices(), "/set gated=off"), "Notice preference saved.")
        stored = SourcePreference.objects.get(source="gated")
        GatedSource.open = False
        self.assert_hidden(self.settings_output())
        self.assertEqual(self.call(CmdNotices(), "/set gated=summary"), UNKNOWN)
        row = SourcePreference.objects.get(source="gated")
        self.assertEqual((row.pk, row.mode), (stored.pk, "off"))
        GatedSource.open = True
        self.assertIn("gated: off; decisions: summary", self.settings_output())
        result = route(
            self.account,
            source="gated",
            event=NoticeEvent("after-reveal", timezone.now()),
            context=NoticeContext(self.account, self.char1),
        )
        self.assertEqual(result.status, "suppressed")

    def test_hook_receives_the_command_context(self):
        self.settings_output()
        self.assertTrue(GatedSource.calls)
        for context in GatedSource.calls:
            self.assertEqual((context.account, context.character), (self.account, self.char1))

    def test_unauthorized_context_is_rejected_before_any_hook_runs(self):
        GatedSource.open = True
        self.account.characters.remove(self.char2)
        with self.assertRaisesMessage(ValueError, "Invalid notice context"):
            set_preference(NoticeContext(self.account, self.char2), "gated", "off")
        self.assertEqual(GatedSource.calls, [])
        self.assertFalse(SourcePreference.objects.exists())


@override_settings(ROOT_URLCONF=__name__, LINKS_NOTICE_SOURCES=SOURCES)
class WebAvailabilityTests(GateMixin, EvenniaTest):
    """The rendered preferences page neither lists nor accepts a hidden source."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def request(self, method="get", data=None, account=None, character=None):
        request = getattr(self.factory, method)("/notices/preferences/", data or {})
        request.user = account or self.account
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        if character:
            request.session["puppet"] = character.pk
        return request

    def page(self, request):
        with self.assertLogs("evennia", "WARNING"):
            return views.preferences(request).render()

    def assert_hidden(self, response):
        self.assertContains(response, 'value="test"')
        self.assertContains(response, "Test source")
        self.assertNotContains(response, 'value="gated"')
        self.assertNotContains(response, "Gated examples")
        self.assertNotContains(response, 'value="broken"')
        self.assertNotContains(response, "Broken examples")

    def test_get_omits_hidden_sources_for_staff_and_players(self):
        self.assert_hidden(self.page(self.request()))
        self.assert_hidden(self.page(self.request(account=self.account2)))
        GatedSource.open = True
        response = self.page(self.request())
        self.assertContains(response, 'value="gated"')
        self.assertContains(response, "Gated examples")
        self.assertContains(response, 'value="test"')

    def test_get_passes_the_web_context_to_the_hook(self):
        self.page(self.request(character=self.char1))
        self.assertTrue(GatedSource.calls)
        for context in GatedSource.calls:
            self.assertEqual((context.account, context.character), (self.account, self.char1))

    def test_post_of_hidden_source_is_refused_like_an_unknown_one(self):
        with self.assertLogs("evennia", "WARNING"):
            hidden = views.preferences(self.request("post", {"source": "gated", "mode": "off"}))
            unknown = views.preferences(self.request("post", {"source": "nosuch", "mode": "off"}))
        self.assertEqual((hidden.status_code, unknown.status_code), (200, 200))
        hidden.render()
        unknown.render()
        self.assertContains(hidden, "Select a valid choice")
        self.assertContains(unknown, "Select a valid choice")
        self.assertNotContains(hidden, '<option value="gated"')
        self.assertFalse(SourcePreference.objects.exists())
        GatedSource.open = True
        with self.assertLogs("evennia", "WARNING"):
            response = views.preferences(self.request("post", {"source": "gated", "mode": "off"}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SourcePreference.objects.get(source="gated").mode, "off")

    def test_source_hidden_between_validation_and_saving_is_refused(self):
        with (
            patch.object(GatedSource, "available", side_effect=[True, False, False]),
            self.assertLogs("evennia", "WARNING"),
        ):
            response = views.preferences(self.request("post", {"source": "gated", "mode": "off"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response.render(), "Select a valid choice")
        self.assertFalse(SourcePreference.objects.exists())

    def test_other_save_errors_still_propagate(self):
        with (
            patch.object(views, "set_preference", side_effect=ValueError("Invalid notice context")),
            self.assertLogs("evennia", "WARNING"),
            self.assertRaisesMessage(ValueError, "Invalid notice context"),
        ):
            views.preferences(self.request("post", {"source": "test", "mode": "off"}))

    def test_raising_hook_keeps_the_page_and_other_rows(self):
        with self.assertLogs("evennia", "WARNING") as logs:
            response = views.preferences(self.request()).render()
        self.assertEqual(response.status_code, 200)
        self.assert_hidden(response)
        for line in logs.output:
            self.assertNotIn("private detail", line)
            self.assertNotIn("broken", line)
