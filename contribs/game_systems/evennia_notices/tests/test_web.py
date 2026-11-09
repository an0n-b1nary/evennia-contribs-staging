# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Rendered pages prove scope, escaping and explicit acknowledgement behavior."""

from importlib import import_module

from django.conf import settings
from django.http import Http404
from django.test import RequestFactory, override_settings
from django.urls import include, path
from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest
from evennia.web.urls import urlpatterns as evennia_patterns

from evennia_links.notices import NoticeContext, NoticeEvent
from evennia_notices import views
from evennia_notices.models import Notice
from evennia_notices.models import NoticeEvent as Stored
from evennia_notices.services import route

from .test_services import SOURCES

urlpatterns = [path("notices/", include("evennia_notices.urls")), *evennia_patterns]


@override_settings(ROOT_URLCONF=__name__, LINKS_NOTICE_SOURCES=SOURCES)
class WebTests(EvenniaTest):
    """Every page is actually rendered with populated and empty state."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.factory = RequestFactory()

    def request(self, method="get", data=None, account=None, character=None):
        request = getattr(self.factory, method)("/notices/", data or {})
        request.user = account or self.account
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        if character:
            request.session["puppet"] = character.pk
        return request

    def test_empty_list_history_preferences_render(self):
        for response in (
            views.inbox(self.request()),
            views.inbox(self.request(), history=True),
            views.preferences(self.request()),
        ):
            response.render()
            self.assertContains(response, "My Notices")
        self.assertContains(views.inbox(self.request()).render(), "No notices")

    def test_populated_list_detail_escape_and_get_does_not_read(self):
        route(
            self.account,
            source="test",
            event=NoticeEvent("web", timezone.now(), payload={"text": "<script>unsafe</script>"}),
            context=NoticeContext(self.account),
        )
        token = Notice.objects.get().public_ref
        for response in (views.inbox(self.request()), views.detail(self.request(), token)):
            response.render()
            self.assertContains(response, "&lt;script&gt;unsafe&lt;/script&gt;")
            self.assertNotContains(response, "<script>unsafe</script>")
        self.assertIsNone(Stored.objects.get().read_at)
        result = views.change(self.request("post"), token, "read")
        self.assertEqual(result.status_code, 302)
        self.assertIsNotNone(Stored.objects.get().read_at)
        self.assertContains(views.inbox(self.request(), history=True).render(), "Read")

    def test_get_cannot_mutate(self):
        self.assertEqual(views.change(self.request(), "missing", "read").status_code, 405)

    def test_wrong_owner_and_stale_puppet_are_missing(self):
        self.account2.characters.add(self.char2)
        route(
            self.char2,
            source="test",
            event=NoticeEvent("other", timezone.now()),
            context=NoticeContext(self.account2, self.char2),
        )
        token = Notice.objects.get().public_ref
        request = self.request(character=self.char2)
        self.assertContains(views.inbox(request).render(), "No notices")
        with self.assertRaises(Http404):
            views.detail(request, token)
        with self.assertRaises(Http404):
            views.change(self.request("post"), token, "clear")

    def test_preferences_post_validates_closed_choices(self):
        response = views.preferences(self.request("post", {"source": "test", "mode": "off"}))
        self.assertEqual(response.status_code, 302)
        response = views.preferences(
            self.request("post", {"source": "test", "mode": "arbitrary"})
        ).render()
        self.assertContains(response, "Select a valid choice")

    def test_post_endpoints_are_protected_by_csrf_middleware(self):
        from django.middleware.csrf import CsrfViewMiddleware

        request = self.request("post")
        middleware = CsrfViewMiddleware(lambda request: None)
        response = middleware.process_view(
            request, views.change, (), {"public_ref": "unknown", "operation": "read"}
        )
        self.assertEqual(response.status_code, 403)
        request = self.request("post", {"source": "test", "mode": "off"})
        self.assertEqual(
            middleware.process_view(request, views.preferences, (), {}).status_code, 403
        )
