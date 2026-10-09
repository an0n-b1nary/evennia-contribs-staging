"""Channel collection under the actual reference-game partners."""

from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from evennia.utils.create import create_channel
from evennia.utils.test_resources import EvenniaTest
from evennia_rptracker import channel_tracker, tracker
from evennia_rptracker.models import RPSession, RPSessionSceneLink
from typeclasses.characters import Character
from typeclasses.rooms import Room


class ChannelSeams(EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        tracker._active_sessions.clear()
        channel_tracker._active_channel_sessions.clear()
        channel_tracker._recent_speakers.clear()
        self.addCleanup(tracker._active_sessions.clear)
        self.addCleanup(channel_tracker._active_channel_sessions.clear)
        self.addCleanup(channel_tracker._recent_speakers.clear)
        self.char1.db_account = self.account
        self.char2.db_account = self.account2
        self.char1.save()
        self.char2.save()
        self.channel = create_channel(
            "Reference IC", typeclass="evennia_rptracker.typeclasses.ICChannel"
        )

    def test_channel_sessions_preserve_room_state_and_have_no_scene_links(self):
        from evennia_rp_chargen import locks
        from evennia_rp_chargen.models import CharacterBuild

        CharacterBuild.objects.create(character=self.char1, status="finalized")
        locks.note_ic_action(self.char1)
        self.char1.last_pose_time = 123
        self.char2.last_pose_time = 456
        now = timezone.now().timestamp()
        for offset in (0, 1200, 1800):
            with patch("time.time", return_value=now + offset):
                for character in (self.char1, self.char2, self.char1, self.char2):
                    channel_tracker.record_rp_channel_activity(character, self.channel)
        self.char1.at_post_unpuppet(account=self.account)
        self.assertTrue(locks.is_locked(self.char1))
        self.assertEqual(RPSession.objects.get(character=self.char1).status, "completed")
        self.assertFalse(RPSessionSceneLink.objects.exists())
        self.assertEqual(self.char2.last_pose_time, 456)

    def test_seed_and_report_commands_are_wired(self):
        from commands.default_cmdsets import AccountCmdSet, CharacterCmdSet

        self.assertIn("+report", {command.key for command in CharacterCmdSet().commands})
        commands = {command.key: command for command in AccountCmdSet().commands}
        self.assertEqual(commands["@channel"].__class__.__name__, "CmdICChannel")

    def completed_sessions(self, end):
        """One eligible hour-long room session and one channel session ending at *end*."""
        sessions = []
        for source in ("rp_session", "rp_channel_session"):
            session = RPSession.objects.create(
                character=self.char1,
                character_name=self.char1.key,
                source_type=source,
                channel=self.channel if source == "rp_channel_session" else None,
                room=self.room1 if source == "rp_session" else None,
                status="completed",
                activated_at=end - timedelta(hours=1),
                ended_at=end,
                last_activity_at=end,
            )
            session.partners.create(partner=self.char2, partner_name=self.char2.key)
            sessions.append(session)
        return sessions

    def test_room_and_channel_collectors_resolve_distinct_ledger_sources(self):
        from django.conf import settings

        from evennia_links import resolve_dotted

        now = timezone.now()
        self.completed_sessions(now - timedelta(hours=1))
        awards = [
            award
            for source, dotted in settings.XP_COLLECTORS
            if source in ("rp_session", "rp_channel_session")
            for award in resolve_dotted(dotted)(now)
        ]
        self.assertTrue(
            {"rp_session", "rp_channel_session"} <= {award.source_type for award in awards}
        )

    def test_weekly_batch_awards_each_source_once_and_flags_both(self):
        from evennia_xp.batch import _window_end_from_week_str, run_weekly_batch
        from evennia_xp.models import XPLog
        from evennia_xp.projection import project_for_character

        week = "2026-W40"
        window_end = _window_end_from_week_str(week)
        sessions = self.completed_sessions(window_end - timedelta(days=3))
        projected = project_for_character(self.char1.pk, window_end).by_source
        self.assertGreater(projected["rp_session"], 0)
        self.assertGreater(projected["rp_channel_session"], 0)

        run_weekly_batch(week)
        ledger = XPLog.objects.filter(character_id=self.char1.pk)
        self.assertEqual(
            sorted(ledger.values_list("source_type", "source_ref_id")),
            sorted((s.source_type, s.pk) for s in sessions),
        )
        for session in sessions:
            session.refresh_from_db()
            self.assertEqual((session.xp_awarded, session.xp_week), (True, week))

        self.assertEqual(run_weekly_batch(week).total_awards, 0)
        self.assertEqual(ledger.count(), 2)
        self.assertEqual(project_for_character(self.char1.pk, window_end).total, 0)
