# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reference game seam: every web contrib resolves the same acting character.

A website visitor need not be connected in-game. Each web contrib keeps its
own ``get_character_id(user)``, and all of them must delegate to
``evennia_links.characters.web_character`` so the site agrees with itself.

A character picked on the site (Evennia's own puppet link in the account menu)
reaches every contrib through ``evennia_links.web.WebCharacterMiddleware``, and
every authoring form says who it posts as.
"""

from importlib import import_module

from django.conf import settings
from django.test import override_settings
from django.urls import include, path, reverse
from evennia.utils import create
from evennia.utils.test_resources import EvenniaTest
from evennia_jobs.models import Job
from evennia_lore.models import LoreAcquisition, LoreEntry

urlpatterns = [path("", include("web.urls"))]

WEB_CONTRIBS = (
    "evennia_boards",
    "evennia_calendar",
    "evennia_jobs",
    "evennia_lore",
    "evennia_plots",
    "evennia_scenes",
    "evennia_xp",
)


class TestWebCharacterSeam(EvenniaTest):
    """EvenniaTest accounts have no sessions: this is a visitor not in the game."""

    def setUp(self):
        super().setUp()
        self.account2.characters.add(self.char2)

    def test_every_web_contrib_agrees_without_a_live_session(self):
        for label in WEB_CONTRIBS:
            with self.subTest(contrib=label):
                permissions = import_module(f"{label}.permissions")
                self.assertEqual(permissions.get_character_id(self.account2), self.char2.pk)

    @override_settings(ROOT_URLCONF=__name__)
    def test_lore_compendium_page_shows_the_characters_lore(self):
        entry = LoreEntry.create_entry(title="Ashbound Hymn", author=self.char1)
        LoreAcquisition.objects.create(
            entry=entry,
            character=self.char2,
            character_name=self.char2.key,
            source=LoreAcquisition.Source.SHARED,
        )
        self.client.force_login(self.account2)
        response = self.client.get(reverse("lore-compendium"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ashbound Hymn")


@override_settings(ROOT_URLCONF=__name__)
class TestChosenWebCharacter(EvenniaTest):
    """An account with two characters picks one on the site and acts as it everywhere."""

    def setUp(self):
        super().setUp()
        self.account2.characters.add(self.char2)
        self.alt = create.create_object(
            settings.BASE_CHARACTER_TYPECLASS, key="Ashwren", location=self.room1, home=self.room1
        )
        self.account2.characters.add(self.alt)
        self.client.force_login(self.account2)

    def _choose(self, character):
        response = self.client.get(character.web_get_puppet_url() + "?next=/")
        self.assertEqual(response.status_code, 302)

    def test_the_menu_and_every_form_name_the_chosen_character(self):
        self._choose(self.alt)
        pages = (
            reverse("job-create", kwargs={"job_type": "request"}),
            reverse("lore-create"),
            reverse("evennia_plots:plot-create"),
        )
        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Playing as Ashwren")
                self.assertContains(response, "Posting as <strong>Ashwren</strong>")
                self.assertContains(response, 'aria-describedby="form-acting-as"')

    def test_a_write_goes_out_as_the_chosen_character(self):
        # Regression: the menu named the chosen character while a write went
        # out as whichever character the resolver picked on its own.
        self._choose(self.alt)
        response = self.client.post(
            reverse("job-create", kwargs={"job_type": "request"}),
            {"title": "Lost satchel", "description": "Left it at the ford."},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Job.objects.get(title="Lost satchel").author_id, self.alt.pk)

        self._choose(self.char2)
        self.client.post(
            reverse("job-create", kwargs={"job_type": "request"}),
            {"title": "Found satchel", "description": "It was at the ford."},
        )
        self.assertEqual(Job.objects.get(title="Found satchel").author_id, self.char2.pk)

    def test_the_menu_marks_the_choice_only_with_several_characters(self):
        self._choose(self.alt)
        response = self.client.get(reverse("lore-create"))
        self.assertContains(response, "Play as")
        self.assertContains(response, 'aria-current="true">Ashwren</a>')

        self.account2.characters.remove(self.alt)
        response = self.client.get(reverse("lore-create"))
        self.assertNotContains(response, "Play as")
        self.assertContains(response, f"Playing as {self.char2.key}")
