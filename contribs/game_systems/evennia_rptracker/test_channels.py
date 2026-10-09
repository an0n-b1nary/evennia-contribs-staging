# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Channel collection must work through the public entry point."""

from datetime import timedelta
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from django.utils import timezone
from evennia.utils.create import create_channel
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_rptracker import channel_tracker, tracker
from evennia_rptracker.models import RPSession


class ChannelCollectionTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        tracker._active_sessions.clear()
        channel_tracker._active_channel_sessions.clear()
        channel_tracker._recent_speakers.clear()
        self.addCleanup(tracker._active_sessions.clear)
        self.addCleanup(channel_tracker._active_channel_sessions.clear)
        self.addCleanup(channel_tracker._recent_speakers.clear)
        self.channel = create_channel(
            "IC test", typeclass="evennia_rptracker.typeclasses.ICChannel"
        )
        self.char1.db_account = self.account
        self.char2.db_account = self.account2
        self.char1.save()
        self.char2.save()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.start = timezone.now().timestamp()

    def say(self, character, seconds=0, channel=None):
        with patch("time.time", return_value=self.start + seconds):
            tracker.record_rp_channel_activity(character, channel or self.channel)

    def exchange(self, seconds=0):
        for character in (self.char1, self.char2, self.char1, self.char2):
            self.say(character, seconds)

    def tracked_session(self, character=None):
        return RPSession.objects.get(
            character=character or self.char1, source_type="rp_channel_session"
        )

    def test_channel_seam_activates_exchanging_speakers(self):
        with patch("time.time", return_value=1_800_000_000):
            tracker.record_rp_channel_activity(self.char1, self.channel)
            tracker.record_rp_channel_activity(self.char2, self.channel)
            tracker.record_rp_channel_activity(self.char1, self.channel)
            tracker.record_rp_channel_activity(self.char2, self.channel)
        self.assertEqual(RPSession.objects.filter(status="active").count(), 2)

    def test_solo_subscribers_and_npcs_supply_no_partner(self):
        self.channel.connect(self.account2)
        self.say(self.char1)
        self.say(self.char1, 10)
        self.char2.tags.add("npc", category="npc_system")
        self.say(self.char2, 11)
        self.say(self.char1, 12)
        self.assertFalse(RPSession.objects.exists())

    def test_same_account_and_shared_playable_membership_supply_no_partner(self):
        self.account.characters.add(self.char2)
        self.exchange()
        self.assertFalse(RPSession.objects.exists())

    def test_policy_applies_to_direct_collection_and_recent_partners(self):
        with override_settings(RPTRACKER_CHANNEL_ELIGIBLE=lambda c: c.pk == self.char1.pk):
            self.exchange()
        self.assertFalse(RPSession.objects.exists())

    def test_policy_failure_fails_closed(self):
        with override_settings(RPTRACKER_CHANNEL_ELIGIBLE="missing.module.hook"):
            self.assertFalse(channel_tracker.eligible(self.char1))

    def test_two_messages_and_partner_are_required_for_each_speaker(self):
        self.say(self.char1)
        self.say(self.char2)
        self.assertFalse(RPSession.objects.exists())
        self.say(self.char1, 10)
        self.assertEqual(RPSession.objects.count(), 1)
        self.assertEqual(self.tracked_session().pose_count, 2)
        self.assertEqual(self.tracked_session().partners.get().partner_id, self.char2.pk)

    def test_idle_boundary_expires_before_new_message(self):
        self.exchange()
        old = self.tracked_session()
        self.say(self.char1, 1800)
        old.refresh_from_db()
        self.assertEqual(old.status, "completed")
        self.assertEqual(old.duration_seconds(), 0)
        self.assertEqual(
            channel_tracker._active_channel_sessions[(self.char1.pk, self.channel.pk)]["status"],
            "pending",
        )

    def test_idle_wait_does_not_make_short_exchange_eligible(self):
        self.exchange()
        self.exchange(60)
        with patch("time.time", return_value=self.start + 2000):
            tracker._check_idle_sessions()
        session = self.tracked_session()
        self.assertEqual(session.duration_seconds(), 60)
        self.assertFalse(session.is_xp_eligible())

    def test_long_exchange_is_eligible_and_counts_all_messages(self):
        self.exchange()
        for seconds in (600, 1200, 1800):
            self.exchange(seconds)
        channel_tracker.end_channel_session(self.char1.pk, self.channel.pk)
        session = self.tracked_session()
        self.assertEqual(session.duration_seconds(), 1800)
        self.assertEqual(session.pose_count, 8)
        self.assertTrue(session.is_xp_eligible())

    def test_no_recent_partner_closes_session_without_solo_extension(self):
        self.exchange()
        self.say(self.char1, 1000)
        self.say(self.char1, 1801)
        session = self.tracked_session()
        self.assertEqual(session.status, "completed")
        self.assertEqual(session.duration_seconds(), 1000)

    def test_room_and_channel_state_are_independent(self):
        tracker._active_sessions[self.char1.pk] = {
            "status": "pending",
            "session_id": None,
            "room_id": self.room1.pk,
        }
        self.char1.last_pose_time = 123
        self.exchange()
        channel_tracker.end_channel_session(self.char1.pk, self.channel.pk)
        self.assertIn(self.char1.pk, tracker._active_sessions)
        self.assertEqual(self.char1.last_pose_time, 123)

    def test_channel_signals_never_emit_room_signals(self):
        from evennia_rptracker import signals

        with (
            patch.object(signals.rp_session_started, "send") as started,
            patch.object(signals.rp_session_ended, "send") as ended,
            patch.object(signals.rp_activity_recorded, "send") as activity,
        ):
            self.exchange()
            channel_tracker.end_channel_session(self.char1.pk, self.channel.pk)
        started.assert_not_called()
        ended.assert_not_called()
        activity.assert_not_called()

    def test_leave_and_delete_close_sessions_and_preserve_names(self):
        self.channel.connect(self.account)
        self.exchange()
        self.channel.disconnect(self.account)
        self.assertEqual(self.tracked_session().status, "completed")
        self.channel.delete()
        session = self.tracked_session(self.char2)
        self.assertEqual(session.status, "completed")
        self.assertIsNone(session.channel_id)
        self.assertEqual(session.channel_name, "IC test")

    def test_unpuppet_api_closes_all_channels_for_one_character(self):
        second = create_channel("Other IC")
        self.exchange()
        self.say(self.char1, 10, second)
        channel_tracker.end_character_channel_sessions(self.char1.pk)
        self.assertFalse(
            any(key[0] == self.char1.pk for key in channel_tracker._active_channel_sessions)
        )
        self.assertTrue(
            any(key[0] == self.char2.pk for key in channel_tracker._active_channel_sessions)
        )

    def test_shutdown_flush_and_recovery_use_last_persisted_activity(self):
        self.exchange()
        self.exchange(100)
        tracker.flush_all_sessions()
        self.assertTrue(
            all(
                s.status == "completed" and s.duration_seconds() == 100
                for s in RPSession.objects.all()
            )
        )
        session = self.tracked_session()
        session.status = "active"
        session.ended_at = None
        session.save()
        tracker.recover_orphaned_sessions()
        session.refresh_from_db()
        self.assertEqual(session.ended_at, session.last_activity_at)

    @skipUnless(apps.is_installed("evennia_xp"), "requires evennia_xp")
    def test_character_deletion_keeps_session_history_but_yields_no_award(self):
        from evennia_rptracker.integrations.xp import collect_rp_channel_sessions

        self.exchange()
        self.exchange(1200)
        self.exchange(1800)
        tracker.flush_all_sessions()
        session = self.tracked_session()
        self.char1.delete()
        session.refresh_from_db()
        self.assertIsNone(session.character_id)
        awards = list(collect_rp_channel_sessions(timezone.now() + timedelta(hours=1)))
        self.assertFalse(any(a.source_ref_id == session.pk for a in awards))

    def test_typeclass_collects_once_after_send_and_retains_history(self):
        with (
            patch.object(self.account, "get_all_puppets", return_value=[self.char1]),
            patch("evennia_rptracker.record_rp_channel_activity") as record,
            patch("evennia.comms.comms.logger.log_file") as history,
        ):
            self.channel.msg("An IC thought", senders=self.account)
        record.assert_called_once_with(self.char1, self.channel)
        self.assertIn("Char: An IC thought", history.call_args.args[0])

    def test_typeclass_rejects_ambiguous_puppets_and_ignores_system_emits(self):
        with (
            patch.object(self.account, "get_all_puppets", return_value=[self.char1, self.char2]),
            patch("evennia_rptracker.record_rp_channel_activity") as record,
        ):
            self.channel.msg("Ambiguous", senders=self.account)
            self.channel.msg("System texture")
            self.channel.msg("Staff texture", senders=self.account, emit=True)
        record.assert_not_called()

    def test_normal_account_channel_command_reaches_collector(self):
        from evennia_rptracker.channel_commands import CmdICChannel

        self.channel.connect(self.account)
        with (
            patch.object(self.account, "get_all_puppets", return_value=[self.char1]),
            patch.object(self.account, "get_puppet", return_value=self.char1),
            patch("evennia_rptracker.record_rp_channel_activity") as record,
        ):
            output = self.call(CmdICChannel(), "IC test = A thread of voices", caller=self.account)
            self.assertIn("Char: A thread of voices", output)
        record.assert_called_once_with(self.char1, self.channel)

    @skipUnless(apps.is_installed("evennia_xp"), "requires evennia_xp")
    def test_collectors_use_distinct_sources_and_host_multiplier(self):
        from evennia_rptracker.integrations.xp import (
            collect_rp_channel_sessions,
            collect_rp_sessions,
        )

        self.exchange()
        self.exchange(1200)
        self.exchange(1800)
        tracker.flush_all_sessions()
        with patch(
            "evennia_xp.gating.resolve_xp_multiplier", return_value=Decimal("0.5")
        ) as resolver:
            awards = list(collect_rp_channel_sessions(timezone.now() + timedelta(hours=1)))
        self.assertEqual(len(awards), 2)
        self.assertEqual({a.amount for a in awards}, {Decimal("0.5")})
        self.assertTrue(
            all(
                c.args[0] == "rp_channel_session" and c.kwargs["room"] is None
                for c in resolver.call_args_list
            )
        )
        self.assertEqual(list(collect_rp_sessions(timezone.now() + timedelta(hours=1))), [])

    @skipUnless(apps.is_installed("evennia_xp"), "requires evennia_xp")
    def test_post_batch_flags_require_confirmed_matching_ledger_rows(self):
        from evennia_xp.batch import Award
        from evennia_xp.models import XPLog

        from evennia_rptracker.integrations.xp import flip_channel_session_flags

        self.exchange()
        session = self.tracked_session()
        award = Award(
            self.char1.pk, Decimal("1"), "rp_channel_session", session.pk, Decimal("1"), "test"
        )
        flip_channel_session_flags(None, [award], "2026-W40")
        session.refresh_from_db()
        self.assertFalse(session.xp_awarded)
        XPLog.objects.create(
            character_id=self.char1.pk,
            amount=1,
            source_type="rp_channel_session",
            source_ref_id=session.pk,
        )
        flip_channel_session_flags(None, [award], "2026-W40")
        session.refresh_from_db()
        self.assertTrue(session.xp_awarded)
        self.assertEqual(session.xp_week, "2026-W40")

    @skipUnless(apps.is_installed("evennia_xp"), "requires evennia_xp")
    def test_post_batch_flags_ignore_ledger_rows_for_another_character(self):
        from evennia_xp.batch import Award
        from evennia_xp.models import XPLog

        from evennia_rptracker.integrations.xp import flip_channel_session_flags

        self.exchange()
        session = self.tracked_session()
        XPLog.objects.create(
            character_id=self.char2.pk,
            amount=1,
            source_type="rp_channel_session",
            source_ref_id=session.pk,
        )
        award = Award(
            self.char1.pk, Decimal("1"), "rp_channel_session", session.pk, Decimal("1"), "test"
        )
        flip_channel_session_flags(None, [award], "2026-W40")
        session.refresh_from_db()
        self.assertFalse(session.xp_awarded)

    def test_flagged_channel_session_is_excluded_and_reviewable(self):
        self.exchange()
        session = self.tracked_session()
        session.flag("Review this")
        self.assertFalse(session.is_xp_eligible())
        session.unflag()
        self.assertEqual(session.status, "completed")


