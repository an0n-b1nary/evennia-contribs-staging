# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reference game seam: presence (evennia_social 0.4) across commands and the home page."""

from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from django.urls import include, path
from django.utils import timezone
from evennia.utils.create import create_account, create_object
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
    """The home page lists characters, never login names, staff or guests (#91)."""

    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        now = timezone.now()
        # self.account is a Developer; self.account2 is an ordinary player.
        for account, character in ((self.account, self.char1), (self.account2, self.char2)):
            account.characters.add(character)
            account.db._last_puppet = character
            account.last_login = now
            account.save()

    def listed(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["accounts_connected_recent"])
        names = [entry["character"].key for entry in response.context["recently_connected"]]
        return names, response.content.decode()

    def test_player_is_listed_by_last_played_character_name(self):
        alt = create_object(Character, key="Quiet Alt", location=self.room1)
        self.account2.characters.add(alt)
        names, html = self.listed()
        self.assertEqual(names, [self.char2.key])
        self.assertIn(f">{self.char2.key}</a>", html)
        self.assertNotIn(self.account2.username, html)
        self.assertNotIn("Quiet Alt", html)  # other characters stay unlinked

    def test_staff_are_left_out_unless_the_game_lists_them(self):
        from evennia_social import presence

        self.assertNotIn(self.char1.key, self.listed()[0])
        with override_settings(SANDBOX_HOMEPAGE_LIST_STAFF=True):
            self.assertIn(self.char1.key, self.listed()[0])
            presence.set_visibility(self.char1, presence.DARK)
            self.assertNotIn(self.char1.key, self.listed()[0])

    def test_unfindable_is_listed_as_in_who(self):
        from evennia_social import presence

        presence.set_visibility(self.char2, presence.UNFINDABLE)
        self.assertIn(self.char2.key, self.listed()[0])  # unfindable hides location only

    def test_accounts_without_a_played_character_are_left_out(self):
        self.account2.db._last_puppet = None
        self.assertEqual(self.listed()[0], [])
        self.account2.db._last_puppet = self.char2
        self.account2.characters.remove(self.char2)
        self.assertEqual(self.listed()[0], [])

    def test_characters_the_visitor_may_not_view_are_left_out(self):
        self.char2.locks.add("view:false()")
        self.assertEqual(self.listed()[0], [])

    def test_guests_are_left_out_with_or_without_social(self):
        from typeclasses.accounts import Guest

        guest = create_account(
            "Visitor", None, "test-password", typeclass=Guest, permissions=["Guests"]
        )
        visitor = create_object(Character, key="Wanderer", location=self.room1)
        visitor.tags.add("character", category="guest")
        guest.characters.add(visitor)
        guest.db._last_puppet = visitor
        guest.last_login = timezone.now()
        guest.save()
        self.assertEqual(self.listed()[0], [self.char2.key])
        installed = apps.is_installed
        with patch(
            "web.website.views.index.apps.is_installed",
            side_effect=lambda label: label != "evennia_social" and installed(label),
        ):
            self.assertEqual(self.listed()[0], [self.char2.key])
            with override_settings(SANDBOX_HOMEPAGE_LIST_STAFF=True):
                self.assertCountEqual(self.listed()[0], [self.char1.key, self.char2.key])
