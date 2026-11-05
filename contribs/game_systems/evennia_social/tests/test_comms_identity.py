# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Character who and visitor pages, without switching the host's cmdsets."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings
from evennia.accounts.accounts import DefaultAccount, DefaultGuest
from evennia.comms.models import Msg
from evennia.utils.ansi import strip_ansi
from evennia.utils.create import create_account

from evennia_links.identity import CharacterCommsAccountMixin
from evennia_social import presence
from evennia_social.commands import CmdPage, CmdWho
from evennia_social.tests.base import SocialCommandTestCase


class SocialIdentityAccount(CharacterCommsAccountMixin, DefaultAccount):
    pass


@override_settings(EVENNIA_COMMS_IDENTITY="character")
class TestSocialIdentity(SocialCommandTestCase):
    account_typeclass = SocialIdentityAccount

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)

    def _session(self, account, puppet):
        return SimpleNamespace(
            logged_in=True,
            account=account,
            get_account=lambda: account,
            get_puppet=lambda: puppet,
            conn_time=0,
            cmd_last_visible=0,
            protocol_flags={},
        )

    def who(self, sessions, viewer=None, cmdstring="who"):
        cmd = CmdWho()
        cmd.caller = cmd.account = self.account2
        cmd.session = self._session(self.account2, viewer)
        cmd.cmdstring = cmdstring
        with (
            patch("evennia.SESSION_HANDLER.get_sessions", return_value=sessions),
            patch.object(cmd, "msg") as output,
        ):
            cmd.func()
        return strip_ansi(str(output.call_args.args[0])) if output.called else ""

    @override_settings(SOCIAL_STAFF_RUN_MARKER=True)
    def test_who_uses_distinct_characters_and_leaves_out_unpuppeted_visitors(self):
        sessions = [self._session(self.account, self.char1)] * 2 + [
            self._session(self.account2, None)
        ]
        shown = self.who(sessions)
        self.assertIn("Character", shown)
        self.assertIn(f"{self.char1.key} (staff-run)", shown)
        self.assertIn("1 character online", shown)
        self.assertNotIn("Account name", shown)
        for account in (self.account, self.account2):
            self.assertNotIn(account.key, shown)
        self.assertIn("0 characters online", self.who([self._session(self.account2, None)]))

    def test_who_presence_and_staff_without_puppet(self):
        self.char2.location = self.room2
        presence.set_visibility(self.char1, presence.UNFINDABLE)
        sessions = [self._session(self.account, self.char1)]
        self.assertIn("0 characters online", self.who(sessions, self.char2))
        self.assertIn("0 characters online", self.who(sessions))
        self.account2.permissions.add("Builder")
        shown = self.who(sessions)
        self.assertIn(self.char1.key, shown)
        self.assertIn("(unfindable)", shown)

    def test_who_keeps_guest_characters(self):
        guest = create_account("GuestIdentity", None, "test-password", typeclass=DefaultGuest)
        self.char1.account = guest
        shown = self.who([self._session(guest, self.char1)])
        self.assertIn(self.char1.key, shown)
        self.assertNotIn(guest.key, shown)

    def test_privileged_who_stays_stock_and_doing_uses_characters(self):
        self.account2.permissions.add("Developer")
        with patch("evennia.commands.default.account.CmdWho.func") as stock:
            self.who([])
            stock.assert_called_once()
        self.assertIn("0 characters online", self.who([], cmdstring="doing"))

    def test_visitor_pages_staff_and_receives_reply_with_private_account_pointer(self):
        # The originating visitor session has no puppet, even if another one does.
        with (
            patch.object(self.account2, "get_puppet", return_value=None),
            patch.object(self.char1, "msg") as received,
        ):
            result = self.call(CmdPage(), f"{self.char1.key}=Need help", caller=self.account2)
        self.assertIn("Newcomer pages: Need help", strip_ansi(received.call_args.args[0][0]))
        self.assertIn("You paged", result)
        self.assertEqual(self.char1.db.last_pager_account, self.account2.pk)
        page = Msg.objects.get(db_message="Need help")
        self.assertEqual(page.senders, [self.account2])
        self.assertEqual(page.receivers, [self.char1])
        with patch.object(self.account2, "msg") as visitor:
            self.call(CmdPage(), "Welcome aboard")
            self.assertIn("Welcome aboard", str(visitor.call_args))
            self.assertNotIn(self.account.key, visitor.call_args.args[0][0])
        with patch.object(self.account2, "get_puppet", return_value=None):
            history = self.call(CmdPage(), "/recall", caller=self.account2)
        self.assertIn("Welcome aboard", history)
        self.assertNotIn(self.account.key, history)

    def test_visitor_refused_nonstaff_and_account_name_targets_without_persisting(self):
        self.account.permissions.clear()
        self.account.is_superuser = False
        with patch.object(self.account2, "get_puppet", return_value=None):
            self.call(
                CmdPage(),
                f"{self.char1.key}=Not allowed",
                "Visitors may page staff only.",
                caller=self.account2,
            )
            output = self.call(CmdPage(), f"{self.account.key}=Not allowed", caller=self.account2)
        self.assertIn("Could not find", output)
        self.assertFalse(Msg.objects.filter(db_message="Not allowed").exists())

    def test_visitors_history_and_reply_do_not_expose_staff_account_names(self):
        with patch.object(self.account2, "get_puppet", return_value=None):
            self.call(CmdPage(), f"{self.char1.key}=Help", caller=self.account2)
        # Staff replies from character select: use a neutral public label.
        self.account.db.last_pager_account = self.account2.pk
        with (
            patch.object(self.account, "get_puppet", return_value=None),
            patch.object(self.account2, "msg") as visitor,
        ):
            self.call(CmdPage(), "Staff help", caller=self.account)
        self.assertIn("Staff", str(visitor.call_args))
        self.assertNotIn(self.account.key, visitor.call_args.args[0][0])
        with patch.object(self.account2, "get_puppet", return_value=None):
            for args in ("/last", "/recall"):
                shown = self.call(CmdPage(), args, caller=self.account2)
                self.assertNotIn(self.account.key, shown)
                self.assertIn("Staff", shown)

    def test_player_replies_to_staff_who_paged_without_a_puppet(self):
        self.account2.permissions.clear()
        self.account2.is_superuser = False
        with patch.object(self.account, "get_puppet", return_value=None):
            self.call(CmdPage(), f"{self.char2.key}=Checking in", caller=self.account)
        self.assertEqual(self.char2.db.last_pager_account, self.account.pk)
        with patch.object(self.account, "msg") as staff:
            output = self.call(CmdPage(), "Thanks", caller=self.char2)
        self.assertNotIn("may page staff only", output)
        self.assertIn(f"{self.char2.key} pages: Thanks", strip_ansi(staff.call_args.args[0][0]))

    def test_page_history_masks_old_account_senders_for_nonstaff(self):
        from evennia.utils.create import create_message

        create_message(
            self.account2, "An old page", receivers=[self.char1], tags=[("page", "comms")]
        )
        self.account.permissions.clear()
        self.account.is_superuser = False
        for args in ("/last", "/recall"):
            shown = self.call(CmdPage(), args)
            self.assertIn("Newcomer", shown)
            self.assertNotIn(self.account2.key, shown)

    @override_settings(EVENNIA_COMMS_IDENTITY="account")
    def test_account_mode_requires_puppet_and_keeps_account_who(self):
        with patch.object(self.account2, "get_puppet", return_value=None):
            self.call(
                CmdPage(),
                "Char=Hello",
                "You must be puppeting a character to page.",
                caller=self.account2,
            )
        shown = self.who([self._session(self.account2, None)])
        self.assertIn("Account name", shown)
        self.assertIn("One unique account", shown)

    def test_guest_character_pages_only_staff_in_both_modes(self):
        guest = create_account("GuestPageIdentity", None, "test-password", typeclass=DefaultGuest)
        self.char2.account = guest
        guest.characters.add(self.char2)
        for mode in ("account", "character"):
            with self.subTest(mode=mode), override_settings(EVENNIA_COMMS_IDENTITY=mode):
                self.call(CmdPage(), f"{self.char1.key}=Guest help", caller=self.char2)
                self.account.permissions.clear()
                self.account.is_superuser = False
                output = self.call(CmdPage(), f"{self.char1.key}=Guest denied", caller=self.char2)
                self.assertIn("may page staff only", output)
                self.account.permissions.add("Builder")
        self.assertFalse(Msg.objects.filter(db_message="Guest denied").exists())