class ActivityReportTests(EvenniaCommandTest):
    def make_session(self, character=None, **changes):
        defaults = dict(
            character=character or self.char1,
            character_name="Participant",
            room=self.room1,
            room_name="Report room",
            status="completed",
            activated_at=timezone.now() - timedelta(hours=2),
            ended_at=timezone.now() - timedelta(hours=1),
            account_id_snapshot=self.account.pk,
        )
        defaults.update(changes)
        return RPSession.objects.create(**defaults)

    @override_settings(RPTRACKER_REGIONS_APP_LABEL="missing_regions")
    def test_room_fallback_and_distinct_participants(self):
        from evennia_rptracker.reports import activity_report

        self.make_session()
        self.make_session()
        result = activity_report()["rows"][0]
        self.assertEqual(
            (result["kind"], result["completed"], result["characters"], result["accounts"]),
            ("room", 2, 1, 1),
        )
        self.assertAlmostEqual(result["minutes"], 120, places=1)

    @override_settings(RPTRACKER_REGIONS_APP_LABEL="missing_regions")
    def test_deleted_rooms_and_characters_keep_their_own_counts(self):
        from evennia_rptracker.reports import activity_report

        self.make_session(room=None, room_name="Old cellar")
        self.make_session(room=None, room_name="Old tower", character=None)
        self.make_session(
            room=None, room_name="Old tower", character=None, account_id_snapshot=None
        )
        rows = {row["name"]: row for row in activity_report()["rows"]}
        self.assertEqual(set(rows), {"Old cellar (deleted)", "Old tower (deleted)"})
        self.assertEqual(
            (rows["Old cellar (deleted)"]["completed"], rows["Old cellar (deleted)"]["characters"]),
            (1, 1),
        )
        tower = rows["Old tower (deleted)"]
        self.assertEqual(
            (tower["completed"], tower["characters"], tower["accounts"], tower["unknown_accounts"]),
            (2, 1, 1, 1),
        )

    @skipUnless(apps.is_installed("evennia_regions"), "requires evennia_regions")
    def test_regions_use_canonical_primary_membership(self):
        from evennia_regions.models import Region, RegionMembership
        from evennia_rptracker.reports import activity_report

        first = Region.create_region("First report area", self.char1)
        second = Region.create_region("Primary report area", self.char1)
        RegionMembership.objects.create(region=first, room=self.room1)
        RegionMembership.objects.create(region=second, room=self.room1, is_primary=True)
        self.make_session()
        result = activity_report()["rows"][0]
        self.assertEqual((result["kind"], result["id"]), ("region", second.pk))

    def test_channels_are_separate_and_flagged_sessions_excluded(self):
        from evennia_rptracker.reports import activity_report

        self.make_session(status="flagged")
        now = timezone.now()
        self.make_session(
            source_type="rp_channel_session",
            channel_name="Global IC",
            room=None,
            activated_at=now - timedelta(hours=2),
            last_activity_at=now - timedelta(hours=1),
        )
        result = activity_report(now=now)
        channel = next(r for r in result["rows"] if r["kind"] == "channel")
        room = next(r for r in result["rows"] if r["kind"] != "channel")
        self.assertEqual(channel["name"], "Global IC")
        self.assertEqual((room["flagged"], room["characters"], room["minutes"]), (1, 0, 0))

    def test_window_clips_minutes_and_read_has_no_writes(self):
        from evennia_rptracker.reports import activity_report

        now = timezone.now()
        self.make_session(activated_at=now - timedelta(days=2), ended_at=now - timedelta(hours=12))
        with patch.object(RPSession, "save", side_effect=AssertionError("Report wrote a session")):
            result = activity_report(1, now=now)
        self.assertEqual(result["rows"][0]["minutes"], 720)
        with self.assertRaises(ValueError):
            activity_report(0)

    def test_report_command_is_staff_only(self):
        from evennia_rptracker.commands import CmdRPActivityReport

        self.assertEqual(CmdRPActivityReport.locks, "cmd:perm(Builder)")
        self.call(CmdRPActivityReport(), "activity", "RP activity:", caller=self.char1)
        self.call(CmdRPActivityReport(), "activity 0", "Choose 1 to 90 days.")
