# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Channel presentation with stock channels and real subscriber delivery."""

from unittest.mock import patch

from django.dispatch import Signal
from django.test import override_settings
from evennia.accounts.accounts import DefaultAccount
from evennia.accounts.models import AccountDB
from evennia.comms.comms import DefaultChannel
from evennia.utils.ansi import strip_ansi
from evennia.utils.create import create_account, create_channel, create_object

from evennia_links.ignoring import ignore_mode
from evennia_social import ignore
from evennia_social.commands import CmdIgnore
from evennia_social.tests.base import SocialCommandTestCase, SocialTestCharacter
from evennia_social.typeclasses import SocialAccountMixin


class ChannelFilteringAccount(SocialAccountMixin, DefaultAccount):
    pass


class StockICChannel(DefaultChannel):
    """IC marker alone: Social must not require an IC-channel contrib."""

    is_ic = True


class CharacterChannelReceiver:
    """A host's opt-in character receive hooks, absent from DefaultCharacter."""

    at_pre_channel_msg = DefaultAccount.at_pre_channel_msg
    channel_msg = DefaultAccount.channel_msg
    at_post_channel_msg = DefaultAccount.at_post_channel_msg


class ChannelFilteringCharacter(SocialTestCharacter, CharacterChannelReceiver):
    pass


