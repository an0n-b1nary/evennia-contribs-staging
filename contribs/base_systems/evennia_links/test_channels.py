# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Ordinary channels must preserve character identity through logs and views."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from evennia.accounts.accounts import DefaultAccount, DefaultGuest
from evennia.comms.comms import DefaultChannel
from evennia.utils.create import create_account, create_channel
from evennia.utils.test_resources import EvenniaTest

from evennia_links.communication import CharacterCommsChannelMixin, CommunicationChannelMixin
from evennia_links.guests import welcome_channel
from evennia_links.identity import CharacterCommsAccountMixin, sending_character


class ChannelPrivacyAccount(CharacterCommsAccountMixin, DefaultAccount):
    pass


class ChannelPrivacyGuest(CharacterCommsAccountMixin, DefaultGuest):
    pass


class LinksCharacterChannel(CharacterCommsChannelMixin, CommunicationChannelMixin, DefaultChannel):
    pass


@override_settings(EVENNIA_COMMS_IDENTITY="character")
class TestLinksCharacterChannels(EvenniaTest):
    account_typeclass = ChannelPrivacyAccount

    def setUp(self):
        super().setUp()
        self.account.permissions.clear()
        self.account.is_superuser = False
        self.channel = create_channel("Public", typeclass=LinksCharacterChannel)
        self.welcome = create_channel("Welcome", typeclass=LinksCharacterChannel)
        self.welcome.tags.add("welcome", category="comms")
        # Use real receiver hooks without depending on live sessions.
        self.channel.send_to_online_only = False
        self.welcome.send_to_online_only = False
        for channel in (self.channel, self.welcome):
            channel.connect(self.account2)

    def test_account_speaks_as_session_puppet_and_public_log_uses_display_name(self):
        with (
            patch.object(self.char1, "get_display_name", return_value="Character alias"),
            patch.object(self.account2, "channel_msg") as received,
            patch("evennia.utils.logger.log_file") as history,
        ):
            self.channel.msg(
                "Hello", senders=self.account, session=SimpleNamespace(puppet=self.char1)
            )
        self.assertIn("Character alias: Hello", received.call_args.args[0])
        self.assertEqual(received.call_args.kwargs["senders"], [self.char1])
        history.assert_called_once_with("Character alias: Hello", self.channel.get_log_filename())

    def test_no_session_resolves_only_one_distinct_puppet(self):
        for puppets, allowed in (
            ([], False),
            ([self.char1], True),
            ([self.char1] * 2, True),
            ([self.char1, self.char2], False),
        ):
            with (
                self.subTest(puppets=puppets),
                patch.object(self.account, "get_all_puppets", return_value=puppets),
                patch.object(self.account, "msg") as feedback,
                patch.object(self.account2, "channel_msg") as received,
                patch("evennia.utils.logger.log_file") as history,
            ):
                self.channel.msg("Hello", senders=self.account)
                self.assertEqual(received.called, allowed)
                self.assertEqual(history.called, allowed)
                if not allowed:
                    self.assertTrue(feedback.called)

    def test_session_at_character_select_does_not_borrow_another_sessions_puppet(self):
        with (
            patch.object(self.account, "get_all_puppets", return_value=[self.char1]),
            patch.object(self.account2, "channel_msg") as received,
            patch("evennia.utils.logger.log_file") as history,
        ):
            self.welcome.msg("Hello", senders=self.account, session=SimpleNamespace(puppet=None))
        self.assertIn("Newcomer: Hello", received.call_args.args[0])
        self.assertEqual(history.call_args.args[0], "Newcomer: Hello")

    def test_visitor_is_masked_to_players_and_history_but_identified_to_staff(self):
        self.account2.permissions.add("Builder")
        listener = create_account(
            "ListeningAccount", None, "test-password", typeclass=ChannelPrivacyAccount
        )
        self.welcome.connect(listener)
        with (
            patch.object(listener, "channel_msg") as player,
            patch.object(self.account2, "channel_msg") as staff,
            patch("evennia.utils.logger.log_file") as history,
        ):
            self.welcome.msg("Hello", senders=self.account, session=SimpleNamespace(puppet=None))
        self.assertIn("Newcomer: Hello", player.call_args.args[0])
        self.assertNotIn(self.account.key, player.call_args.args[0])
        self.assertIn(self.account.key, staff.call_args.args[0])
        self.assertEqual(history.call_args.args[0], "Newcomer: Hello")

    def test_guest_puppet_uses_character_name_only_on_welcome(self):
        guest = create_account(
            "GuestIdentity", None, "test-password", typeclass=ChannelPrivacyGuest
        )
        self.char1.account = guest
        guest.characters.add(self.char1)
        self.char1.tags.add("character", category="guest")
        for sender in (guest, self.char1):
            for channel, allowed in ((self.welcome, True), (self.channel, False)):
                with (
                    self.subTest(channel=channel, sender=sender),
                    patch.object(self.account2, "channel_msg") as received,
                    patch("evennia.utils.logger.log_file") as history,
                ):
                    channel.msg("Hello", senders=sender, session=SimpleNamespace(puppet=self.char1))
                    self.assertEqual(received.called, allowed)
                    self.assertEqual(history.called, allowed)
                    if allowed:
                        self.assertIn("Char: Hello", received.call_args.args[0])

    def test_staff_without_puppet_and_multiple_senders_are_refused(self):
        self.account.permissions.add("Builder")
        for senders in (self.account, [self.account, self.account2]):
            with (
                self.subTest(senders=senders),
                patch.object(self.account, "msg") as feedback,
                patch.object(self.account2, "channel_msg") as received,
                patch("evennia.utils.logger.log_file") as history,
            ):
                self.channel.msg("Hello", senders=senders, session=SimpleNamespace(puppet=None))
                received.assert_not_called()
                history.assert_not_called()
                feedback.assert_called_with("Speak on this channel as one puppeted character.")

    def test_system_messages_and_authorized_emits_pass_without_puppet(self):
        with (
            patch.object(self.account2, "channel_msg") as received,
            patch("evennia.utils.logger.log_file") as history,
        ):
            self.channel.msg("System notice")
            self.assertIn("System notice", received.call_args.args[0])
            self.assertEqual(history.call_args.args[0], "System notice")
            received.reset_mock()
            self.channel.msg("Unauthorized emit", senders=self.account, emit=True)
            received.assert_not_called()
            self.account.permissions.add("Admin")
            self.channel.msg("Staff emit", senders=self.account, emit=True)
            self.assertIn("Staff emit", received.call_args.args[0])

    def test_communication_restriction_prevents_delivery_and_logging(self):
        with (
            patch("evennia_links.communication.denial", return_value="Restricted"),
            patch.object(self.char1, "msg") as feedback,
            patch.object(self.account2, "channel_msg") as received,
            patch("evennia.utils.logger.log_file") as history,
        ):
            self.channel.msg("Hello", senders=self.char1, bypass_mute=True)
        feedback.assert_called_once_with("Restricted")
        received.assert_not_called()
        history.assert_not_called()

    def test_muted_subscriber_does_not_receive_message(self):
        self.channel.mute(self.account2)
        with patch.object(self.account2, "channel_msg") as received:
            self.channel.msg("Hello", senders=self.char1)
        received.assert_not_called()

    def test_public_web_history_renders_the_actual_logged_identity(self):
        for sender, channel, name in (
            (self.char1, self.channel, "Char"),
            (self.account, self.welcome, "Newcomer"),
        ):
            with (
                self.subTest(name=name),
                patch("evennia.utils.logger.log_file") as history,
            ):
                channel.msg(
                    "A public thought", senders=sender, session=SimpleNamespace(puppet=None)
                )
                line = f"2026-11-04 12:00:00 [-] {history.call_args.args[0]}\n"
                with (
                    patch("evennia.web.website.views.channels.tail_log_file", return_value=[line]),
                    patch(
                        "evennia.web.website.views.channels.ChannelDetailView.model",
                        LinksCharacterChannel,
                    ),
                ):
                    response = self.client.get(
                        reverse("channel-detail", kwargs={"slug": channel.key.lower()})
                    )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f"{name}: A public thought")
                self.assertNotContains(response, self.account.key)

    def test_welcome_lookup_fails_closed_on_missing_and_duplicate_tags(self):
        self.assertEqual(welcome_channel(), self.welcome)
        self.welcome.tags.remove("welcome", category="comms")
        with self.assertRaisesMessage(ValueError, "welcome channel is unavailable"):
            welcome_channel()
        self.welcome.tags.add("welcome", category="comms")
        self.channel.tags.add("welcome", category="comms")
        with (
            self.assertRaisesMessage(ValueError, "welcome channel is unavailable"),
        ):
            welcome_channel()
        with patch.object(self.account2, "channel_msg") as received:
            self.welcome.msg("Hello", senders=self.account, session=SimpleNamespace(puppet=None))
        received.assert_not_called()

    @override_settings(EVENNIA_COMMS_IDENTITY="account")
    def test_account_mode_retains_stock_channel_sender_and_log(self):
        channel = create_channel("Account mode", typeclass=DefaultChannel)
        channel.send_to_online_only = False
        channel.connect(self.account2)
        with (
            patch.object(self.account2, "channel_msg") as received,
            patch("evennia.utils.logger.log_file") as history,
        ):
            channel.msg("Hello", senders=self.account)
        self.assertEqual(received.call_args.kwargs["senders"], [self.account])
        self.assertEqual(history.call_args.args[0], f"{self.account.key}: Hello")

    def test_session_puppet_must_belong_to_sender(self):
        self.assertIsNone(sending_character(self.account, SimpleNamespace(puppet=self.char2)))
        self.assertEqual(
            sending_character(self.account, SimpleNamespace(puppet=self.char1)), self.char1
        )
