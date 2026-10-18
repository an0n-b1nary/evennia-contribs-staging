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

    def _reader(self, account, *permissions):
        for permission in account.permissions.all():
            account.permissions.remove(permission)
        for permission in permissions:
            account.permissions.add(permission)
        self.client.force_login(account)

    def _guide_menu(self, path="/", user=None):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory
        from web.website.nav import build_menu

        request = RequestFactory().get(path)
        request.user = user or AnonymousUser()
        groups = {group["label"]: group for group in build_menu(request)["groups"]}
        self.assertNotIn("Guide", [item["label"] for item in groups["Community"]["items"]])
        return groups["Guide"]

    def test_the_guide_has_its_own_dropdown(self):
        """Start here, the index, principles and glossary for everyone."""
        items = self._guide_menu()["items"]
        self.assertEqual(
            [(item["label"], item["url"]) for item in items],
            [
                ("Start here", "/guide/start-here/"),
                ("All guides", "/guide/"),
                ("Design principles", "/guide/principles/"),
                ("Glossary", "/guide/glossary/"),
            ],
        )

    def test_staff_get_the_staff_guides_entry(self):
        self._reader(self.account2)
        self.assertNotIn(
            "Staff guides", [i["label"] for i in self._guide_menu(user=self.account2)["items"]]
        )
        self.assertNotContains(self.client.get("/"), 'href="/guide/staff-start-here/"')

        self._reader(self.account, "Builder")
        items = self._guide_menu(user=self.account)["items"]
        self.assertEqual(
            items[-1], {"label": "Staff guides", "url": "/guide/staff-start-here/", "active": False}
        )
        self.assertContains(self.client.get("/"), 'href="/guide/staff-start-here/"')

    def test_a_guide_page_activates_its_own_entry(self):
        """/guide/start-here/ lights Start here, not All guides as well."""
        group = self._guide_menu("/guide/start-here/")
        self.assertTrue(group["active"])
        self.assertEqual([i["label"] for i in group["items"] if i["active"]], ["Start here"])
        group = self._guide_menu("/guide/combat/")
        self.assertEqual([i["label"] for i in group["items"] if i["active"]], ["All guides"])

    def test_staff_pages_are_for_builders_only(self):
        """GUIDES_STAFF_LOCK is Builder here, matching every staff command."""
        for url in ("/guide/staff-start-here/", "/guide/writing-guides/"):
            with self.subTest(url, reader="anonymous"):
                self.assertEqual(self.client.get(url).status_code, 404)
        self._reader(self.account2)
        for url in ("/guide/staff-start-here/", "/guide/writing-guides/"):
            with self.subTest(url, reader="player"):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertNotContains(self.client.get("/guide/"), "/guide/staff-start-here/")

        self._reader(self.account, "Builder")
        self.assertContains(self.client.get("/guide/staff-start-here/"), "Moderation and safety")
        self.assertContains(self.client.get("/guide/writing-guides/"), "Staff pages")
        index = self.client.get("/guide/").content.decode()
        staff = index[index.index('id="guide-staff-heading"') :]
        self.assertIn("/guide/staff-start-here/", staff)

    def test_the_home_page_starts_with_the_guide(self):
        response = self.client.get("/")
        self.assertContains(response, 'href="/guide/start-here/">Start with the guide</a>')

    def test_the_systems_table_links_each_visible_guide_page(self):
        """In-game-only contribs are listed too, and a hidden page isn't linked."""
        html = self.client.get("/").content.decode()
        for app_label, url in (
            ("evennia_boards", "/guide/boards/"),
            ("evennia_rp_chargen", "/guide/character-sheet/"),
            ("evennia_rp_combat", "/guide/combat/"),
            ("evennia_building", "/guide/building/"),
            ("evennia_rp_equipment", "/guide/equipment/"),
        ):
            with self.subTest(app_label):
                self.assertIn(f'href="{url}" aria-label="Guide page for {app_label}"', html)
        for app_label in ("evennia_rp_crafting", "evennia_economy", "evennia_moderation"):
            with self.subTest(app_label):
                self.assertIn(f"<code>{app_label}</code>", html)
        self.assertNotIn('aria-label="Guide page for evennia_guides"', html)

        with override_settings(RP_COMBAT_REVEALED=False):
            html = self.client.get("/").content.decode()
        self.assertIn("<code>evennia_rp_combat</code>", html)
        self.assertNotIn('aria-label="Guide page for evennia_rp_combat"', html)

    def test_the_equipment_switch_hides_its_commands_and_page(self):
        """RP_EQUIPMENT_REVEALED hides gear from players at runtime; staff keep it."""
        from commands.default_cmdsets import CharacterCmdSet

        from evennia_links import runtime

        gear = next(cmd for cmd in CharacterCmdSet().commands if cmd.key == "+gear")
        self.assertContains(
            self.client.get("/guide/equipment/"), "Gear commits, it doesn&#x27;t grant"
        )
        self.assertContains(self.client.get("/guide/start-here/"), 'href="/guide/equipment/"')
        self.assertTrue(gear.access(self.char2))

        runtime.set("RP_EQUIPMENT_REVEALED", False)
        try:
            self.assertEqual(self.client.get("/guide/equipment/").status_code, 404)
            start = self.client.get("/guide/start-here/").content.decode()
            self.assertNotIn('href="/guide/equipment/"', start)
            self.assertIn("gear and outfits", start)
            self.assertNotIn(
                'aria-label="Guide page for evennia_rp_equipment"',
                self.client.get("/").content.decode(),
            )
            for permission in self.char2.permissions.all():
                self.char2.permissions.remove(permission)
            self.assertFalse(gear.access(self.char2))
            self.assertTrue(gear.access(self.char1))

            self._reader(self.account, "Builder")
            self.assertContains(
                self.client.get("/guide/equipment/"), "Gear commits, it doesn&#x27;t grant"
            )
        finally:
            runtime.reset("RP_EQUIPMENT_REVEALED")
        self.assertTrue(gear.access(self.char2))

    def test_the_equipment_staff_page_is_linked_from_the_staff_index(self):
        self._reader(self.account2)
        self.assertEqual(self.client.get("/guide/equipment-staff/").status_code, 404)

        self._reader(self.account, "Builder")
        self.assertContains(self.client.get("/guide/equipment-staff/"), "Finding broken gear")
        self.assertContains(
            self.client.get("/guide/staff-start-here/"), 'href="/guide/equipment-staff/"'
        )

    def test_start_here_links_every_system_page(self):
        from evennia_guides.pages import all_pages, get_page

        links = set(get_page("start-here").document.links())
        systems = {
            page.key
            for page in all_pages()
            if page.kind == "guide" and page.audience == "player" and page.origin != "host"
        }
        self.assertEqual(systems - links, set())

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

    def test_the_joining_page_renders_and_is_linked_from_start_here(self):
        self.assertContains(
            self.client.get("/guide/joining/"), "Your password never enters the application"
        )
        self.assertContains(self.client.get("/guide/start-here/"), 'href="/guide/joining/"')

    def test_moderation_and_community_staff_pages_are_for_staff(self):
        """Each staff page: a 404 for players, readable by Builders, linked from the index."""
        pages = (
            ("moderation-staff", "Reviewing applications"),
            ("jobs-staff", "A decision is separate from status"),
            ("social-staff", "Going dark"),
            ("rptracker-staff", "Read activity, never ration it"),
        )
        self._reader(self.account2)
        for key, _text in pages:
            with self.subTest(key, reader="player"):
                self.assertEqual(self.client.get(f"/guide/{key}/").status_code, 404)

        self._reader(self.account, "Builder")
        index = self.client.get("/guide/staff-start-here/")
        for key, text in pages:
            with self.subTest(key, reader="staff"):
                self.assertContains(self.client.get(f"/guide/{key}/"), text)
                self.assertContains(index, f'href="/guide/{key}/"')
