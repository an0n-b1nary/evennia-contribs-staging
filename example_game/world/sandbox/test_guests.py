"""Guest boundaries under the reference game's real contrib composition."""

from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from evennia.utils.create import create_account
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from typeclasses.accounts import Guest
from typeclasses.characters import Character
from typeclasses.rooms import Room


class GuestFixture:
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        self.guest = create_account(
            "Visitor", None, "test-password", typeclass=Guest, permissions=["Guests"]
        )
        self.account.characters.remove(self.char1)
        self.char1.account = self.guest
        self.guest.characters.add(self.char1)
        self.room1.tags.add("wing", category="guest")
        self.room1.tags.add("start", category="guest")
        self.room1.room_type = "ooc"
        self.char1.location = self.room1
        self.char2.location = self.room2


class TestGuestBoundaries(GuestFixture, EvenniaTest):
    def test_direct_move_cannot_escape_wing(self):
        self.assertFalse(self.char1.move_to(self.room2, quiet=True))
        self.assertEqual(self.char1.location, self.room1)

    def test_guest_is_not_a_reward_character(self):
        from evennia_links.characters import is_playable, playable_characters

        self.assertFalse(is_playable(self.char1))
        self.assertNotIn(self.char1, list(playable_characters()))

    def test_hookless_move_cannot_escape_and_internal_move_is_allowed(self):
        self.assertFalse(self.char1.move_to(self.room2, move_hooks=False))
        self.room2.tags.add("wing", category="guest")
        self.assertTrue(self.char1.move_to(self.room2, quiet=True))

    def test_ordinary_player_is_not_guest_despite_permission_hierarchy(self):
        from evennia_links.guests import is_guest

        self.assertFalse(is_guest(self.char2))
        self.assertTrue(self.char2.move_to(self.room1, quiet=True))

    def test_offline_guest_still_excluded(self):
        from evennia_links.characters import is_playable

        self.char1.account = None
        self.assertFalse(is_playable(self.char1))

    def test_room_and_channel_collectors_ignore_guests(self):
        from evennia_rptracker import tracker
        from evennia_rptracker.channel_tracker import eligible

        tracker._active_sessions.clear()
        self.addCleanup(tracker._active_sessions.clear)
        self.room1.room_type = "ic"  # Misconfiguration must not enroll guests.
        tracker.record_rp_activity(self.char1, self.room1)
        self.assertNotIn(self.char1.pk, tracker._active_sessions)
        self.assertFalse(eligible(self.char1))

    def test_guest_cannot_receive_items_or_trade_assets(self):
        from evennia_economy.assets import check
        from evennia_economy.services import EconomyError

        self.assertFalse(self.obj1.move_to(self.char1, quiet=True))
        with self.assertRaisesMessage(EconomyError, "Guests cannot exchange"):
            check(self.char2, self.char1, [])

    def test_guest_cannot_post_to_board(self):
        from django.core.exceptions import PermissionDenied
        from evennia_boards.models import Board, Post

        board = Board.objects.create(name="Guest boundary")
        with self.assertRaises(PermissionDenied):
            Post.create_post(board, self.char1, "title", "content")

    def test_trial_bypasses_approval_only_for_guest_in_wing_and_can_reset(self):
        from evennia_rp_chargen.models import CharacterBuild
        from evennia_rp_chargen.services import reset_trial
        from evennia_rp_chargen.subject import ChargenSubject

        from evennia_rp_rules.checks import CheckError
        from evennia_rp_rules.ruleset import get_ruleset

        stat = next(iter(get_ruleset().stats))
        build = CharacterBuild.objects.create(character=self.char1, status="finalized")
        with override_settings(RP_CHARGEN_REQUIRE_APPROVAL=True, RP_CHARGEN_GUEST_TRIALS=True):
            self.assertFalse(build.is_playable)
            self.assertIsNone(ChargenSubject(self.char1).get_rating(stat))
            self.char1.location = self.room2
            with self.assertRaises(CheckError):
                ChargenSubject(self.char1).get_rating(stat)
            self.char1.location = self.room1
            reset = reset_trial(self.char1)
            self.assertTrue(reset.is_draft)
            self.assertNotEqual(reset.pk, build.pk)
            with self.assertRaises(CheckError):
                ChargenSubject(self.char1).get_rating(stat)

    def test_guest_has_no_web_character_even_with_forced_login(self):
        from evennia_links.characters import web_character

        self.assertIsNone(web_character(self.guest))
        self.client.force_login(self.guest)
        response = self.client.get("/characters/manage/")
        self.assertEqual(response.status_code, 302)

    def test_trial_roll_has_no_durable_history_or_reward_signals(self):
        from evennia_rp_chargen.models import CharacterBuild
        from evennia_rp_chargen.stats import StatHandler
        from evennia_rp_contest import services, signals
        from evennia_rp_contest.models import CheckRecord
        from evennia_rp_contest.parsing import parse_test

        from evennia_rp_rules.ruleset import get_ruleset
        from evennia_rp_rules.signals import check_resolved

        stat = next(iter(get_ruleset().stats.values()))
        StatHandler(self.char1).set(stat, stat.scale.parse("B"))
        CharacterBuild.objects.create(character=self.char1, status="finalized")
        before = CheckRecord.objects.count()
        with (
            override_settings(RP_CHARGEN_REQUIRE_APPROVAL=True, RP_CHARGEN_GUEST_TRIALS=True),
            patch.object(signals.check_recorded, "send") as recorded,
            patch.object(check_resolved, "send") as resolved,
        ):
            record = services.perform_test(self.char1, parse_test(stat.key))
        self.assertIsNone(record.pk)
        self.assertEqual(CheckRecord.objects.count(), before)
        recorded.assert_not_called()
        resolved.assert_not_called()

    def test_public_directory_leaves_guest_out(self):
        self.client.force_login(self.account2)
        response = self.client.get(reverse("characters"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.char1, response.context["object_list"])
        response = self.client.get(
            reverse(
                "character-detail",
                kwargs={
                    "slug": self.char1.web_get_detail_url().split("/")[-3],
                    "pk": self.char1.pk,
                },
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_deleting_guest_removes_sheet_but_keeps_staff_request(self):
        from evennia_jobs.models import Job, JobType
        from evennia_rp_chargen.models import CharacterBuild

        job = Job.create_job(JobType.REQUEST, self.char1, "Guest question", "Help")
        CharacterBuild.objects.create(character=self.char1)
        character_id = self.char1.pk
        self.guest.at_post_disconnect()
        self.assertFalse(CharacterBuild.objects.filter(character_id=character_id).exists())
        job.refresh_from_db()
        self.assertIsNone(job.author_id)
        self.assertEqual(job.author_name, "Char")


class TestGuestCommands(GuestFixture, EvenniaCommandTest):
    def test_connected_guest_is_marked_and_located_in_both_where_layouts(self):
        from evennia_social.commands import CmdWhere

        self.assertIn("(guest)", self.guest.get_display_name(self.account2))
        for screenreader in (False, True):
            with (
                patch(
                    "evennia_social.commands.discovery.get_connected_characters",
                    return_value=[self.char1],
                ),
                patch(
                    "evennia_social.commands.discovery.uses_screenreader", return_value=screenreader
                ),
            ):
                output = self.call(CmdWhere(), "", caller=self.char2)
            self.assertIn("(guest)", output)
            self.assertIn(self.room1.key, output)

    def test_page_to_player_refused_before_creating_message(self):
        from evennia.comms.models import Msg

        from evennia_social.commands import CmdPage

        self.account2.permissions.clear()
        self.account2.permissions.add("Player")
        self.char2.permissions.clear()
        before = Msg.objects.count()
        self.assertIn("staff", self.call(CmdPage(), f"{self.char2.key}=hello"))
        self.assertEqual(Msg.objects.count(), before)

    @override_settings(OOC_ROOM_DBREF="#999999")
    def test_ooc_returns_guest_to_guest_lounge(self):
        from evennia_social.commands import CmdOocTeleport

        self.call(CmdOocTeleport(), "")
        self.assertEqual(self.char1.location, self.room1)

    def test_page_to_staff_allowed_including_offline_staff(self):
        from evennia_social.commands import CmdPage

        self.account2.characters.add(self.char2)
        self.account2.permissions.add("Builder")
        self.char2.account = None
        self.assertIn("You paged", self.call(CmdPage(), f"{self.char2.key}=hello"))

    def test_home_ignores_non_guest_personal_home(self):
        from evennia_social.commands import CmdHome

        self.char1.home_room = self.room2.pk
        self.call(CmdHome(), "")
        self.assertEqual(self.char1.location, self.room1)

    def test_summon_and_join_cannot_move_guest_outside(self):
        from evennia_social.commands import CmdJoin, CmdSummon

        self.call(CmdSummon(), self.char1.key, caller=self.char2)
        self.call(CmdSummon(), f"/accept {self.char2.key}")
        self.assertEqual(self.char1.location, self.room1)
        self.call(CmdJoin(), self.char2.key)
        self.call(CmdJoin(), f"/accept {self.char1.key}", caller=self.char2)
        self.assertEqual(self.char1.location, self.room1)

    def test_teleport_of_guest_by_staff_is_guarded(self):
        from evennia_social.commands import CmdTel

        self.char2.permissions.add("Builder")
        self.call(CmdTel(), f"{self.char1.key}={self.room2.key}", caller=self.char2)
        self.assertEqual(self.char1.location, self.room1)

    def test_restricted_cmdset_preserves_trials_and_excludes_shared_writes(self):
        from commands.guests import GuestAccountCmdSet, GuestCharacterCmdSet

        commands = GuestCharacterCmdSet()
        keys = {command.key for command in commands.commands}
        self.assertTrue({"+stats", "+test", "+request", "+bug", "page", "guest"} <= keys)
        self.assertFalse(
            {"+sandbox", "+bb", "give", "get", "+scene", "+craft", "+summon", "+join", "channel"}
            & keys
        )
        self.assertNotIn("ic", {c.key for c in GuestAccountCmdSet().commands})

    def test_guest_private_request_cannot_start_player_questionnaire(self):
        from evennia_jobs.commands import CmdRequest

        self.assertIn("plain private requests", self.call(CmdRequest(), "/form building=Hello"))

    def test_guest_chat_honours_channel_ban(self):
        from commands.guests import CmdGuestChat
        from evennia.utils.create import create_channel

        channel = create_channel("Guest Test")
        channel.tags.add("chat", category="guest")
        channel.connect(self.guest)
        channel.ban(self.guest)
        self.assertIn("cannot speak", self.call(CmdGuestChat(), "hello"))


class TestGuestSeed(EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def test_guest_login_uses_seeded_wing_and_only_guest_channel(self):
        from django.core.management import call_command
        from evennia.comms.models import ChannelDB

        from evennia_links.guests import guest_start

        call_command("seed_sandbox", verbosity=0)
        start = guest_start()
        from commands.sandbox import _stray_rooms

        self.assertNotIn(start, _stray_rooms())
        with override_settings(GUEST_LIST=["TrialVisitor"]):
            guest, errors = Guest.authenticate()
        self.assertEqual(errors, [])
        self.assertIsNotNone(guest)
        self.addCleanup(lambda: guest.delete() if guest.pk else None)
        character = guest.characters.all()[0]
        self.assertEqual(character.location, start)
        self.assertEqual(character.home, start)
        with patch.object(guest, "puppet_object") as puppet:
            guest.at_post_login(session=self.session)
        puppet.assert_called_once_with(self.session, character)
        subscriptions = list(ChannelDB.objects.get_subscriptions(guest))
        self.assertEqual(len(subscriptions), 1)
        self.assertTrue(subscriptions[0].tags.has("chat", category="guest"))

    def test_guest_login_before_seed_fails_without_consuming_slot(self):
        from evennia.accounts.models import AccountDB

        before = AccountDB.objects.count()
        guest, errors = Guest.authenticate()
        self.assertIsNone(guest)
        self.assertTrue(errors)
        self.assertEqual(before, AccountDB.objects.count())
