# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Named boundaries: levels, alt-safe replies, delivery and legacy protection."""

from unittest.mock import patch

from django.dispatch import Signal
from django.test import SimpleTestCase, override_settings
from evennia.accounts.accounts import DefaultAccount
from evennia.accounts.models import AccountDB
from evennia.comms.comms import DefaultChannel
from evennia.objects.objects import DefaultCharacter
from evennia.utils.create import create_account, create_channel, create_object

from evennia_links.ignoring import ignore_mode
from evennia_social import ignore
from evennia_social.commands import CmdIgnore, CmdJoin, CmdPage, CmdSummon
from evennia_social.commands.teleportation import _check_ignore_silent
from evennia_social.integrations import ignoring as ignore_integration
from evennia_social.tests.base import SocialCommandTestCase
from evennia_social.typeclasses import SocialAccountMixin


class SocialFilteringAccount(SocialAccountMixin, DefaultAccount):
    pass


class TestNamedIgnores(SocialCommandTestCase):
    account_typeclass = SocialFilteringAccount

    def setUp(self):
        super().setUp()
        self.account.permissions.clear()
        self.account.is_superuser = False
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.alt = create_object(type(self.char2), key="Alder", location=self.room1)
        self.account2.characters.add(self.alt)
        self.alt.account = self.account2
        self.stranger_account = create_account("UnrelatedAccount", None, "test-password")
        self.stranger = create_object(type(self.char2), key="Birch", location=self.room1)
        self.stranger.account = self.stranger_account
        self.stranger_account.characters.add(self.stranger)

    def test_levels_and_specific_entries_override_full_in_both_modes(self):
        for mode in ("account", "character"):
            with self.subTest(mode=mode), override_settings(EVENNIA_COMMS_IDENTITY=mode):
                ignore.clear(self.account)
                ignore.set_entry(self.char1, self.char2)
                self.assertEqual(ignore.ignore_level(self.char1, self.char2), ignore.HIDDEN)
                self.assertEqual(ignore.ignore_level(self.char1, self.alt), ignore.NONE)
                ignore.set_entry(self.char1, self.char2, ignore.FULL)
                self.assertEqual(ignore.ignore_level(self.char1, self.alt), ignore.HIDDEN)
                ignore.set_entry(self.char1, self.alt, ignore.POSTS)
                self.assertEqual(ignore.ignore_level(self.char1, self.alt), ignore.POSTS)
                ignore.set_entry(self.char1, self.alt)
                self.assertEqual(ignore.ignore_level(self.char1, self.alt), ignore.HIDDEN)
                ignore.remove_entry(self.char1, self.alt)
                self.assertEqual(ignore.ignore_level(self.char1, self.alt), ignore.HIDDEN)
                ignore.remove_entry(self.char1, self.char2)
                self.assertEqual(ignore.ignore_level(self.char1, self.alt), ignore.NONE)

    def test_add_except_and_remove_replies_do_not_depend_on_full_ownership(self):
        for mode in ("account", "character"):
            for switch in ("", "/except", "/remove"):
                with (
                    self.subTest(mode=mode, switch=switch),
                    override_settings(EVENNIA_COMMS_IDENTITY=mode),
                ):
                    ignore.clear(self.account)
                    ignore.set_entry(self.char1, self.char2, ignore.FULL)
                    outputs = []
                    for char in (self.alt, self.stranger):
                        output = self.call(CmdIgnore(), f"{switch} {char.key}".strip())
                        outputs.append(output.replace(char.key, "TARGET"))
                    self.assertEqual(*outputs)
                    self.assertEqual(
                        ignore.named_entry(self.account, self.char2)["level"], ignore.FULL
                    )

    @override_settings(EVENNIA_COMMS_IDENTITY="character")
    def test_list_names_only_entries_and_deleted_character_keeps_named_removal_history(self):
        self.call(CmdIgnore(), "/full Char2")
        shown = self.call(CmdIgnore(), "")
        self.assertIn("Char2 (full)", shown)
        for hidden in (self.alt.key, self.stranger.key, self.account2.key):
            self.assertNotIn(hidden, shown)
        self.call(CmdIgnore(), "/except Alder")
        self.assertIn("Alder (except)", self.call(CmdIgnore(), ""))
        self.alt.delete()
        self.assertIn("Alder (except)", self.call(CmdIgnore(), ""))
        self.call(CmdIgnore(), "/clear")
        self.assertEqual(ignore.entries(self.account), {})

    @override_settings(EVENNIA_COMMS_IDENTITY="account")
    def test_account_mode_also_lists_accounts_without_unnamed_alts(self):
        self.call(CmdIgnore(), "/full Char2")
        shown = self.call(CmdIgnore(), "")
        self.assertIn(self.account2.key, shown)
        self.assertNotIn(self.alt.key, shown)

    def test_earlier_full_ignores_survive_named_operations_and_clear_removes_them(self):
        self.account.db.ignore_list = [self.account2.pk]
        with override_settings(EVENNIA_COMMS_IDENTITY="character"):
            self.assertIn(
                "1 earlier full ignores, made before names were recorded",
                self.call(CmdIgnore(), ""),
            )
            self.assertIn("isn't on your list", self.call(CmdIgnore(), "/remove Alder"))
            ignore.set_entry(self.char1, self.alt, ignore.POSTS)
            self.assertEqual(ignore.ignore_level(self.char1, self.alt), ignore.POSTS)
            ignore.remove_entry(self.char1, self.alt)
            self.assertEqual(ignore.ignore_level(self.char1, self.alt), ignore.HIDDEN)
            self.assertEqual(self.account.db.ignore_list, [self.account2.pk])
            self.call(CmdIgnore(), "/clear")
            self.assertEqual(ignore.ignore_level(self.char1, self.alt), ignore.NONE)

    def test_offline_owner_and_staff_bypass(self):
        ignore.set_entry(self.char1, self.char2, ignore.FULL)
        self.char2.account = self.alt.account = None
        self.assertEqual(ignore.ignore_level(self.char1, self.alt), ignore.HIDDEN)
        self.account2.permissions.add("Builder")
        self.assertEqual(ignore.ignore_level(self.char1, self.alt), ignore.NONE)
        self.assertFalse(ignore.blocks_channel(self.char1, self.alt))

    def test_viewers_without_entries_skip_the_owner_sweep(self):
        # Every pose, say and channel line asks, once per listener.
        with patch("evennia_social.ignore.account_ids") as sweep:
            self.assertEqual(ignore.ignore_level(self.char1, self.char2), ignore.NONE)
            self.assertFalse(ignore.blocks_channel(self.char1, self.char2))
        sweep.assert_not_called()

    def test_posts_and_contact_delivery_for_each_level(self):
        for level in (ignore.HIDDEN, ignore.POSTS):
            ignore.set_entry(self.char1, self.char2, level)
            for kind in ("pose", "say", "ooc", "crafting_event", "whisper", "page"):
                with (
                    self.subTest(level=level, kind=kind),
                    patch.object(DefaultCharacter, "msg") as sink,
                ):
                    self.char1.msg(("Private content", {"type": kind}), from_obj=self.char2)
                    if kind in ("whisper", "page") or (
                        kind == "crafting_event" and level == ignore.HIDDEN
                    ):
                        sink.assert_not_called()
                    elif level == ignore.HIDDEN:
                        self.assertNotIn("Private content", str(sink.call_args))
                        self.assertIn("ignored player", str(sink.call_args))
                        self.assertEqual(sink.call_args.kwargs["text"][1]["type"], "system")
                    else:
                        self.assertIn("Private content", str(sink.call_args))
            self.assertTrue(_check_ignore_silent(self.char2, self.char1))
            with patch.object(self.char1, "msg") as received:
                self.call(CmdPage(), f"{self.char1.key}=Hidden page", caller=self.char2)
                received.assert_not_called()
            self.assertNotIn("Hidden page", self.call(CmdPage(), "/last"))
            self.assertNotIn("Hidden page", self.call(CmdPage(), "/recall"))
            # The sender's own history must not reveal the ignore.
            sent = self.call(CmdPage(), "/recall", caller=self.char2)
            self.assertIn(f"To {self.char1.key}: Hidden page", sent)

    def test_ooc_channels_filter_account_subscribers_without_aborting_other_receivers(self):
        ignore.set_channels_preference(self.account, "hide")
        channel = create_channel("Ignore seam", typeclass=DefaultChannel)
        channel.send_to_online_only = False
        channel.connect(self.account)
        channel.connect(self.stranger_account)
        for level in (ignore.HIDDEN, ignore.POSTS, ignore.FULL):
            ignore.set_entry(self.char1, self.char2, level)
            for sender in (self.char2, self.account2):
                with (
                    self.subTest(level=level, sender=sender),
                    patch.object(self.account, "msg") as hidden,
                    patch.object(self.stranger_account, "msg") as visible,
                    patch("evennia.utils.logger.log_file"),
                ):
                    channel.msg("Channel line", senders=[sender])
                    hidden.assert_not_called()
                    visible.assert_called_once()
        self.account2.permissions.add("Builder")
        with patch.object(self.account, "msg") as visible, patch("evennia.utils.logger.log_file"):
            channel.msg("Staff line", senders=[self.char2])
            visible.assert_called_once()

    def test_ignored_summon_and_join_leave_no_pending_contact_and_recheck_acceptance(self):
        self.char2.location = self.room2
        for command, accept in ((CmdSummon, "summon"), (CmdJoin, "join")):
            with self.subTest(command=accept):
                ignore.clear(self.char1)
                self.char1.pending_summon_requests = {}
                self.call(command(), self.char1.key, caller=self.char2)
                self.assertIn(self.char2.pk, self.char1.pending_summon_requests)
                ignore.set_entry(self.char1, self.char2, ignore.POSTS)
                self.assertNotIn(self.char2.key, self.call(command(), "/pending"))
                before = (self.char1.location, self.char2.location)
                self.call(command(), f"/accept {self.char2.key}", f"No pending {accept} request")
                self.assertEqual((self.char1.location, self.char2.location), before)
                self.char1.pending_summon_requests = {}
                self.call(command(), self.char1.key, caller=self.char2)
                self.assertFalse(self.char1.pending_summon_requests)

    def test_board_preference_persists_and_preserves_other_namespaced_keys(self):
        self.account.db.ignore_preferences = {"future": "kept", "channels": "hide"}
        self.assertEqual(ignore.boards_preference(self.account), "show")
        self.assertTrue(ignore.set_boards_preference(self.char1, "hide"))
        self.account.attributes.reset_cache()
        fresh = AccountDB.objects.get(pk=self.account.pk)
        stored = fresh.db.ignore_preferences
        self.assertEqual(stored["boards"], "hide")
        self.assertEqual(stored["channels"], "hide")
        self.assertEqual(stored["future"], "kept")
        self.assertEqual(ignore.boards_preference(fresh), "hide")
        self.assertEqual(ignore.boards_preference(self.char1), "hide")

    def test_board_preference_supports_account_without_characters(self):
        account = create_account("BoardOnlyAccount", None, "test-password")
        self.assertEqual(ignore.boards_preference(account), "show")
        command_output = self.call(CmdIgnore(), "/boards hide", caller=account)
        self.assertIn("will now be hidden", command_output)
        account.attributes.reset_cache()
        self.assertEqual(ignore.boards_preference(AccountDB.objects.get(pk=account.pk)), "hide")

    def test_links_provider_maps_show_to_placeholder_and_respects_shared_ignore_levels(self):
        from django.contrib.auth.models import AnonymousUser

        ignore.set_entry(self.char1, self.char2)
        self.assertEqual(ignore_mode(self.account, self.char2, "boards"), "placeholder")
        self.assertEqual(ignore_mode(self.account, self.char2, "channels"), "placeholder")
        with self.assertNoLogs("evennia", level="ERROR"):
            self.assertIsNone(ignore_mode(AnonymousUser(), self.char2, "boards"))
        ignore.set_boards_preference(self.account, "hide")
        self.assertEqual(ignore_mode(self.char1, self.char2, "boards"), "hide")
        ignore.set_entry(self.char1, self.char2, ignore.POSTS)
        self.assertIsNone(ignore_mode(self.account, self.char2, "boards"))

    def test_board_provider_staff_bypass_applies_to_reader_and_sender(self):
        ignore.set_entry(self.char1, self.char2)
        self.account.permissions.add("Builder")
        self.assertIsNone(ignore_mode(self.account, self.char2, "boards"))
        self.account.permissions.clear()
        self.account2.permissions.add("Builder")
        self.assertIsNone(ignore_mode(self.account, self.char2, "boards"))

    def test_boards_switch_handles_values_before_character_lookup(self):
        from evennia_social.commands import filtering

        with patch.object(filtering, "find_character") as lookup:
            shown = self.call(CmdIgnore(), "/boards show")
            self.assertIn("placeholders", shown)
            hidden = self.call(CmdIgnore(), "/boards hide")
            self.assertIn("will now be hidden", hidden)
            invalid = self.call(CmdIgnore(), "/boards unknown")
            self.assertIn("Usage: +ignore/boards hide or +ignore/boards show", invalid)
        lookup.assert_not_called()
        self.assertEqual(ignore.boards_preference(self.account), "hide")

    def test_policy_bookkeeping_failure_rolls_back_entry_and_command_is_generic(self):
        with patch("evennia_social.ignore.notify_ignore_policy_changing", side_effect=RuntimeError):
            with self.assertRaises(ignore.PolicyChangeError):
                ignore.set_entry(self.char1, self.char2)
            output = self.call(CmdIgnore(), self.char2.key)
        self.assertEqual(ignore.entries(self.account), {})
        self.assertIn("Please try again", output)

    def test_policy_prechange_sees_old_state_and_noops_do_not_notify(self):
        observed = []

        def inspect(viewer, kind=None):
            observed.append((kind, ignore.entries(viewer), ignore.boards_preference(viewer)))

        with patch("evennia_social.ignore.notify_ignore_policy_changing", side_effect=inspect):
            ignore.set_entry(self.char1, self.char2)
            ignore.set_entry(self.char1, self.char2)
            ignore.remove_entry(self.char1, self.char2)
            ignore.remove_entry(self.char1, self.char2)
            ignore.set_entry(self.char1, self.char2)
            ignore.clear(self.account)
            ignore.clear(self.account)
            ignore.set_boards_preference(self.account, "hide")
            ignore.set_boards_preference(self.account, "hide")
            ignore.set_boards_preference(self.account, "show")

        self.assertEqual(len(observed), 6)
        self.assertEqual(observed[0], (None, {}, "show"))
        self.assertEqual(observed[1][0], None)
        self.assertIn(self.char2.pk, observed[1][1])
        self.assertEqual(observed[2], (None, {}, "show"))
        self.assertEqual(observed[3][0], None)
        self.assertIn(self.char2.pk, observed[3][1])
        self.assertEqual(observed[4], ("boards", {}, "show"))
        self.assertEqual(observed[5], ("boards", {}, "hide"))


class TestIgnoreProviderRegistration(SimpleTestCase):
    def test_register_is_idempotent(self):
        signal = Signal()
        with patch.object(ignore_integration, "ignore_mode_requested", signal):
            ignore_integration.register()
            ignore_integration.register()
        self.assertEqual(len(signal.receivers), 1)
