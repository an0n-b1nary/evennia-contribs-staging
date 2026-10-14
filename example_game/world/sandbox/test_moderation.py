"""Real command, authentication, rendered website and optional partner seams."""

from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.test import override_settings
from django.urls import reverse
from evennia.utils.create import create_channel
from evennia.utils.test_resources import EvenniaCommandTest
from typeclasses.accounts import Account
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_moderation import services
from evennia_moderation.commands import CmdAccountPage, CmdApply, CmdMute
from evennia_posing.commands import CmdEmit, CmdPose, CmdSemipose
from evennia_social.commands.finger import CmdFinger
from evennia_social.commands.messaging import CmdPage


class TestModerationSeams(EvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room
    account_typeclass = Account

    def setUp(self):
        super().setUp()
        self.char1.account = self.account
        self.char2.account = self.account2
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.account.is_superuser = True
        self.account.save()
        self.account2.is_superuser = False
        self.account2.permissions.clear()
        self.account2.permissions.add("Player")
        self.account2.save()
        self.room1.room_type = "ooc"
        self.char2.location = self.room1

    def mute(self):
        return services.restrict(
            self.char1, kind="mute", account=self.account2, reason="OOC disruption"
        )

    def test_room_commands_stop_before_delivery_and_ic_poses_continue(self):
        self.mute()
        for command in (CmdPose(), CmdSemipose(), CmdEmit()):
            self.call(command, "test speech", "You are muted", caller=self.char2)
        with patch.object(self.room1, "msg_contents") as send:
            self.char2.at_say("Direct speech")
            send.assert_not_called()
        self.room1.room_type = "ic"
        self.call(CmdPose(), "nods.", caller=self.char2)
        self.assertIn("nods", self.char2.last_pose_text)

    def test_pages_to_staff_remain_available_and_mixed_targets_are_atomic(self):
        from evennia.comms.models import Msg

        self.mute()
        page = CmdPage()
        page.caller = self.char2
        with patch.object(self.char1, "msg"):
            page._send_page(self.char2, [self.char1], "Staff, please help.")
        self.assertTrue(Msg.objects.filter(db_message="Staff, please help.").exists())
        page._send_page(self.char2, [self.char1, self.char2], "Mixed recipients")
        self.assertFalse(Msg.objects.filter(db_message="Mixed recipients").exists())

    def test_account_cmdset_replaces_stock_page_and_guest_surface_includes_apply(self):
        from commands.default_cmdsets import AccountCmdSet, CharacterCmdSet
        from commands.guests import GuestCharacterCmdSet

        self.assertIsInstance(AccountCmdSet().get("page"), CmdAccountPage)
        self.assertIsInstance(GuestCharacterCmdSet().get("+apply"), CmdApply)
        self.assertIsInstance(CharacterCmdSet().get("+mute"), CmdMute)
        self.assertEqual(CharacterCmdSet().get("+ignore").key, "+ignore")

    def test_capped_apply_counts_seats_with_host_guest_and_plural_staff(self):
        from commands.guests import GuestCharacterCmdSet
        from evennia.accounts.models import AccountDB
        from evennia.utils.create import create_account, create_object
        from typeclasses.accounts import Guest

        from evennia_links.guests import is_guest
        from evennia_moderation import admissions
        from evennia_moderation.policy import staff_account

        guest_account = create_account(
            "CapGuest", "", "temporary-passphrase-528", typeclass=Guest, permissions=["Guests"]
        )
        create_account("CapStaff", "", "temporary-passphrase-528", permissions=["Builders"])
        create_account("CapPlayer", "", "temporary-passphrase-528", permissions=["Player"])
        expected = sum(
            1
            for account in AccountDB.objects.all()
            if not is_guest(account) and not staff_account(account)
        )
        self.assertEqual(admissions.seat_count(), expected)
        guest = create_object(Character, key="Cap guest")
        guest.account = guest_account
        guest_account.characters.add(guest)
        guest.tags.add("character", category="guest")
        with override_settings(MODERATION_PLAYER_CAP=expected):
            self.call(
                GuestCharacterCmdSet().get("+apply"), "", "The game is at capacity", caller=guest
            )
        guest.delete()
        guest_account.delete()

    def test_staff_commands_are_listed_in_help_only_for_moderation_staff(self):
        from commands.default_cmdsets import CharacterCmdSet
        from evennia.commands.default.help import CmdHelp

        class PlainHelp(CmdHelp):
            help_more = False  # the pager would swallow the index in call()

        # The help index lists keys without their "+" prefix.
        staff_keys = {"softban", "mute", "notes", "admissions"}
        player = self.call(PlainHelp(), "", cmdset=CharacterCmdSet(), caller=self.char2).split()
        self.assertFalse(staff_keys & set(player))
        self.assertIn("apply", player)
        staff = self.call(PlainHelp(), "", cmdset=CharacterCmdSet(), caller=self.char1).split()
        self.assertTrue(staff_keys <= set(staff))

    def test_normal_and_ic_channels_block_mutes_without_recording_activity(self):
        self.mute()
        for typeclass in (
            "typeclasses.channels.Channel",
            "evennia_rptracker.typeclasses.ICChannel",
        ):
            channel = create_channel("Mute seam " + typeclass, typeclass=typeclass)
            with patch.object(channel, "at_post_msg") as post:
                channel.msg("Should be blocked", senders=self.account2)
                post.assert_not_called()

    def test_explicit_ooc_and_party_chat_are_blocked_even_in_ic_room(self):
        from evennia_rp_combat.data import CombatError
        from evennia_rp_party import services as party

        from evennia_social.commands.ooc import CmdOoc

        self.room1.room_type = "ic"
        self.mute()
        self.call(CmdOoc(), "A message", "You are muted", caller=self.char2)
        with self.assertRaisesMessage(CombatError, "You are muted"):
            party.chat(self.char2, "A message")

    def test_npc_portrayal_cannot_bypass_ooc_room_mute_and_staff_npc_marker_follows_controller(
        self,
    ):
        from evennia_npcs import services as npcs

        from evennia_social.identity import staff_run_marker

        blueprint = npcs.create_blueprint(self.char2, "Moderation NPC", "template")
        record = npcs.spawn(self.char2, blueprint)
        npc = npcs.control(self.char2, record)
        self.mute()
        with self.assertRaisesMessage(npcs.NPCError, "You are muted"):
            npcs.portray(self.char2, "Speaks in the lounge")
        self.room1.room_type = "ic"
        npcs.portray(self.char2, "Speaks in character")
        self.account2.permissions.add("Builder")
        self.assertIn("staff-run", staff_run_marker(npc))

    def test_board_command_and_web_post_and_edit_are_blocked(self):
        from evennia_boards.commands import CmdBoard
        from evennia_boards.models import Board, Post

        board = Board.objects.create(name="Mute seam board")
        post = Post.create_post(board, self.char2, "Before mute", "Original")
        self.mute()
        self.call(CmdBoard(), f"/post {board.name}=Blocked", "You are muted", caller=self.char2)
        with self.assertRaises(PermissionDenied):
            Post.create_post(board, self.char2, "After mute", "Blocked")
        self.client.force_login(self.account2)
        for route, kwargs in [
            ("post-create", {"pk": board.pk}),
            ("post-edit", {"pk": board.pk, "post_id": post.pk}),
        ]:
            response = self.client.post(
                reverse("evennia_boards:" + route, kwargs=kwargs),
                {"title": "Changed", "content": "Blocked"},
            )
            self.assertEqual(response.status_code, 403)
        post.refresh_from_db()
        self.assertEqual(post.content, "Original")

    def test_softban_refuses_real_game_account_authentication(self):
        self.account2.set_password("seam-password-397")
        self.account2.save()
        services.restrict(self.char1, kind="softban", account=self.account2, reason="Stop")
        account, errors = Account.authenticate(
            self.account2.key, "seam-password-397", ip="192.0.2.77"
        )
        self.assertIsNone(account)
        self.assertIn("banned until", errors[0])
        self.account2.username = "RenamedRestrictedPlayer"
        self.account2.save(update_fields=["username"])
        # Game-only hosts may keep the stock Django backend. The account mixin
        # must enforce account-ID bans independently of website configuration.
        for backend in (
            "evennia.web.utils.backends.CaseInsensitiveModelBackend",
            "evennia_moderation.auth.ModerationBackend",
        ):
            with override_settings(AUTHENTICATION_BACKENDS=[backend]):
                account, errors = Account.authenticate(
                    self.account2.key, "seam-password-397", ip="192.0.2.77"
                )
            self.assertIsNone(account)
            self.assertTrue(errors)

    def test_softban_refuses_existing_website_and_api_session(self):
        self.client.force_login(self.account2)
        services.restrict(self.char1, kind="softban", account=self.account2, reason="Stop")
        response = self.client.get(reverse("job-list"))
        self.assertEqual(response.status_code, 403)

    def test_staff_marker_reaches_profile_and_rendered_web_list_and_detail(self):
        self.account2.permissions.add("Builder")
        self.char2.account = None
        self.account2.db._quell = True
        self.assertIn("staff-run", CmdFinger._format_profile(self.char1, self.char2))
        self.client.force_login(self.account)
        response = self.client.get(reverse("characters"))
        self.assertContains(response, "staff-run")
        response = self.client.get(self.char2.web_get_detail_url())
        self.assertContains(response, "staff-run")

    def test_application_context_is_staff_only_and_web_decline_can_share_reason(self):
        from evennia.accounts.accounts import DefaultGuest
        from evennia.utils.create import create_account, create_object
        from evennia_jobs.review import review_fields

        from evennia_moderation import admissions
        from evennia_moderation.models import Notice

        guest_account = create_account(
            "ReviewGuest", "", "temporary-passphrase-941", typeclass=DefaultGuest
        )
        guest = create_object("typeclasses.characters.Character", key="Review guest")
        guest.account = guest_account
        guest_account.characters.add(guest)
        guest.tags.add("character", category="guest")
        code = admissions.issue_code(self.account2)
        application = admissions.submit_application(
            guest=guest,
            username="ReviewApplicant",
            password="new-passphrase-941",
            answers={"introduction": "A sample applicant", "conduct": True},
            address="192.0.2.13",
            code=code.code,
        )
        submission = application.job.submissions.get()
        self.assertEqual(review_fields(submission, self.char2), {})
        self.assertEqual(review_fields(submission, self.char1)["Connection address"], "192.0.2.13")
        self.client.force_login(self.account)
        response = self.client.get(reverse("job-request-review", kwargs={"pk": application.job_id}))
        self.assertContains(response, "192.0.2.13")
        self.assertContains(response, "Share the decline reason")
        response = self.client.post(
            reverse("job-request-review", kwargs={"pk": application.job_id}),
            {
                "revision": 1,
                "outcome": "declined",
                "reason": "Try again next wave",
                "share_decline_reason": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("Try again next wave", Notice.objects.get(account=self.account2).text)
        guest.delete()
        guest_account.delete()
