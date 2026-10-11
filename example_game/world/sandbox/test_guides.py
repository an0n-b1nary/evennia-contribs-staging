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

    def test_the_launch_system_pages_render_through_the_site(self):
        """Each contrib's player page, through the real site templates."""
        for key, text in (
            ("checks", "Why pips never cross a grade"),
            ("character-sheet", "Why weakness is free"),
            ("tests", "Suggestions, not rails"),
            ("posing", "Whose turn it is"),
            ("scenes", "Private means private everywhere"),
            ("social", "Nobody is moved without saying yes"),
            ("rp-sessions", "Play, and it counts"),
            ("xp", "Paid for what happened, once"),
            ("plots", "Rewarding the habits that include people"),
            ("calendar", "Losing a draw counts for something"),
            ("map", "A map is a way of finding people"),
            ("regions", "One room, several regions"),
            ("boards", "In-character boards"),
            ("requests", "Only staff know who reported"),
            ("accessibility", "Colour is never the only signal"),
        ):
            with self.subTest(key):
                response = self.client.get(f"/guide/{key}/")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, text)

    def test_contrib_pages_link_only_to_pages_their_dependencies_ship(self):
        """A contrib's pages validate in a game that installs it with nothing optional.

        The full sandbox installs every partner, so a link from one contrib's page
        to an optional partner's page resolves here and breaks guides_check in a
        game without that partner. Rebuild each contrib's page set from its own
        guides/ plus those of its hard [project] dependencies, and resolve its
        links and principle tags against that alone.
        """
        import re
        from importlib import metadata

        from evennia_guides import pages

        by_label = {}
        for label, directory in pages.guide_dirs():
            if label == "host":
                continue
            by_label[label] = [
                pages.parse_page(path.read_text(encoding="utf-8"), source=str(path), origin=label)
                for path in sorted(directory.glob("*.md"))
            ]

        def hard_dependencies(label):
            try:
                requirements = metadata.requires(label.replace("_", "-")) or []
            except metadata.PackageNotFoundError:
                return set()
            found = set()
            for line in requirements:
                if ";" in line:
                    continue  # An extra or other marker: optional, not a hard dependency.
                name = re.match(r"[A-Za-z0-9._-]+", line).group().lower()
                if name.startswith("evennia-"):
                    found.add(name.replace("-", "_"))
            return found

        self.assertIn("evennia_rp_rules", hard_dependencies("evennia_rp_chargen"))
        for label, own in by_label.items():
            available = list(own)
            for dependency in hard_dependencies(label):
                available += by_label.get(dependency, [])
            keys = {page.key for page in available}
            keys |= {alias for page in available for alias in page.aliases}
            principles = {page.key for page in available if page.kind == "principle"}
            for page in own:
                tags = set(page.principles)
                for insight in page.document.insights():
                    tags.update(insight.tags)
                with self.subTest(page=page.source):
                    self.assertEqual(set(page.document.links()) - keys, set())
                    self.assertEqual(tags - principles, set())
