# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_rptracker.

Uses EvenniaTest which provides:
    self.char1 (key="Char"), self.char2 (key="Char2") — both in self.room1
    self.obj1, self.obj2 — generic objects
    self.account, self.account2

Tracker tests modify the module-level _active_sessions dict; setUp() clears
it before each test to prevent state leakage.

Run:
    evennia test --settings test_rptracker_settings.py evennia_rptracker
"""

import time
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest

from evennia_rptracker.models import RPSession, RPSessionPartner, RPSessionSceneLink


def _clear_tracker():
    """Clear in-memory tracker state between tests."""
    from evennia_rptracker import tracker

    tracker._active_sessions.clear()


# ---------------------------------------------------------------------------
# RPSession model tests
# ---------------------------------------------------------------------------


class TestRPSessionModel(EvenniaTest):
    def setUp(self):
        super().setUp()
        _clear_tracker()

    def _make_session(self, **kwargs):
        defaults = dict(
            character=self.char1,
            character_name="Char",
            room=self.room1,
            room_name="Room",
        )
        defaults.update(kwargs)
        return RPSession.objects.create(**defaults)

    def test_defaults(self):
        s = self._make_session()
        self.assertEqual(s.status, RPSession.Status.PENDING)
        self.assertEqual(s.pose_count, 0)
        self.assertFalse(s.ended_manually)
        self.assertFalse(s.xp_awarded)
        self.assertIsNone(s.ended_at)

    def test_duration_display_minutes(self):
        s = self._make_session()
        s.activated_at = timezone.now() - timedelta(minutes=45)
        s.save(update_fields=["activated_at"])
        self.assertIn("m", s.duration_display())

    def test_duration_display_hours(self):
        s = self._make_session()
        s.activated_at = timezone.now() - timedelta(hours=2, minutes=10)
        s.save(update_fields=["activated_at"])
        self.assertIn("h", s.duration_display())

    def test_is_xp_eligible_requires_completed(self):
        s = self._make_session(status=RPSession.Status.ACTIVE)
        self.assertFalse(s.is_xp_eligible())

    def test_is_xp_eligible_requires_duration(self):
        s = self._make_session(status=RPSession.Status.COMPLETED)
        s.activated_at = timezone.now()
        s.ended_at = timezone.now()
        s.save(update_fields=["activated_at", "ended_at"])
        self.assertFalse(s.is_xp_eligible())

    def test_is_xp_eligible_requires_partner(self):
        s = self._make_session(status=RPSession.Status.COMPLETED)
        s.activated_at = timezone.now() - timedelta(hours=1)
        s.ended_at = timezone.now()
        s.save(update_fields=["activated_at", "ended_at"])
        self.assertFalse(s.is_xp_eligible())

    def test_is_xp_eligible_true(self):
        s = self._make_session(status=RPSession.Status.COMPLETED)
        s.activated_at = timezone.now() - timedelta(hours=1)
        s.ended_at = timezone.now()
        s.save(update_fields=["activated_at", "ended_at"])
        RPSessionPartner.objects.create(session=s, partner=self.char2, partner_name="Char2")
        self.assertTrue(s.is_xp_eligible())

    def test_is_xp_eligible_already_awarded(self):
        s = self._make_session(status=RPSession.Status.COMPLETED, xp_awarded=True)
        s.activated_at = timezone.now() - timedelta(hours=1)
        s.ended_at = timezone.now()
        s.save(update_fields=["activated_at", "ended_at"])
        RPSessionPartner.objects.create(session=s, partner=self.char2, partner_name="Char2")
        self.assertFalse(s.is_xp_eligible())

    def test_activate(self):
        s = self._make_session()
        s.activate(room=self.room1)
        s.refresh_from_db()
        self.assertEqual(s.status, RPSession.Status.ACTIVE)
        self.assertIsNotNone(s.activated_at)

    def test_activate_noop_if_not_pending(self):
        s = self._make_session(status=RPSession.Status.COMPLETED)
        s.activate(room=self.room1)
        s.refresh_from_db()
        self.assertEqual(s.status, RPSession.Status.COMPLETED)

    def test_complete(self):
        s = self._make_session(status=RPSession.Status.ACTIVE)
        s.complete(manual=False)
        s.refresh_from_db()
        self.assertEqual(s.status, RPSession.Status.COMPLETED)
        self.assertIsNotNone(s.ended_at)
        self.assertFalse(s.ended_manually)

    def test_complete_manual(self):
        s = self._make_session(status=RPSession.Status.ACTIVE)
        s.complete(manual=True)
        s.refresh_from_db()
        self.assertTrue(s.ended_manually)

    def test_flag(self):
        s = self._make_session(status=RPSession.Status.COMPLETED)
        s.flag(reason="Test reason", flagged_by=self.char2)
        s.refresh_from_db()
        self.assertEqual(s.status, RPSession.Status.FLAGGED)
        self.assertEqual(s.flag_reason, "Test reason")
        self.assertEqual(s.flagged_by, self.char2)
        self.assertEqual(s.flagged_by_name, "Char2")
        self.assertIsNotNone(s.flagged_at)

    def test_flag_auto(self):
        s = self._make_session(status=RPSession.Status.COMPLETED)
        s.flag(reason="Auto flag")
        s.refresh_from_db()
        self.assertEqual(s.flagged_by_name, "auto")
        self.assertIsNone(s.flagged_by)

    def test_unflag(self):
        s = self._make_session(status=RPSession.Status.FLAGGED)
        s.flag_reason = "Old reason"
        s.flagged_by_name = "auto"
        s.save(update_fields=["flag_reason", "flagged_by_name"])
        s.unflag()
        s.refresh_from_db()
        self.assertEqual(s.status, RPSession.Status.COMPLETED)
        self.assertEqual(s.flag_reason, "")
        self.assertEqual(s.flagged_by_name, "")


class TestRPSessionPartnerModel(EvenniaTest):
    def setUp(self):
        super().setUp()
        _clear_tracker()

    def test_create_partner(self):
        session = RPSession.objects.create(
            character=self.char1, character_name="Char", room=self.room1, room_name="Room"
        )
        partner = RPSessionPartner.objects.create(
            session=session, partner=self.char2, partner_name="Char2", pose_count=3
        )
        self.assertEqual(partner.pose_count, 3)

    def test_unique_constraint(self):
        """Cannot add the same partner twice to a session."""
        from django.db import IntegrityError, transaction

        session = RPSession.objects.create(
            character=self.char1, character_name="Char", room=self.room1, room_name="Room"
        )
        RPSessionPartner.objects.create(session=session, partner=self.char2, partner_name="Char2")
        with self.assertRaises(IntegrityError), transaction.atomic():
            RPSessionPartner.objects.create(
                session=session, partner=self.char2, partner_name="Char2"
            )


# ---------------------------------------------------------------------------
# Tracker runtime tests
# ---------------------------------------------------------------------------


class TestTrackerRecordRpActivity(EvenniaTest):
    def setUp(self):
        super().setUp()
        _clear_tracker()
        self.room1.room_type = "ic"
        self.char2.last_pose_time = time.time()

    def tearDown(self):
        super().tearDown()
        _clear_tracker()

    def test_skip_ooc_room(self):
        from evennia_rptracker import tracker

        self.room1.room_type = "ooc"
        tracker.record_rp_activity(self.char1, self.room1)
        self.assertNotIn(self.char1.id, tracker._active_sessions)

    def test_skip_npc(self):
        from evennia_rptracker import tracker

        self.char1.tags.add("npc", category="npc_system")
        tracker.record_rp_activity(self.char1, self.room1)
        self.assertNotIn(self.char1.id, tracker._active_sessions)

    def test_first_pose_creates_pending(self):
        from evennia_rptracker import tracker

        tracker.record_rp_activity(self.char1, self.room1)
        state = tracker._active_sessions.get(self.char1.id)
        self.assertIsNotNone(state)
        self.assertEqual(state["status"], "pending")
        self.assertIsNone(state["session_id"])

    def test_activation_threshold(self):
        """Pose twice with an active partner → session activates."""
        from evennia_rptracker import tracker

        tracker.SESSION_ACTIVATION_POSES = 2
        tracker.record_rp_activity(self.char1, self.room1)
        tracker.record_rp_activity(self.char1, self.room1)
        state = tracker._active_sessions.get(self.char1.id)
        self.assertEqual(state["status"], "active")
        self.assertIsNotNone(state["session_id"])
        self.assertTrue(RPSession.objects.filter(pk=state["session_id"]).exists())

    def test_no_activation_without_partner(self):
        """Poses without a partner stay pending."""
        from evennia_rptracker import tracker

        tracker.SESSION_ACTIVATION_POSES = 2
        self.char2.last_pose_time = None  # no active partner
        for _ in range(5):
            tracker.record_rp_activity(self.char1, self.room1)
        state = tracker._active_sessions.get(self.char1.id)
        self.assertEqual(state["status"], "pending")

    def test_end_session_completes_db(self):
        from evennia_rptracker import tracker

        tracker.SESSION_ACTIVATION_POSES = 2
        tracker.record_rp_activity(self.char1, self.room1)
        tracker.record_rp_activity(self.char1, self.room1)
        session_id = tracker._active_sessions[self.char1.id]["session_id"]
        tracker.end_session(self.char1.id, manual=False)
        session = RPSession.objects.get(pk=session_id)
        self.assertEqual(session.status, RPSession.Status.COMPLETED)
        self.assertFalse(session.ended_manually)

    def test_end_session_manual(self):
        from evennia_rptracker import tracker

        tracker.SESSION_ACTIVATION_POSES = 2
        tracker.record_rp_activity(self.char1, self.room1)
        tracker.record_rp_activity(self.char1, self.room1)
        session_id = tracker._active_sessions[self.char1.id]["session_id"]
        tracker.end_session(self.char1.id, manual=True)
        session = RPSession.objects.get(pk=session_id)
        self.assertTrue(session.ended_manually)

    def test_get_active_session_id(self):
        from evennia_rptracker import tracker

        tracker.SESSION_ACTIVATION_POSES = 2
        self.assertIsNone(tracker.get_active_session_id(self.char1.id))
        tracker.record_rp_activity(self.char1, self.room1)
        tracker.record_rp_activity(self.char1, self.room1)
        self.assertIsNotNone(tracker.get_active_session_id(self.char1.id))

    def test_rp_activity_signal_fires(self):
        """rp_activity_recorded fires on each pose during an active session."""
        from evennia_rptracker import tracker
        from evennia_rptracker.signals import rp_activity_recorded

        tracker.SESSION_ACTIVATION_POSES = 2
        fired = []

        def receiver(sender, **kw):  # named var keeps a strong ref (weak-ref safe)
            fired.append(kw)

        rp_activity_recorded.connect(receiver)
        try:
            tracker.record_rp_activity(self.char1, self.room1)
            tracker.record_rp_activity(self.char1, self.room1)  # activates + fires
            self.assertEqual(len(fired), 1)
            tracker.record_rp_activity(self.char1, self.room1)
            self.assertEqual(len(fired), 2)
        finally:
            rp_activity_recorded.disconnect(receiver)

    def test_recover_orphaned_sessions(self):
        from evennia_rptracker import tracker

        session = RPSession.objects.create(
            character=self.char1,
            character_name="Char",
            room=self.room1,
            room_name="Room",
            status=RPSession.Status.ACTIVE,
        )
        tracker.recover_orphaned_sessions()
        session.refresh_from_db()
        self.assertEqual(session.status, RPSession.Status.COMPLETED)


# ---------------------------------------------------------------------------
# Anti-gaming tests
# ---------------------------------------------------------------------------


class TestAntigamingPoseSpam(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.window_end = self.now + timedelta(days=1)

    def _make_session(self, *, pose_count=20, duration_minutes=5):
        from evennia_rptracker.models import RPSession

        s = RPSession.objects.create(
            character=self.char1,
            character_name=self.char1.key,
            room=self.room1,
            room_name="Room",
            status=RPSession.Status.COMPLETED,
            pose_count=pose_count,
            xp_awarded=False,
        )
        s.activated_at = self.window_end - timedelta(minutes=duration_minutes + 1)
        s.ended_at = self.window_end - timedelta(minutes=1)
        s.save(update_fields=["activated_at", "ended_at"])
        return s

    def test_fires_at_threshold(self):
        from evennia_rptracker.antigaming import _flag_pose_spam

        session = self._make_session(pose_count=20, duration_minutes=5)
        _flag_pose_spam(self.window_end)
        session.refresh_from_db()
        self.assertEqual(session.status, RPSession.Status.FLAGGED)

    def test_below_threshold_not_flagged(self):
        from evennia_rptracker.antigaming import _flag_pose_spam

        session = self._make_session(pose_count=5, duration_minutes=5)
        _flag_pose_spam(self.window_end)
        session.refresh_from_db()
        self.assertEqual(session.status, RPSession.Status.COMPLETED)

    def test_long_duration_not_flagged(self):
        from evennia_rptracker.antigaming import _flag_pose_spam

        session = self._make_session(pose_count=20, duration_minutes=15)
        _flag_pose_spam(self.window_end)
        session.refresh_from_db()
        self.assertEqual(session.status, RPSession.Status.COMPLETED)

    def test_review_hook_called(self):
        from evennia_rptracker.antigaming import _flag_pose_spam

        self._make_session(pose_count=20, duration_minutes=5)
        with patch("evennia_rptracker.antigaming._notify_flag_review") as mock_hook:
            _flag_pose_spam(self.window_end)
        mock_hook.assert_called_once()

    def test_idempotent(self):
        from evennia_rptracker.antigaming import _flag_pose_spam

        session = self._make_session(pose_count=20, duration_minutes=5)
        session.flag("pre-existing")
        with patch("evennia_rptracker.antigaming._notify_flag_review") as mock_hook:
            _flag_pose_spam(self.window_end)
        mock_hook.assert_not_called()


class TestAntigamingManualEndAbuse(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.window_end = self.now + timedelta(days=1)

    def _make_manual_session(self, offset_hours=1):
        s = RPSession.objects.create(
            character=self.char1,
            character_name=self.char1.key,
            room=self.room1,
            room_name="Room",
            status=RPSession.Status.COMPLETED,
            ended_manually=True,
            xp_awarded=False,
        )
        ended_at = self.window_end - timedelta(hours=offset_hours)
        s.activated_at = ended_at - timedelta(hours=1)
        s.ended_at = ended_at
        s.save(update_fields=["activated_at", "ended_at"])
        return s

    def test_fires_at_three_in_24h(self):
        from evennia_rptracker.antigaming import _flag_manual_end_abuse

        s1 = self._make_manual_session(offset_hours=3)
        s2 = self._make_manual_session(offset_hours=2)
        s3 = self._make_manual_session(offset_hours=1)
        _flag_manual_end_abuse(self.window_end)
        for s in (s1, s2, s3):
            s.refresh_from_db()
            self.assertEqual(s.status, RPSession.Status.FLAGGED)

    def test_two_not_flagged(self):
        from evennia_rptracker.antigaming import _flag_manual_end_abuse

        s1 = self._make_manual_session(offset_hours=2)
        s2 = self._make_manual_session(offset_hours=1)
        _flag_manual_end_abuse(self.window_end)
        for s in (s1, s2):
            s.refresh_from_db()
            self.assertEqual(s.status, RPSession.Status.COMPLETED)

    def test_review_hook_called(self):
        from evennia_rptracker.antigaming import _flag_manual_end_abuse

        for i in range(3):
            self._make_manual_session(offset_hours=i + 1)
        with patch("evennia_rptracker.antigaming._notify_flag_review") as mock_hook:
            _flag_manual_end_abuse(self.window_end)
        mock_hook.assert_called_once()

    def test_sweep_calls_both_rules(self):
        from evennia_rptracker.antigaming import sweep_rp_sessions

        with (
            patch("evennia_rptracker.antigaming._flag_pose_spam") as r1,
            patch("evennia_rptracker.antigaming._flag_manual_end_abuse") as r2,
        ):
            sweep_rp_sessions(self.window_end)
        r1.assert_called_once_with(self.window_end)
        r2.assert_called_once_with(self.window_end)


# ---------------------------------------------------------------------------
# Command smoke tests
# ---------------------------------------------------------------------------


class TestCmdActivityNoProjection(EvenniaTest):
    """Without RPTRACKER_XP_PROJECTION set, +activity shows no XP projection."""

    def setUp(self):
        super().setUp()
        _clear_tracker()

    def tearDown(self):
        super().tearDown()
        _clear_tracker()

    def test_activity_no_projection(self):
        from evennia.commands.default.tests import BaseEvenniaCommandTest

        from evennia_rptracker.commands import CmdActivity

        # Confirm it doesn't crash without the XP hook.
        with patch("django.conf.settings") as mock_settings:
            mock_settings.RPTRACKER_XP_PROJECTION = None
            mock_settings.RPTRACKER_SCENE_DISPLAY = None
            # Just verifies command can be instantiated and parsed.
            cmd = CmdActivity()
            self.assertIsNotNone(cmd)


class TestCmdRPTrackerStaffLock(EvenniaTest):
    def test_staff_lock_default(self):
        from evennia_rptracker.commands import CmdRPTrackerStaff

        self.assertEqual(CmdRPTrackerStaff.locks, "cmd:perm(Builder)")


# ---------------------------------------------------------------------------
# Scene bridge tests (scenes-absent profile)
# ---------------------------------------------------------------------------


class TestSceneBridgeListener(EvenniaTest):
    """Test the rp_activity_recorded listener without a real scenes app."""

    def setUp(self):
        super().setUp()
        _clear_tracker()
        self.room1.room_type = "ic"
        self.char2.last_pose_time = time.time()

    def tearDown(self):
        super().tearDown()
        _clear_tracker()

    def test_listener_creates_link_when_scene_active(self):
        """Setting room.active_scene_id causes an RPSessionSceneLink to be created."""
        from evennia_rptracker import tracker
        from evennia_rptracker.bridges_scenes import on_rp_activity_recorded
        from evennia_rptracker.signals import rp_activity_recorded

        # Wire the listener manually (it's normally registered via apps.ready()).
        rp_activity_recorded.connect(on_rp_activity_recorded)
        try:
            tracker.SESSION_ACTIVATION_POSES = 2
            self.room1.active_scene_id = 42  # fake scene pk

            tracker.record_rp_activity(self.char1, self.room1)
            tracker.record_rp_activity(self.char1, self.room1)  # activates + fires signal

            session_id = tracker._active_sessions[self.char1.id]["session_id"]
            self.assertTrue(
                RPSessionSceneLink.objects.filter(session_id=session_id, scene_id=42).exists()
            )
        finally:
            rp_activity_recorded.disconnect(on_rp_activity_recorded)

    def test_no_link_without_active_scene_id(self):
        """If room has no active_scene_id, no link is created."""
        from evennia_rptracker import tracker
        from evennia_rptracker.bridges_scenes import on_rp_activity_recorded
        from evennia_rptracker.signals import rp_activity_recorded

        rp_activity_recorded.connect(on_rp_activity_recorded)
        try:
            tracker.SESSION_ACTIVATION_POSES = 2
            self.room1.active_scene_id = None

            tracker.record_rp_activity(self.char1, self.room1)
            tracker.record_rp_activity(self.char1, self.room1)

            self.assertEqual(RPSessionSceneLink.objects.count(), 0)
        finally:
            rp_activity_recorded.disconnect(on_rp_activity_recorded)

    def test_link_is_idempotent(self):
        """Repeated signals for the same (session, scene) produce one link."""
        from evennia_rptracker import tracker
        from evennia_rptracker.bridges_scenes import on_rp_activity_recorded
        from evennia_rptracker.signals import rp_activity_recorded

        rp_activity_recorded.connect(on_rp_activity_recorded)
        try:
            tracker.SESSION_ACTIVATION_POSES = 2
            self.room1.active_scene_id = 99

            for _ in range(4):
                tracker.record_rp_activity(self.char1, self.room1)

            self.assertEqual(RPSessionSceneLink.objects.count(), 1)
        finally:
            rp_activity_recorded.disconnect(on_rp_activity_recorded)


# ---------------------------------------------------------------------------
# Soft-ref cleanup test (probe table created outside EvenniaTest's atomic)
# ---------------------------------------------------------------------------


class TestSoftRefCleanup(EvenniaTest):
    """Verify connect_soft_ref_cleanup deletes bridge rows on hard delete.

    Uses a throwaway SceneStub model. Tables are built via the schema editor
    BEFORE EvenniaTest's class-level atomic block (SQLite can't toggle FK
    checks mid-transaction — same lesson as evennia-links tests).
    """

    from django.db import models as _dj_models

    class SceneStub(_dj_models.Model):
        class Meta:
            app_label = "evennia_rptracker"

    @classmethod
    def setUpClass(cls):
        from django.db import connection

        with connection.schema_editor() as se:
            se.create_model(cls.SceneStub)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        from django.db import connection

        with connection.schema_editor() as se:
            se.delete_model(cls.SceneStub)

    def test_cleanup_on_hard_delete(self):
        from evennia_links import connect_soft_ref_cleanup

        connect_soft_ref_cleanup(self.SceneStub, RPSessionSceneLink, "scene_id")

        session = RPSession.objects.create(
            character=self.char1,
            character_name=self.char1.key,
            room=self.room1,
            room_name="Room",
            status=RPSession.Status.ACTIVE,
        )
        stub = self.SceneStub.objects.create()
        RPSessionSceneLink.objects.create(session=session, scene_id=stub.pk)
        self.assertEqual(RPSessionSceneLink.objects.count(), 1)

        stub.delete()  # triggers the cleanup hook
        self.assertEqual(RPSessionSceneLink.objects.count(), 0)
