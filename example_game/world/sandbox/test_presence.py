# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reference game seam: presence (evennia_social 0.4) across commands and the home page."""

from datetime import timedelta
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from django.urls import include, path
from django.utils import timezone
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaTest
from typeclasses.characters import Character
from typeclasses.rooms import Room

urlpatterns = [path("", include("web.urls"))]


class TestPresenceCommandsMounted(EvenniaTest):
    def test_unfindable_in_character_and_who_replaced_for_accounts(self):
        from commands.default_cmdsets import AccountCmdSet, CharacterCmdSet

        from evennia_social.commands import CmdWho

        self.assertIn("+unfindable", {cmd.key for cmd in CharacterCmdSet().commands})
        who = [cmd for cmd in AccountCmdSet().commands if cmd.key == "who"]
        self.assertEqual(len(who), 1)
        self.assertIsInstance(who[0], CmdWho)


@override_settings(ROOT_URLCONF=__name__)
class TestRecentlyConnected(EvenniaTest):
    """The home page lists characters played lately, never accounts (#91)."""

    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        now = timezone.now()
        # char1 is a Developer's; char2 an ordinary player's, seen more recently.
        self.char1.attributes.add("sandbox_last_seen", now - timedelta(hours=2))
        self.char2.attributes.add("sandbox_last_seen", now - timedelta(hours=1))

    def listed(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["accounts_connected_recent"])
        names = [entry["character"].key for entry in response.context["recently_connected"]]
        return names, response.content.decode()

    def test_every_character_played_lately_newest_first(self):
        alt = create_object(Character, key="Quiet Alt", location=self.room1)
        self.account2.characters.add(alt)
        alt.attributes.add("sandbox_last_seen", timezone.now())
        names, html = self.listed()
        self.assertEqual(names, ["Quiet Alt", self.char2.key, self.char1.key])
        self.assertIn(f">{self.char2.key}</a>", html)
        self.assertNotRegex(html, rf"\b{self.account.username}\b")
        self.assertNotIn(self.account2.username, html)

    def test_unlisted_characters_are_left_out(self):
        from evennia_social import presence

        self.char1.key = "HiddenLegacyStaff"
        self.char2.key = "HiddenCanonicalPlayer"
        presence.set_visibility(self.char2, presence.UNFINDABLE)
        self.char1.attributes.add(presence.ATTRIBUTE, "dark")
        for mode in ("account", "character"):
            with override_settings(EVENNIA_COMMS_IDENTITY=mode), self.subTest(mode=mode):
                names, html = self.listed()
                self.assertEqual(names, [])
                self.assertNotIn(self.char1.key, html)
                self.assertNotIn(self.char2.key, html)
                self.assertEqual(self.char1.attributes.get(presence.ATTRIBUTE), "dark")

    def test_characters_not_seen_lately_are_left_out(self):
        self.char1.attributes.add("sandbox_last_seen", timezone.now() - timedelta(days=8))
        self.char2.attributes.remove("sandbox_last_seen")
        self.assertEqual(self.listed()[0], [])

    def test_characters_the_visitor_may_not_view_are_left_out(self):
        self.char2.locks.add("view:false()")
        self.assertEqual(self.listed()[0], [self.char1.key])

    def test_guests_are_left_out_with_or_without_social(self):
        visitor = create_object(Character, key="Wanderer", location=self.room1)
        visitor.tags.add("character", category="guest")
        visitor.attributes.add("sandbox_last_seen", timezone.now())
        expected = [self.char2.key, self.char1.key]
        self.assertEqual(self.listed()[0], expected)
        installed = apps.is_installed
        with patch(
            "web.website.views.index.apps.is_installed",
            side_effect=lambda label: label != "evennia_social" and installed(label),
        ):
            self.assertEqual(self.listed()[0], expected)
