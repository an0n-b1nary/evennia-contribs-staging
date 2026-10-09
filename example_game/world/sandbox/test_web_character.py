# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reference game seam: every web contrib resolves the same acting character.

A website visitor need not be connected in-game. Each web contrib keeps its
own ``get_character_id(user)``, and all of them must delegate to
``evennia_links.characters.web_character`` so the site agrees with itself.
"""

from importlib import import_module

from django.test import override_settings
from django.urls import include, path, reverse
from evennia.utils.test_resources import EvenniaTest
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
