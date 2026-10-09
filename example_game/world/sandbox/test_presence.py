# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reference game seam: presence (evennia_social 0.4) across commands and the home page."""

from django.test import override_settings
from django.urls import include, path
from django.utils import timezone
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
class TestRecentlyConnectedLeavesOutDarkStaff(EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def test_dark_staff_account_is_not_listed(self):
        from evennia_social import presence

        now = timezone.now()
        for account, character in ((self.account, self.char1), (self.account2, self.char2)):
            account.characters.add(character)
            account.last_login = now
            account.save()

        def listed():
            response = self.client.get("/")
            self.assertEqual(response.status_code, 200)
            return [account.pk for account in response.context["accounts_connected_recent"]]

        self.assertIn(self.account.pk, listed())
        presence.set_visibility(self.char1, presence.UNFINDABLE)
        self.assertIn(self.account.pk, listed())  # unfindable hides location only
        presence.set_visibility(self.char1, presence.DARK)
        self.assertNotIn(self.account.pk, listed())
        self.assertIn(self.account2.pk, listed())
