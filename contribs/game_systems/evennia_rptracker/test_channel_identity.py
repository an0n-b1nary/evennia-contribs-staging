# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Channel command privacy in both communication identity modes."""

from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from evennia.accounts.accounts import DefaultAccount
from evennia.accounts.bots import Bot
from evennia.comms.comms import DefaultChannel
from evennia.utils.create import create_account, create_channel
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_links.communication import CharacterCommsChannelMixin, CommunicationChannelMixin
from evennia_links.identity import CharacterCommsAccountMixin, sending_character
from evennia_rptracker.channel_commands import CmdICChannel
from evennia_rptracker.typeclasses import sending_character as old_sending_character


class TrackerChannelAccount(CharacterCommsAccountMixin, DefaultAccount):
    pass


class TrackerCharacterChannel(
    CharacterCommsChannelMixin, CommunicationChannelMixin, DefaultChannel
):
    pass


@override_settings(EVENNIA_COMMS_IDENTITY="character")
class TestChannelIdentity(EvenniaCommandTest):
    account_typeclass = TrackerChannelAccount

    def setUp(self):
        super().setUp()
        self.channel = create_channel("Ordinary", typeclass=TrackerCharacterChannel)
        self.channel.send_to_online_only = False
        self.channel.connect(self.account)
        self.channel.connect(self.account2)

    def command(self):
        command = CmdICChannel()
        command.caller = self.account
        command.session = SimpleNamespace(puppet=self.char1)
        return command

    def test_normal_channel_command_passes_the_originating_session(self):
        with patch.object(self.account, "get_puppet", return_value=self.char1):
            output = self.call(
                CmdICChannel(), "Ordinary = A character thought", caller=self.account
            )
        self.assertIn("Char: A character thought", output)
        self.assertNotIn(self.account.key, output)

    def test_who_lists_distinct_puppets_and_counts_visitor_sessions(self):
        self.account2.permissions.clear()
        self.account2.is_superuser = False
        with (
            patch.object(
                self.channel.subscriptions, "online", return_value=[self.account, self.account2]
            ),
            patch.object(
                self.account.sessions, "all", return_value=[SimpleNamespace(puppet=self.char1)] * 2
            ),
            patch.object(
                self.account2.sessions,
                "all",
                return_value=[
                    SimpleNamespace(puppet=self.char2),
                    SimpleNamespace(puppet=None),
                    SimpleNamespace(puppet=None),
                ],
            ),
        ):
            output = self.call(CmdICChannel(), "/who Ordinary", caller=self.account)
        self.assertIn("Char", output)
        self.assertIn("Char2", output)
        self.assertIn("and 2 newcomers", output)
        self.assertNotIn(self.account.key, output)
        self.assertNotIn(self.account2.key, output)

    @skipUnless(apps.is_installed("evennia_social"), "requires Social presence")
    def test_who_applies_presence_for_players_and_staff(self):
        from evennia_social.presence import UNFINDABLE, set_visibility

        set_visibility(self.char2, UNFINDABLE)
        # Social lists unfindable characters to people in the same room.
        self.char2.location = self.room2
        with (
            patch.object(self.channel.subscriptions, "online", return_value=[self.account2]),
            patch.object(
                self.account2.sessions, "all", return_value=[SimpleNamespace(puppet=self.char2)]
            ),
        ):
            command = self.command()
            self.assertTrue(any("Char2" in name for name in command.channel_list_who(self.channel)))
            self.account.permissions.clear()
            self.account.is_superuser = False
            self.assertEqual(command.channel_list_who(self.channel), [])

    @skipUnless(apps.is_installed("evennia_social"), "requires Social presence")
    def test_who_shows_a_players_own_unlisted_puppet_to_that_session(self):
        from evennia_social.presence import UNFINDABLE, set_visibility

        self.account.permissions.clear()
        self.account.is_superuser = False
        set_visibility(self.char1, UNFINDABLE)
        with (
            patch.object(self.channel.subscriptions, "online", return_value=[self.account]),
            patch.object(
                self.account.sessions, "all", return_value=[SimpleNamespace(puppet=self.char1)]
            ),
        ):
            names = self.command().channel_list_who(self.channel)
        self.assertEqual(names, [self.char1.get_display_name(self.account)])

    def test_who_names_relay_bots_without_counting_them_as_newcomers(self):
        bot = create_account("IRCRelay", None, None, typeclass=Bot)
        with (
            patch.object(self.channel.subscriptions, "online", return_value=[bot]),
            patch.object(bot.sessions, "all", return_value=[SimpleNamespace(puppet=None)]),
        ):
            names = self.command().channel_list_who(self.channel)
        self.assertEqual(names, [bot.get_display_name(self.account)])

    def test_who_keeps_guest_puppets_and_omits_staff_without_puppet(self):
        self.char2.tags.add("character", category="guest")
        with (
            patch.object(
                self.channel.subscriptions, "online", return_value=[self.account, self.account2]
            ),
            patch.object(self.account.sessions, "all", return_value=[SimpleNamespace(puppet=None)]),
            patch.object(
                self.account2.sessions, "all", return_value=[SimpleNamespace(puppet=self.char2)]
            ),
        ):
            names = self.command().channel_list_who(self.channel)
        self.assertEqual(names, [self.char2.get_display_name(self.account)])

    def test_boot_and_ban_announce_public_names_and_remove_aliases(self):
        for method in ("boot_user", "ban_user"):
            self.channel.connect(self.account2)
            self.channel.add_user_channel_alias(self.account2, "myalias")
            with (
                self.subTest(method=method),
                patch.object(self.account2, "get_all_puppets", return_value=[self.char2]),
                patch.object(self.channel, "msg") as broadcast,
                patch.object(self.account2, "msg") as target,
            ):
                result = getattr(self.command(), method)(self.channel, self.account2, reason="Spam")
            self.assertEqual(result, (True, ""))
            self.assertEqual(
                broadcast.call_args.args[0], "Char2 was booted from channel by Char. Reason: Spam"
            )
            self.assertIn("by Char. Reason: Spam", target.call_args.args[0])
            self.assertNotIn(self.account.key, target.call_args.args[0])
            self.assertFalse(self.channel.has_connection(self.account2))
            self.assertIsNone(self.account2.nicks.get("myalias", category="channel"))
        self.assertIn(self.account2, self.channel.banlist)

    def test_boot_without_puppets_and_quiet_boot_do_not_leak_names(self):
        command = self.command()
        command.session = SimpleNamespace(puppet=None)
        with (
            patch.object(self.account2, "get_all_puppets", return_value=[]),
            patch.object(self.channel, "msg") as broadcast,
            patch.object(self.account2, "msg") as target,
        ):
            self.assertEqual(command.boot_user(self.channel, self.account2), (True, ""))
            self.assertEqual(
                broadcast.call_args.args[0], "Newcomer was booted from channel by Newcomer."
            )
            self.assertNotIn(self.account.key, target.call_args.args[0])
            self.channel.connect(self.account2)
            broadcast.reset_mock()
            command.boot_user(self.channel, self.account2, quiet=True)
            broadcast.assert_not_called()

    def test_history_command_displays_the_log_written_by_the_channel(self):
        with patch("evennia.utils.logger.log_file") as history:
            self.channel.msg("A thought", senders=self.char1)
        line = f"2026-11-04 12:00:00 [-] {history.call_args.args[0]}\n"

        def tail(filename, start, count, callback):
            self.assertEqual(filename, self.channel.get_log_filename())
            callback([line])

        with patch("evennia.commands.default.comms.tail_log_file", side_effect=tail):
            output = self.call(CmdICChannel(), "/history Ordinary", caller=self.account2)
        self.assertIn("Char: A thought", output)
        self.assertNotIn(self.account.key, output)

    @override_settings(EVENNIA_COMMS_IDENTITY="account")
    def test_account_mode_keeps_stock_who_and_boot(self):
        channel = create_channel("Account", typeclass=DefaultChannel)
        channel.connect(self.account2)
        with patch.object(channel.subscriptions, "online", return_value=[self.account2]):
            names = self.command().channel_list_who(channel)
        self.assertEqual(names, [self.account2.get_display_name(self.account)])
        with patch.object(channel, "msg") as broadcast:
            self.command().boot_user(channel, self.account2)
        self.assertIn(self.account.key, broadcast.call_args.args[0])
        self.assertIn(self.account2.key, broadcast.call_args.args[0])

    def test_sender_resolver_remains_exported_for_ic_channel_adopters(self):
        self.assertIs(old_sending_character, sending_character)
