# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reference game seam: evennia_guides with this game's pages, routes and partners."""

from urllib.parse import parse_qs, urlsplit

from django.test import override_settings
from django.urls import include, path
from evennia.utils.test_resources import EvenniaTest
from typeclasses.characters import Character
from typeclasses.rooms import Room

urlpatterns = [path("", include("web.urls"))]


@override_settings(ROOT_URLCONF=__name__)
class TestGuidesInTheSandbox(EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        from evennia_guides import pages

        pages.reset()
        super().setUp()

    def test_every_page_loads_and_checks_resolve(self):
        """The sandbox's pages, the contribs' pages, and real check names."""
        from evennia_guides import pages

        errors = [problem for problem in pages.validate() if problem[0] == "error"]
        self.assertEqual(errors, [])
        keys = {page.key for page in pages.all_pages()}
        self.assertTrue({"start-here", "trading", "writing-guides"} <= keys)

    def test_pages_render_through_the_site(self):
        for url, text in (
            ("/guide/", "Start here"),
            ("/guide/start-here/", "One game, every contrib"),
            ("/guide/trading/", "Both sides or neither"),
            ("/guide/principles/", "Penalize, don&#x27;t forbid"),
            ("/guide/glossary/", "The unit of money"),
        ):
            with self.subTest(url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, text)
        self.assertEqual(self.client.get("/guide/writing-guides/").status_code, 404)

    def test_the_economy_reveal_switch_gates_the_trading_page(self):
        """RP_ECONOMY_REVEALED is an evennia_links runtime setting: no restart."""
        from evennia_links import runtime

        runtime.set("RP_ECONOMY_REVEALED", False)
        try:
            self.assertEqual(self.client.get("/guide/trading/").status_code, 404)
            start = self.client.get("/guide/start-here/").content.decode()
            self.assertNotIn("/guide/trading/", start)
            self.assertIn("trading covers money", start)
        finally:
            runtime.reset("RP_ECONOMY_REVEALED")
        self.assertEqual(self.client.get("/guide/trading/").status_code, 200)

    def test_ask_links_to_the_jobs_request_form(self):
        from evennia_guides.pages import get_page
        from evennia_guides.views import ask_url

        url = urlsplit(ask_url(get_page("trading")))
        self.assertEqual(url.path, "/jobs/new/request/")
        self.assertEqual(parse_qs(url.query)["title"], ["Guide question: Money & trade"])

    def test_the_menu_links_the_guide(self):
        self.assertContains(self.client.get("/"), 'href="/guide/"')
