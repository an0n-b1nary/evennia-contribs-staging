# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
The web guide, rendered for real.

RequestFactory and direct view calls rather than the test client, as the
other web contribs do: the client trips an Evennia template-context recursion
on authenticated pages. Every case calls ``response.render()``, so template
errors and unreversable URLs fail here.
"""

from importlib import import_module
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import RequestFactory
from evennia.utils.test_resources import EvenniaTest

from evennia_guides.tests.base import FreshPagesMixin, site_settings
from evennia_guides.views import (
    GuideGlossaryView,
    GuideIndexView,
    GuidePageView,
    GuidePrinciplesView,
    ask_url,
)


class GuideViewTest(FreshPagesMixin, EvenniaTest):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.account.permissions.add("Admin")  # staff; account2 is a player

    def render(self, view, path="/guide/", user=None, **kwargs):
        request = self.factory.get(path)
        request.user = AnonymousUser() if user is None else user
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        response = view.as_view()(request, **kwargs)
        response.render()
        html = response.content.decode()
        self.assertIn("evennia_guides/css/evennia_guides.css", html)
        return html

    def page(self, key, user=None):
        return self.render(GuidePageView, f"/guide/{key}/", user=user, key=key)


class TestIndex(GuideViewTest):
    def test_players_see_visible_pages_by_category(self):
        with site_settings():
            html = self.render(GuideIndexView, user=self.account2)
        self.assertIn("Getting started", html)
        self.assertIn("What this world offers", html)  # summary
        self.assertNotIn("Money &amp; trade", html)  # gated
        self.assertNotIn("Staff notes", html)
        self.assertNotIn("Writing guide pages", html)  # the contrib's staff page
        self.assertIn("Design principles", html)
        self.assertIn("Glossary", html)

    def test_staff_see_hidden_and_staff_pages_marked(self):
        with site_settings():
            html = self.render(GuideIndexView, user=self.account)
        self.assertIn("Money &amp; trade", html)
        self.assertIn("Hidden from players until GUIDES_TEST_TRADE", html)
        self.assertIn("For staff", html)
        self.assertIn("Writing guide pages", html)

    def test_empty(self):
        with site_settings(dirs=()):
            html = self.render(GuideIndexView)
        self.assertIn("There are no guide pages yet.", html)


class TestPage(GuideViewTest):
    def test_page_renders_body_toc_footer_and_principles(self):
        with site_settings():
            html = self.page("start-here")
        self.assertIn("<h1", html)
        self.assertIn("On this page", html)
        self.assertIn('<aside class="evennia-guides-insight"', html)
        self.assertIn('href="/guide/vitality/"', html)
        self.assertIn("About the numbers", html)  # footer: true
        self.assertIn('Design principles:\n      <a href="/guide/no-quota/">', html)
        # A link to the gated page is text that names no title; raw HTML is escaped.
        self.assertIn("Trading is described in trading.", html)  # key, not title
        self.assertNotIn("/guide/trading/", html)
        self.assertIn("&lt;b&gt;Raw tags stay text.&lt;/b&gt;", html)

    def test_a_gated_page_is_a_404_until_its_check_passes(self):
        with site_settings(), self.assertRaises(Http404):
            self.page("trading", user=self.account2)
        with site_settings(trade=True):
            html = self.page("trading", user=self.account2)
            self.assertIn("Coins arrive on their own.", html)
            self.assertIn('href="/guide/trading/"', self.page("start-here"))

    def test_staff_read_a_gated_page_with_a_notice(self):
        with site_settings():
            html = self.page("trading", user=self.account)
        self.assertIn("Hidden from players until GUIDES_TEST_TRADE", html)

    def test_staff_pages_and_unknown_keys_are_404_for_players(self):
        for key in ("staff-notes", "writing-guides", "no-such-page"):
            with self.subTest(key), site_settings(), self.assertRaises(Http404):
                self.page(key, user=self.account2)
        with site_settings():
            self.assertIn("Only staff read this.", self.page("staff-notes", user=self.account))

    def test_ask_link_is_prefilled_when_configured(self):
        with site_settings(GUIDES_ASK_URL="/ask/"):
            html = self.page("start-here")
            url = ask_url(_page("start-here"))
        self.assertIn("Ask about this page", html)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["title"], ["Guide question: Start here"])
        self.assertIn("/guide/start-here/", query["description"][0])

    def test_no_ask_link_when_the_route_does_not_reverse(self):
        with site_settings(GUIDES_ASK_URL="no-such-route"):
            self.assertNotIn("Ask about this page", self.page("start-here"))


def _page(key):
    from evennia_guides import pages

    return pages.get_page(key)


class TestPrinciplesAndGlossary(GuideViewTest):
    def test_principles_list_tagged_insights_from_visible_pages(self):
        with site_settings():
            html = self.render(GuidePrinciplesView, "/guide/principles/")
        self.assertIn("Roleplay is never a quota", html)
        self.assertIn('href="/guide/start-here/#insight-play-when-you-like"', html)
        self.assertNotIn("Trades are atomic", html)  # on the gated page
        with site_settings(trade=True):
            html = self.render(GuidePrinciplesView, "/guide/principles/")
        self.assertIn("Trades are atomic", html)

    def test_glossary(self):
        with site_settings():
            html = self.render(GuideGlossaryView, "/guide/glossary/")
        self.assertIn('<dt id="vitality">', html)
        self.assertIn("staying power.", html)

    def test_empty_principles_and_glossary(self):
        with site_settings(dirs=()):
            self.assertIn(
                "No design principles", self.render(GuidePrinciplesView, "/guide/principles/")
            )
            self.assertIn(
                "The glossary is empty.", self.render(GuideGlossaryView, "/guide/glossary/")
            )
