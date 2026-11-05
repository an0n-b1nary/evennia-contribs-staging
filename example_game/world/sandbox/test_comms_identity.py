# SPDX-License-Identifier: BSD-3-Clause
"""Audit the shipped communication composition with real concurrent sessions."""

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import evennia
from commands.default_cmdsets import AccountCmdSet, CharacterCmdSet
from commands.guests import GuestAccountCmdSet
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.urls import reverse
from evennia.comms.models import Msg
from evennia.server.serversession import ServerSession
from evennia.utils.ansi import strip_ansi
from evennia.utils.create import create_account, create_channel, create_object
from evennia.utils.test_resources import EvenniaCommandTest
from typeclasses.accounts import Account
from typeclasses.channels import Channel
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_links.guests import welcome_channel
from evennia_links.identity import check_comms_identity


class TestCommunicationAudit(EvenniaCommandTest):
    account_typeclass = Account
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        self.account.key = "PrivateJuniperLogin"
        self.account2.key = "PrivateOrchidLogin"
        self.account.permissions.clear()
        self.char1.permissions.clear()
        self.char1.key = "Alder"
        self.char2.key = "Birch"
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.staff = create_account(
            "PrivateCedarLogin",
            None,
            "staff-audit-pass",
            typeclass=Account,
            permissions=["Builder"],
        )
        self.staff_char = create_object(Character, key="Steward", location=self.room1)
        self.staff.characters.add(self.staff_char)
        self.alt = create_object(Character, key="Willow", location=self.room1)
        self.account.characters.add(self.alt)
        for character, account in (
            (self.char1, self.account),
            (self.char2, self.account2),
            (self.alt, self.account),
            (self.staff_char, self.staff),
        ):
            character.locks.add(f"puppet:pid({account.pk});view:all()")
        self.other_sessions = []
        self.player2_session = self.login(self.account2, 2)
        self.staff_session = self.login(self.staff, 3)
        self.alt_session = self.login(self.account, 4)
        self.welcome = create_channel("Welcome", typeclass=Channel)
        self.welcome.tags.add("welcome", category="comms")
        self.public = create_channel("Public", typeclass=Channel)
        for channel in (self.welcome, self.public):
            for account in (self.account, self.account2, self.staff):
                channel.connect(account)

    def login(self, account, sessid):
        session = ServerSession()
        session.init_session("telnet", ("localhost", "audit"), evennia.SESSION_HANDLER)
        session.sessid = sessid
        evennia.SESSION_HANDLER[sessid] = session
        self.other_sessions.append(session)
        evennia.SESSION_HANDLER.login(session, account, testmode=True)
        return session

    def tearDown(self):
        for session in self.other_sessions:
            if session.puppet:
                session.account.unpuppet_object(session)
            evennia.SESSION_HANDLER.pop(session.sessid, None)
        if self.session.puppet:
            self.account.unpuppet_object(self.session)
        self.staff.delete()
        # Evennia's fixture restores its real disconnect before deleting accounts.
        # Remove any other account sessions retained by login hooks first.
        for session in list(evennia.SESSION_HANDLER.values()):
            if session.sessid != self.session.sessid and session.account in (
                self.account,
                self.account2,
            ):
                evennia.SESSION_HANDLER.pop(session.sessid, None)
        super().tearDown()

    def command(self, key, args, account, session, *, character=False):
        cmdset = CharacterCmdSet() if character else AccountCmdSet()
        command = cmdset.get(key)
        self.assertIsNotNone(command, key)
        self.assertTrue(command.access(session.get_puppet_or_account(), "cmd"), key)
        command.caller = session.get_puppet_or_account() if character else account
        command.account = account
        command.session = session
        command.args = args
        command.cmdname = command.cmdstring = command.raw_cmdname = key
        command.raw_string = f"{key} {args}"
        command.obj = command.caller
        if not command.at_pre_cmd():
            command.parse()
            command.func()
            command.at_post_cmd()

    def test_all_rendered_surfaces_hide_other_players_account_names(self):
        outputs = []

        def capture(text=None, *, viewer, **kwargs):
            if text is not None:
                outputs.append(
                    (strip_ansi(str(text[0] if isinstance(text, tuple) else text)), viewer)
                )

        with TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(override_settings(LOG_DIR=directory))
            from functools import partial

            for actor, viewer in (
                (self.account, self.account),
                (self.account2, self.account2),
                (self.char1, self.account),
                (self.char2, self.account2),
                (self.alt, self.account),
            ):
                stack.enter_context(
                    patch.object(actor, "msg", side_effect=partial(capture, viewer=viewer))
                )

            def log(message, filename="game.log"):
                path = Path(directory) / filename
                with path.open("a") as stream:
                    stream.write(f"2026-11-05 12:00:00 [-] {message}\n")

            def tail(filename, start=0, count=20, callback=None):
                path = Path(directory) / filename
                lines = path.read_text().splitlines(keepends=True) if path.exists() else []
                if callback:
                    callback(lines)
                return lines

            stack.enter_context(patch("evennia.utils.logger.log_file", side_effect=log))
            stack.enter_context(
                patch("evennia.commands.default.comms.tail_log_file", side_effect=tail)
            )
            stack.enter_context(
                patch("evennia.web.website.views.channels.tail_log_file", side_effect=tail)
            )
            # Both players and staff start at character select. The visitor's
            # sending session stays puppetless even when another session has an alt.
            self.command("who", "", self.account, self.session)
            self.command("welcome", "Visitor hello", self.account, self.session)
            self.assertIn("Newcomer: Visitor hello", "\n".join(text for text, _ in outputs))
            for key, args in (
                ("+ignore", "Birch"),
                ("+ignore", ""),
                ("+ignore", "/remove Birch"),
                ("@channel", "/who Welcome"),
                ("@channel", "/history Welcome"),
            ):
                self.command(key, args, self.account, self.session)

            self.command("@channel", "Public = Refused visitor line", self.account, self.session)
            self.assertFalse((Path(directory) / self.public.get_log_filename()).exists())
            self.command("page", "Birch=Refused visitor contact", self.account, self.session)
            self.assertFalse(Msg.objects.filter(db_message="Refused visitor contact").exists())
            self.staff.puppet_object(self.staff_session, self.staff_char)
            self.command("page", "Steward=Visitor help", self.account, self.session)
            self.assertEqual(self.staff_char.db.last_pager_account, self.account.pk)
            self.command("page", "Welcome aboard", self.staff, self.staff_session, character=True)
            self.assertIn("Steward pages: Welcome aboard", "\n".join(text for text, _ in outputs))
            self.account.puppet_object(self.session, self.char1)
            self.account.puppet_object(self.alt_session, self.alt)
            self.account2.puppet_object(self.player2_session, self.char2)
            self.command("who", "", self.account2, self.player2_session)
            self.assertIn("Alder", "\n".join(text for text, _ in outputs))
            self.assertIn("Willow", "\n".join(text for text, _ in outputs))
            self.command("@channel", "Public = Character hello", self.account, self.session)
            self.assertIn("Alder: Character hello", "\n".join(text for text, _ in outputs))
            self.command("@channel", "/who Public", self.account2, self.player2_session)
            self.command(
                "page", "Birch=Character contact", self.account, self.session, character=True
            )
            self.command(
                "page", "Character reply", self.account2, self.player2_session, character=True
            )
            self.command(
                "apage", f"{self.account2.key}=Account contact", self.staff, self.staff_session
            )
            self.staff.unpuppet_object(self.staff_session)
            self.command("page", "Staff reply", self.account2, self.player2_session, character=True)
            self.assertEqual(Msg.objects.get(db_message="Staff reply").receivers, [self.staff])
            self.command(
                "apage", f"{self.account2.key}=Puppetless staff", self.staff, self.staff_session
            )
            self.command(
                "page", "Puppetless reply", self.account2, self.player2_session, character=True
            )
            self.assertIn("Staff pages: Puppetless staff", "\n".join(text for text, _ in outputs))
            for key, args in (
                ("+ignore", "Alder"),
                ("+ignore", ""),
                ("+ignore", "/except Willow"),
                ("page", "/recall"),
            ):
                self.command(key, args, self.account2, self.player2_session, character=True)
            self.account.unpuppet_object(self.session)
            self.command("welcome", "Other session still plays Willow", self.account, self.session)
            self.command("who", "", self.account, self.session)
            for channel in (self.welcome, self.public):
                self.command(
                    "@channel", f"/history {channel.key}", self.account2, self.player2_session
                )
                response = self.client.get(
                    reverse("channel-detail", kwargs={"slug": channel.key.lower()})
                )
                self.assertEqual(response.status_code, 200)
                outputs.append((response.content.decode(), None))
            for character in (self.char1, self.char2, self.alt):
                from django.utils import timezone

                character.db.sandbox_last_seen = timezone.now()
            for viewer in (None, self.account, self.account2):
                if viewer:
                    self.client.force_login(viewer)
                else:
                    self.client.logout()
                response = self.client.get("/")
                self.assertEqual(response.status_code, 200)
                outputs.append((response.content.decode(), viewer))
            shown = "\n".join(text for text, _ in outputs)
            self.assertIn("Character hello", shown)
            self.assertIn("Visitors may", shown)
            self.assertIn("Staff reply", Msg.objects.get(db_message="Staff reply").message)
            # Self labels and the website's own account menu are allowed;
            # every rendered output is checked against all other accounts.
            for text, viewer in outputs:
                for account in (self.account, self.account2, self.staff):
                    if account != viewer:
                        self.assertNotIn(account.key, text)

    def test_startup_check_accepts_host_and_rejects_half_switched_mode(self):
        check_comms_identity()
        with (
            override_settings(EVENNIA_COMMS_IDENTITY="account"),
            self.assertRaisesMessage(ImproperlyConfigured, "requires 'character' mode"),
        ):
            check_comms_identity()

    def test_without_tracker_the_channel_command_keeps_session_visitor_policy(self):
        from django.apps import apps

        from evennia_links.commands import CmdSessionChannel

        installed = apps.is_installed
        self.account.puppet_object(self.alt_session, self.alt)
        with (
            patch(
                "commands.default_cmdsets.apps.is_installed",
                side_effect=lambda label: label != "evennia_rptracker" and installed(label),
            ),
            patch("evennia.utils.logger.log_file") as logged,
        ):
            self.assertIsInstance(AccountCmdSet().get("@channel"), CmdSessionChannel)
            check_comms_identity()
            self.command("@channel", "Public = Refused", self.account, self.session)
            logged.assert_not_called()

    def test_channel_account_moderation_is_staff_only_even_for_player_controlled_channels(self):
        from django.apps import apps

        installed = apps.is_installed
        self.public.locks.add(f"control:pid({self.account.pk})")
        self.public.ban(self.staff)
        for tracker in (True, False):
            with (
                self.subTest(tracker=tracker),
                patch(
                    "commands.default_cmdsets.apps.is_installed",
                    side_effect=lambda label, tracker=tracker: (
                        installed(label) if tracker or label != "evennia_rptracker" else False
                    ),
                ),
            ):
                channel_command = AccountCmdSet().get("@channel")
                self.assertFalse(channel_command.access(self.account, "admin"))
                self.assertTrue(channel_command.access(self.staff, "admin"))
                self.assertFalse(channel_command.access(self.account, "manage"))
                self.assertTrue(channel_command.access(self.staff, "manage"))
                with override_settings(EVENNIA_COMMS_IDENTITY="account"):
                    self.assertTrue(AccountCmdSet().get("@channel").access(self.account, "admin"))
                    self.assertTrue(AccountCmdSet().get("@channel").access(self.account, "manage"))
                for args in (
                    "/ban Public",
                    "/boot Public=Nobody",
                    "/unban Public=Nobody",
                    "/create Unsafe:evennia.comms.comms.DefaultChannel=An unsafe channel",
                ):
                    with (
                        patch.object(self.account, "search") as lookup,
                        patch.object(self.account, "msg") as output,
                    ):
                        self.command("@channel", args, self.account, self.session)
                    lookup.assert_not_called()
                    self.assertTrue(output.called)
                    self.assertNotIn(self.staff.key, str(output.call_args))
                    from evennia.comms.models import ChannelDB

                    self.assertFalse(ChannelDB.objects.filter(db_key="Unsafe").exists())

    def test_guest_account_surface_has_welcome_and_character_page(self):
        from commands.guests import CmdWelcome

        from evennia_social.commands import CmdPage

        self.assertIsInstance(GuestAccountCmdSet().get("welcome"), CmdWelcome)
        self.assertIsInstance(GuestAccountCmdSet().get("page"), CmdPage)
        self.assertIsNone(GuestAccountCmdSet().get("apage"))

    def test_new_accounts_join_welcome_once_and_can_leave(self):
        player = create_account("PrivateNewLogin", None, "new-audit-pass", typeclass=Account)
        self.assertTrue(welcome_channel().has_connection(player))
        self.welcome.disconnect(player)
        session = self.login(player, 5)
        self.assertFalse(self.welcome.has_connection(player))
        evennia.SESSION_HANDLER.pop(session.sessid)
        self.other_sessions.remove(session)
        player.delete()