class TestChannelIgnores(SocialCommandTestCase):
    account_typeclass = ChannelFilteringAccount
    character_typeclass = ChannelFilteringCharacter

    def setUp(self):
        super().setUp()
        self.account.is_superuser = False
        self.account.permissions.clear()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.observer = create_account("ChannelObserver", None, "test-password")
        self.ooc = create_channel("Ordinary", typeclass=DefaultChannel)
        self.ic = create_channel("Story", typeclass=StockICChannel)
        for channel in (self.ooc, self.ic):
            channel.send_to_online_only = False
            channel.connect(self.account)
            channel.connect(self.observer)
        self.enterContext(patch("evennia.utils.logger.log_file"))

    def send(self, channel, senders, text="Private channel content", viewer=None, **kwargs):
        viewer = viewer or self.account
        with patch.object(viewer, "msg") as received, patch.object(self.observer, "msg") as other:
            channel.msg(text, senders=senders, **kwargs)
        other.assert_called_once()
        self.assertIn(text, str(other.call_args))
        return received

    def assert_placeholder(self, received, channel):
        received.assert_called_once()
        message = strip_ansi(received.call_args.kwargs["text"][0])
        self.assertEqual(message, f"[{channel.key}] An ignored player said something.")
        self.assertNotIn(self.char2.key, message)
        self.assertNotIn(self.account2.key, message)
        self.assertEqual(received.call_args.kwargs["from_obj"], [])

    def test_default_placeholder_and_hide_cover_account_and_character_senders_in_both_modes(self):
        ignore.set_entry(self.account, self.char2, ignore.FULL)
        for mode in ("account", "character"):
            with override_settings(EVENNIA_COMMS_IDENTITY=mode):
                for channel in (self.ooc, self.ic):
                    for sender in (self.account2, self.char2):
                        with self.subTest(mode=mode, channel=channel.key, sender=sender):
                            ignore.set_channels_preference(self.account, "show")
                            self.assert_placeholder(self.send(channel, [sender]), channel)
                            ignore.set_channels_preference(self.account, "hide")
                            self.send(channel, [sender]).assert_not_called()

    def test_exception_shows_ic_posts_but_ooc_uses_player_boundary(self):
        alt = create_object(type(self.char2), key="ChannelAlt", location=self.room1)
        self.account2.characters.add(alt)
        alt.account = self.account2
        ignore.set_entry(self.account, self.char2, ignore.FULL)
        ignore.set_entry(self.account, alt, ignore.POSTS)
        for preference in ("show", "hide"):
            ignore.set_channels_preference(self.account, preference)
            self.assertIn("Private channel content", str(self.send(self.ic, [alt]).call_args))
            received = self.send(self.ooc, [alt])
            if preference == "hide":
                received.assert_not_called()
            else:
                self.assert_placeholder(received, self.ooc)
        ignore.set_entry(self.account, alt)
        self.send(self.ic, [alt]).assert_not_called()

    def test_character_ignore_does_not_hide_unlisted_alts_on_ic_channels(self):
        alt = create_object(type(self.char2), key="OtherStoryCharacter", location=self.room1)
        self.account2.characters.add(alt)
        alt.account = self.account2
        ignore.set_entry(self.account, self.char2)
        self.assert_placeholder(self.send(self.ic, [self.char2]), self.ic)
        self.assertIn("Private channel content", str(self.send(self.ic, [alt]).call_args))
        self.assert_placeholder(self.send(self.ooc, [alt]), self.ooc)

    def test_puppeted_npc_is_covered_without_playable_membership(self):
        npc = create_object(type(self.char2), key="UnlistedNPC", location=self.room1)
        npc.account = self.account2
        self.assertNotIn(npc, self.account2.characters.all())
        ignore.set_entry(self.account, self.char2, ignore.FULL)
        for channel in (self.ooc, self.ic):
            self.assert_placeholder(self.send(channel, [npc]), channel)
            ignore.set_channels_preference(self.account, "hide")
            self.send(channel, [npc]).assert_not_called()
            ignore.set_channels_preference(self.account, "show")
        self.account2.permissions.add("Builder")
        self.assertIn("Private channel content", str(self.send(self.ic, [npc]).call_args))

    def test_staff_sender_and_reader_bypass_both_presentations(self):
        ignore.set_entry(self.account, self.char2, ignore.FULL)
        for preference in ("show", "hide"):
            ignore.set_channels_preference(self.account, preference)
            for staff in (self.account, self.account2):
                staff.permissions.add("Builder")
                for channel in (self.ooc, self.ic):
                    for sender in (self.account2, self.char2):
                        self.assertIn(
                            "Private channel content", str(self.send(channel, [sender]).call_args)
                        )
                staff.permissions.clear()

    def test_direct_character_subscribers_share_account_preference(self):
        ignore.set_entry(self.account, self.char2, ignore.FULL)
        for channel in (self.ooc, self.ic):
            channel.disconnect(self.account)
            channel.connect(self.char1)
            self.assert_placeholder(self.send(channel, [self.char2], viewer=self.char1), channel)
            ignore.set_channels_preference(self.account, "hide")
            self.send(channel, [self.char2], viewer=self.char1).assert_not_called()
            ignore.set_channels_preference(self.account, "show")

    def test_system_lines_unignored_senders_and_multi_sender_lines(self):
        ignore.set_entry(self.account, self.char2, ignore.FULL)
        self.assertIn("Private channel content", str(self.send(self.ooc, []).call_args))
        self.assertIn(
            "Private channel content", str(self.send(self.ooc, [self.observer]).call_args)
        )
        self.assert_placeholder(self.send(self.ooc, [self.observer, self.char2]), self.ooc)
        ignore.set_channels_preference(self.account, "hide")
        self.send(self.ooc, [self.observer, self.char2]).assert_not_called()

    def test_absent_or_broken_provider_leaves_content_visible(self):
        ignore.set_entry(self.account, self.char2, ignore.FULL)
        for result in (None, RuntimeError("unavailable"), "invalid"):
            signal = Signal()

            def provider(sender, result=result, **kwargs):
                if isinstance(result, Exception):
                    raise result
                return result

            if result is not None:
                signal.connect(provider, weak=False)
            with patch("evennia_links.ignoring.ignore_mode_requested", signal):
                for channel in (self.ooc, self.ic):
                    self.assertIn(
                        "Private channel content", str(self.send(channel, [self.char2]).call_args)
                    )

    def test_channel_preferences_are_account_shared_and_preserve_boards_and_other_keys(self):
        self.account.db.ignore_preferences = {"boards": "hide", "future": "kept"}
        self.assertEqual(ignore.channels_preference(self.account), "show")
        self.assertTrue(ignore.set_channels_preference(self.char1, "hide"))
        self.account.attributes.reset_cache()
        fresh = AccountDB.objects.get(pk=self.account.pk)
        self.assertEqual(ignore.channels_preference(fresh), "hide")
        self.assertEqual(ignore.boards_preference(fresh), "hide")
        self.assertEqual(fresh.db.ignore_preferences["future"], "kept")
        self.account.db.ignore_preferences = {"channels": "invalid"}
        self.assertEqual(ignore.channels_preference(self.char1), "show")
        with self.assertRaises(ValueError):
            ignore.set_channels_preference(self.account, "invalid")

    def test_channel_switch_works_before_character_lookup_and_without_a_character(self):
        from evennia_social.commands import filtering

        account = create_account("ChannelOnlyAccount", None, "test-password")
        with patch.object(filtering, "find_character") as lookup:
            for value, expected in (
                ("show", "already set to show placeholders"),
                ("hide", "will now be hidden"),
                ("hide", "already set to hide"),
                ("show", "will now use placeholders"),
                ("unknown", "Usage: +ignore/channels hide or +ignore/channels show"),
            ):
                self.assertIn(
                    expected, self.call(CmdIgnore(), f"/channels {value}", caller=account)
                )
        lookup.assert_not_called()
        self.assertEqual(ignore.channels_preference(account), "show")

    def test_channel_policy_notifications_are_scoped_and_failure_rolls_back(self):
        observed = []

        def inspect(viewer, kind=None):
            observed.append((kind, ignore.channels_preference(viewer)))

        with patch("evennia_social.ignore.notify_ignore_policy_changing", side_effect=inspect):
            ignore.set_channels_preference(self.account, "hide")
            ignore.set_channels_preference(self.account, "hide")
            ignore.set_channels_preference(self.account, "show")
        self.assertEqual(observed, [("channels", "show"), ("channels", "hide")])
        with patch("evennia_social.ignore.notify_ignore_policy_changing", side_effect=RuntimeError):
            self.assertIn("Please try again", self.call(CmdIgnore(), "/channels hide"))
        self.assertEqual(ignore.channels_preference(self.account), "show")

    def test_links_provider_distinguishes_ic_and_ooc_and_ignores_unknown_kinds(self):
        ignore.set_entry(self.account, self.char2, ignore.POSTS)
        self.assertEqual(ignore_mode(self.account, self.char2, "channels"), "placeholder")
        self.assertIsNone(ignore_mode(self.account, self.char2, "ic_channels"))
        self.assertIsNone(ignore_mode(self.account, self.char2, "unknown"))
        ignore.set_channels_preference(self.account, "hide")
        self.assertEqual(ignore_mode(self.account, self.account2, "channels"), "hide")
