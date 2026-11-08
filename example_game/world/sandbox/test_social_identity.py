# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Social identity and boundaries with the reference host's composed partners."""

from unittest.mock import patch

from django.test import override_settings
from evennia.comms.comms import DefaultChannel
from evennia.objects.objects import DefaultCharacter
from evennia.utils.ansi import strip_ansi
from evennia.utils.create import create_account, create_channel
from evennia.utils.test_resources import EvenniaCommandTest
from typeclasses.accounts import Account
from typeclasses.channels import Channel
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_social.commands import CmdIgnore, CmdPage


class SandboxSocialAccount(Account):
    pass


class SocialIdentitySeams(EvenniaCommandTest):
    account_typeclass = SandboxSocialAccount
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)

    def test_named_boundary_filters_real_host_post_chain_and_account_channel_receiver(self):
        self.account.permissions.clear()
        self.account.is_superuser = False
        for mode in ("account", "character"):
            with self.subTest(mode=mode), override_settings(EVENNIA_COMMS_IDENTITY=mode):
                channel = create_channel(
                    f"Social boundary {mode}",
                    typeclass=DefaultChannel if mode == "account" else Channel,
                )
                channel.send_to_online_only = False
                channel.connect(self.account2)
                self.call(CmdIgnore(), "/channels hide", caller=self.char2)
                self.call(CmdIgnore(), f"/except {self.char1.key}", caller=self.char2)
                with patch.object(DefaultCharacter, "msg") as sink:
                    self.char2.msg(("Room post", {"type": "ooc"}), from_obj=self.char1)
                self.assertIn("Room post", str(sink.call_args))
                with (
                    patch.object(self.account2, "msg") as hidden,
                    patch("evennia.utils.logger.log_file"),
                ):
                    channel.msg(
                        "Player channel line",
                        senders=[self.account if mode == "account" else self.char1],
                    )
                hidden.assert_not_called()
                with patch.object(self.char2, "msg") as hidden:
                    self.call(CmdPage(), f"{self.char2.key}=Blocked contact")
                hidden.assert_not_called()
                self.call(CmdIgnore(), self.char1.key, caller=self.char2)
                with patch.object(DefaultCharacter, "msg") as sink:
                    self.char2.msg(("Room post", {"type": "pose"}), from_obj=self.char1)
                self.assertIn("ignored player", str(sink.call_args))
                self.assertNotIn("Room post", str(sink.call_args))
                self.call(CmdIgnore(), "/clear", caller=self.char2)

    @override_settings(EVENNIA_COMMS_IDENTITY="character")
    def test_channel_preferences_through_host_mixins_and_real_ic_channel(self):
        from evennia_rptracker import channel_tracker
        from evennia_rptracker.typeclasses import ICChannel

        self.account.permissions.clear()
        self.account.is_superuser = False
        self.account2.permissions.clear()
        self.account2.is_superuser = False
        observer = create_account("UnaffectedChannelReader", None, "test-password")
        self.addCleanup(channel_tracker._active_channel_sessions.clear)
        self.addCleanup(channel_tracker._recent_speakers.clear)
        self.call(CmdIgnore(), self.char1.key, caller=self.char2)
        for typeclass in (Channel, ICChannel):
            channel = create_channel(f"Host {typeclass.__name__}", typeclass=typeclass)
            channel.send_to_online_only = False
            channel.connect(self.account2)
            channel.connect(observer)
            for preference in ("show", "hide"):
                self.call(CmdIgnore(), f"/channels {preference}", caller=self.account2)
                with (
                    patch.object(self.account2, "msg") as received,
                    patch.object(observer, "msg") as other,
                    patch("evennia.utils.logger.log_file") as history,
                ):
                    channel.msg("Private host channel content", senders=[self.char1])
                other.assert_called_once()
                self.assertIn("Private host channel content", str(other.call_args))
                self.assertIn("Private host channel content", str(history.call_args))
                if preference == "hide":
                    received.assert_not_called()
                else:
                    received.assert_called_once()
                    self.assertEqual(
                        strip_ansi(received.call_args.kwargs["text"][0]),
                        f"[{channel.key}] An ignored player said something.",
                    )
            self.call(CmdIgnore(), f"/except {self.char1.key}", caller=self.char2)
            with (
                patch.object(self.account2, "msg") as received,
                patch("evennia.utils.logger.log_file"),
            ):
                channel.msg("Excepted story content", senders=[self.char1])
            if typeclass is ICChannel:
                self.assertIn("Excepted story content", str(received.call_args))
            else:
                received.assert_not_called()
            self.call(CmdIgnore(), self.char1.key, caller=self.char2)

    @override_settings(EVENNIA_COMMS_IDENTITY="character")
    def test_visitor_can_page_staff_and_staff_can_reply_through_host_mixins(self):
        with patch.object(self.account2, "get_puppet", return_value=None):
            self.call(CmdPage(), f"{self.char1.key}=Host help", caller=self.account2)
        self.assertEqual(self.char1.last_pager_account, self.account2.pk)
        with patch.object(self.account2, "msg") as received:
            self.call(CmdPage(), "Host reply")
        self.assertIn("Host reply", str(received.call_args))
        self.assertNotIn(self.account.key, str(received.call_args))