class TestChannelLogCutover(EvenniaCommandTest):
    def test_archive_keeps_old_logs_private_and_reseed_preserves_new_history(self):
        from world.sandbox.management.commands.seed_sandbox import Command

        channel = create_channel("Guest", typeclass=Channel)
        channel.tags.add("chat", category="guest")
        channel.connect(self.account2)
        channel.add_user_channel_alias(self.account2, "greeting")
        command = Command()
        with TemporaryDirectory() as directory, override_settings(LOG_DIR=directory):
            log_dir = Path(directory)
            old_name = channel.get_log_filename()  # Prime Evennia's filename cache.
            old = log_dir / old_name
            old.write_text("PrivateOldLogin: before cutover\n")
            (log_dir / (old_name + ".1")).write_text("PrivateEarlierLogin: rotated\n")
            unrelated = log_dir / "server.log"
            unrelated.write_text("Keep server log\n")
            command._archive_channel_logs()
            command._create_guest_wing()
            command._archive_channel_logs()
            self.assertEqual(welcome_channel(), channel)
            self.assertEqual(channel.key, "Welcome")
            self.assertTrue(channel.has_connection(self.account2))
            self.assertEqual(self.account2.nicks.get("greeting", category="channel"), "welcome")
            self.assertEqual(
                self.account2.nicks.nickreplace(
                    "greeting hello", categories=("inputline",), include_account=False
                ),
                "@channel welcome = hello",
            )
            self.assertEqual(
                self.account2.nicks.nickreplace(
                    "guest hello", categories=("inputline",), include_account=False
                ),
                "guest hello",
            )
            self.assertFalse(old.exists())
            archived = list((log_dir / "account-history-archive").glob("*/*"))
            self.assertEqual(len(archived), 2)
            self.assertIn("PrivateOldLogin", "".join(path.read_text() for path in archived))
            self.assertEqual(unrelated.read_text(), "Keep server log\n")
            new_name = channel.get_log_filename()
            self.assertNotEqual(old_name, new_name)
            current = log_dir / new_name
            current.write_text("Alder: after cutover\n")
            command._archive_channel_logs()
            command._create_guest_wing()
            self.assertEqual(channel.get_log_filename(), new_name)
            self.assertEqual(current.read_text(), "Alder: after cutover\n")
            self.assertEqual(len(list((log_dir / "account-history-archive").glob("*/*"))), 2)

    def test_ic_logs_and_disabled_logging_are_preserved(self):
        from world.sandbox.management.commands.seed_sandbox import Command

        ic = create_channel("Existing IC", typeclass="evennia_rptracker.typeclasses.ICChannel")
        silent = create_channel("No history", typeclass=Channel)
        silent.log_file = ""
        silent._log_file = None
        with TemporaryDirectory() as directory, override_settings(LOG_DIR=directory):
            path = Path(directory) / ic.get_log_filename()
            path.write_text("Alder: existing IC history\n")
            Command()._archive_channel_logs()
            self.assertEqual(path.read_text(), "Alder: existing IC history\n")
            self.assertEqual(silent.get_log_filename(), "")

    def test_duplicate_welcome_tags_fail_without_renaming_channels(self):
        from django.core.management.base import CommandError

        from world.sandbox.management.commands.seed_sandbox import Command

        first = create_channel("Welcome one", typeclass=Channel)
        second = create_channel("Welcome two", typeclass=Channel)
        for channel in (first, second):
            channel.tags.add("welcome", category="comms")
        with self.assertRaisesMessage(CommandError, "Exactly one Welcome"):
            Command()._create_guest_wing()
        self.assertEqual(first.key, "Welcome one")
        self.assertEqual(second.key, "Welcome two")
