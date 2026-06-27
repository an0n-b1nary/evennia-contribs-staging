# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_plots.

Covers models (lifecycle, factories, bonus XP, permissions), bridges, listener,
XP gating, anti-gaming sweep, XP collectors, commands, web privacy, API privacy,
and template compile checks.

Run:
    evennia test --settings test_plots_settings evennia_plots
"""

import unittest
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import RequestFactory, override_settings
from django.utils import timezone
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from evennia_plots.antigaming import _flag_thread_gaming
from evennia_plots.commands import CmdArc, CmdHook, CmdPlot
from evennia_plots.gating import resolve_active_arc, resolve_xp_multiplier
from evennia_plots.listeners import on_scene_linked_to_thread
from evennia_plots.models import (
    PlotArc,
    PlotBoardLink,
    PlotBonusCredit,
    PlotCalendarLink,
    PlotParticipant,
    PlotTag,
    PlotThread,
    PlotUpdate,
    PlotUpdateVersion,
    ScenePlotLink,
    ThreadLink,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_thread(name="Test Thread", creator=None, privacy="public", status=None):
    thread = PlotThread.create_thread(name=name, creator=creator, description="", privacy=privacy)
    if status == "active":
        thread.activate()
    elif status == "concluded":
        thread.activate()
        thread.conclude()
    return thread


def _make_arc(name="Test Arc", creator=None, arc_type=None):
    return PlotArc.create_arc(name=name, creator=creator, arc_type=arc_type)


class catch_signal:
    """Context manager that records every send of a Django Signal.

    Connects with ``weak=False`` so the receiver is not garbage-collected
    before the signal fires (a bound lambda has no other strong reference),
    and disconnects the exact receiver on exit.

    Usage::

        with catch_signal(plot_thread_created) as received:
            PlotThread.create_thread(...)
        self.assertEqual(len(received), 1)
    """

    def __init__(self, signal):
        self.signal = signal
        self.received = []

    def _receiver(self, **kwargs):
        self.received.append(kwargs)

    def __enter__(self):
        self.signal.connect(self._receiver, weak=False)
        return self.received

    def __exit__(self, *exc):
        self.signal.disconnect(self._receiver)
        return False


# ---------------------------------------------------------------------------
# __init__.py exports
# ---------------------------------------------------------------------------


class TestPlotsInit(unittest.TestCase):
    def test_version(self):
        import evennia_plots

        self.assertEqual(evennia_plots.__version__, "0.1.0")

    def test_signals_eagerly_exported(self):
        from django.dispatch import Signal

        import evennia_plots

        for name in [
            "plot_thread_created",
            "plot_thread_activated",
            "plot_thread_concluded",
            "plot_thread_archived",
            "scene_linked_to_thread",
            "post_linked_to_thread",
            "event_linked_to_thread",
            "thread_link_accepted",
            "plot_update_created",
            "plot_thread_edited",
            "arc_type_changed",
            "arc_currency_changed",
        ]:
            with self.subTest(signal=name):
                self.assertIsInstance(getattr(evennia_plots, name), Signal)

    def test_lazy_model_exports_resolve(self):
        import evennia_plots

        for name in [
            "PlotThread",
            "PlotArc",
            "PlotTag",
            "PlotParticipant",
            "PlotUpdate",
            "ThreadLink",
            "ScenePlotLink",
            "PlotCalendarLink",
            "PlotBoardLink",
            "PlotBonusCredit",
        ]:
            with self.subTest(model=name):
                self.assertIsNotNone(getattr(evennia_plots, name))

    def test_unknown_attr_raises(self):
        import evennia_plots

        with self.assertRaises(AttributeError):
            _ = evennia_plots.NonExistentModel


# ---------------------------------------------------------------------------
# PlotTag
# ---------------------------------------------------------------------------


class TestPlotTagModel(EvenniaTest):
    def test_create_tag_major(self):
        tag = PlotTag.objects.create(name="Magic", is_major=True)
        self.assertTrue(tag.is_major)

    def test_str_major(self):
        tag = PlotTag.objects.create(name="Politics", is_major=True)
        self.assertIn("Major", str(tag))
        self.assertIn("Politics", str(tag))

    def test_str_minor(self):
        tag = PlotTag.objects.create(name="Dragons")
        self.assertIn("Minor", str(tag))


# ---------------------------------------------------------------------------
# PlotArc — factory + lifecycle + XP multiplier
# ---------------------------------------------------------------------------


class TestPlotArcFactory(EvenniaTest):
    def test_arc_number_starts_at_one(self):
        arc = _make_arc(creator=self.char1)
        self.assertEqual(arc.arc_number, 1)

    def test_arc_number_increments(self):
        a1 = _make_arc("Arc A", creator=self.char1)
        a2 = _make_arc("Arc B", creator=self.char1)
        self.assertGreater(a2.arc_number, a1.arc_number)

    def test_creator_name_denormalized(self):
        arc = _make_arc(creator=self.char1)
        self.assertEqual(arc.creator_name, self.char1.key)

    def test_default_type_is_story(self):
        arc = _make_arc(creator=self.char1)
        self.assertEqual(arc.arc_type, PlotArc.ArcType.STORY)

    def test_default_status_is_active(self):
        arc = _make_arc(creator=self.char1)
        self.assertEqual(arc.status, PlotArc.Status.ACTIVE)


class TestPlotArcLifecycle(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.arc = _make_arc(creator=self.char1)

    def test_conclude_sets_status(self):
        self.arc.conclude()
        self.arc.refresh_from_db()
        self.assertEqual(self.arc.status, PlotArc.Status.CONCLUDED)

    def test_conclude_sets_concluded_at(self):
        self.arc.conclude()
        self.arc.refresh_from_db()
        self.assertIsNotNone(self.arc.concluded_at)

    def test_conclude_clears_is_current_if_set(self):
        self.arc.is_current = True
        self.arc.save(update_fields=["is_current"])
        self.arc.conclude()
        self.arc.refresh_from_db()
        self.assertFalse(self.arc.is_current)

    def test_archive_sets_status(self):
        self.arc.archive()
        self.arc.refresh_from_db()
        self.assertEqual(self.arc.status, PlotArc.Status.ARCHIVED)


class TestPlotArcXPMultiplier(EvenniaTest):
    def test_story_default_is_one(self):
        arc = _make_arc(creator=self.char1, arc_type=PlotArc.ArcType.STORY)
        self.assertEqual(arc.get_xp_multiplier("rp_session"), Decimal("1.0"))

    def test_downtime_default_is_zero(self):
        arc = _make_arc(creator=self.char1, arc_type=PlotArc.ArcType.DOWNTIME)
        self.assertEqual(arc.get_xp_multiplier("rp_session"), Decimal("0.0"))

    def test_per_arc_override_wins_over_type_default(self):
        arc = _make_arc(creator=self.char1)
        arc.xp_mult_rp_session = Decimal("2.5")
        arc.save(update_fields=["xp_mult_rp_session"])
        self.assertEqual(arc.get_xp_multiplier("rp_session"), Decimal("2.5"))

    def test_downtime_override_can_restore_xp(self):
        arc = _make_arc(creator=self.char1, arc_type=PlotArc.ArcType.DOWNTIME)
        arc.xp_mult_lore = Decimal("1.0")
        arc.save(update_fields=["xp_mult_lore"])
        self.assertEqual(arc.get_xp_multiplier("lore"), Decimal("1.0"))

    def test_unknown_source_raises_value_error(self):
        arc = _make_arc(creator=self.char1)
        with self.assertRaises(ValueError):
            arc.get_xp_multiplier("nonexistent_source")

    def test_pauses_xp_true_for_downtime(self):
        arc = _make_arc(creator=self.char1, arc_type=PlotArc.ArcType.DOWNTIME)
        self.assertTrue(arc.pauses_xp)

    def test_pauses_xp_false_for_story(self):
        arc = _make_arc(creator=self.char1, arc_type=PlotArc.ArcType.STORY)
        self.assertFalse(arc.pauses_xp)

    def test_all_xp_sources_accessible(self):
        arc = _make_arc(creator=self.char1)
        for source in PlotArc.XP_SOURCES:
            with self.subTest(source=source):
                mult = arc.get_xp_multiplier(source)
                self.assertIsInstance(mult, Decimal)


class TestPlotArcOneCurrentConstraint(EvenniaTest):
    def test_two_current_arcs_raises_integrity_error(self):
        a1 = _make_arc("Arc 1", creator=self.char1)
        a1.is_current = True
        a1.save(update_fields=["is_current"])

        a2 = _make_arc("Arc 2", creator=self.char1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            a2.is_current = True
            a2.save(update_fields=["is_current"])

    def test_zero_current_arcs_allowed(self):
        a1 = _make_arc("Arc 1", creator=self.char1)
        a2 = _make_arc("Arc 2", creator=self.char1)
        self.assertFalse(a1.is_current)
        self.assertFalse(a2.is_current)


# ---------------------------------------------------------------------------
# PlotThread — factory + lifecycle
# ---------------------------------------------------------------------------


class TestPlotThreadFactory(EvenniaTest):
    def test_plot_number_starts_at_one(self):
        t = _make_thread(creator=self.char1)
        self.assertEqual(t.plot_number, 1)

    def test_plot_number_increments(self):
        t1 = _make_thread("Thread A", creator=self.char1)
        t2 = _make_thread("Thread B", creator=self.char1)
        self.assertGreater(t2.plot_number, t1.plot_number)

    def test_creator_name_denormalized(self):
        t = _make_thread(creator=self.char1)
        self.assertEqual(t.creator_name, self.char1.key)

    def test_default_status_is_proposed(self):
        t = _make_thread(creator=self.char1)
        self.assertEqual(t.status, PlotThread.Status.PROPOSED)

    def test_fires_plot_thread_created_signal(self):
        from evennia_plots.signals import plot_thread_created

        with catch_signal(plot_thread_created) as received:
            _make_thread(creator=self.char1)
        self.assertEqual(len(received), 1)
        self.assertIn("thread", received[0])


class TestPlotThreadLifecycle(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.thread = _make_thread(creator=self.char1)

    def test_activate_transitions_to_active(self):
        self.thread.activate()
        self.assertEqual(self.thread.status, PlotThread.Status.ACTIVE)

    def test_conclude_transitions_to_concluded(self):
        self.thread.activate()
        self.thread.conclude()
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.status, PlotThread.Status.CONCLUDED)

    def test_conclude_sets_concluded_at(self):
        self.thread.activate()
        self.thread.conclude()
        self.thread.refresh_from_db()
        self.assertIsNotNone(self.thread.concluded_at)

    def test_conclude_returns_int_bonus(self):
        self.thread.activate()
        bonus = self.thread.conclude()
        self.assertIsInstance(bonus, int)
        self.assertGreaterEqual(bonus, 0)
        self.assertLessEqual(bonus, 5)

    def test_conclude_stores_bonus_xp_computed(self):
        self.thread.activate()
        bonus = self.thread.conclude()
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.bonus_xp_computed, bonus)

    def test_conclude_fires_signal(self):
        from evennia_plots.signals import plot_thread_concluded

        with catch_signal(plot_thread_concluded) as received:
            self.thread.activate()
            self.thread.conclude()
        self.assertEqual(len(received), 1)
        self.assertIn("bonus_xp", received[0])

    def test_archive_transitions_to_archived(self):
        self.thread.archive()
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.status, PlotThread.Status.ARCHIVED)

    def test_archive_sets_archived_at(self):
        self.thread.archive()
        self.thread.refresh_from_db()
        self.assertIsNotNone(self.thread.archived_at)


# ---------------------------------------------------------------------------
# Bonus XP — all three checklist rules
# ---------------------------------------------------------------------------


class TestBonusXP(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.thread = _make_thread("Bonus Thread", creator=self.char1, status="active")

    def test_advance_notice_met_awards_three(self):
        PlotCalendarLink.objects.create(thread=self.thread, event_id=1, advance_notice_met=True)
        self.assertEqual(self.thread._compute_bonus_xp(), 3)

    def test_advance_notice_not_met_awards_zero(self):
        PlotCalendarLink.objects.create(thread=self.thread, event_id=1, advance_notice_met=False)
        self.assertEqual(self.thread._compute_bonus_xp(), 0)

    def test_two_scene_links_awards_one(self):
        ScenePlotLink.objects.create(thread=self.thread, scene_id=1)
        ScenePlotLink.objects.create(thread=self.thread, scene_id=2)
        self.assertEqual(self.thread._compute_bonus_xp(), 1)

    def test_one_scene_link_awards_zero(self):
        ScenePlotLink.objects.create(thread=self.thread, scene_id=1)
        self.assertEqual(self.thread._compute_bonus_xp(), 0)

    def test_is_ic_post_awards_one(self):
        PlotBoardLink.objects.create(thread=self.thread, post_id=1, is_ic_post=True)
        self.assertEqual(self.thread._compute_bonus_xp(), 1)

    def test_non_ic_post_awards_zero(self):
        PlotBoardLink.objects.create(thread=self.thread, post_id=1, is_ic_post=False)
        self.assertEqual(self.thread._compute_bonus_xp(), 0)

    def test_all_three_rules_awards_five(self):
        PlotCalendarLink.objects.create(thread=self.thread, event_id=1, advance_notice_met=True)
        ScenePlotLink.objects.create(thread=self.thread, scene_id=1)
        ScenePlotLink.objects.create(thread=self.thread, scene_id=2)
        PlotBoardLink.objects.create(thread=self.thread, post_id=1, is_ic_post=True)
        self.assertEqual(self.thread._compute_bonus_xp(), 5)

    def test_no_rules_awards_zero(self):
        self.assertEqual(self.thread._compute_bonus_xp(), 0)


# ---------------------------------------------------------------------------
# PlotUpdate — factory + block_number + clean XOR
# ---------------------------------------------------------------------------


class TestPlotUpdateFactory(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.thread = _make_thread(creator=self.char1, status="active")
        self.arc = _make_arc(creator=self.char1)

    def test_block_number_starts_at_one_for_thread(self):
        u = PlotUpdate.create_update(self.thread, self.char1, "First block")
        self.assertEqual(u.block_number, 1)

    def test_block_number_increments_per_thread(self):
        u1 = PlotUpdate.create_update(self.thread, self.char1, "Block A")
        u2 = PlotUpdate.create_update(self.thread, self.char1, "Block B")
        self.assertEqual(u1.block_number, 1)
        self.assertEqual(u2.block_number, 2)

    def test_block_number_starts_at_one_for_arc(self):
        u = PlotUpdate.create_update(self.arc, self.char1, "Arc block")
        self.assertEqual(u.block_number, 1)

    def test_thread_and_arc_block_numbers_are_independent(self):
        PlotUpdate.create_update(self.thread, self.char1, "T1")
        PlotUpdate.create_update(self.thread, self.char1, "T2")
        u_arc = PlotUpdate.create_update(self.arc, self.char1, "A1")
        self.assertEqual(u_arc.block_number, 1)

    def test_fires_plot_update_created_signal(self):
        from evennia_plots.signals import plot_update_created

        with catch_signal(plot_update_created) as received:
            PlotUpdate.create_update(self.thread, self.char1, "Signal test")
        self.assertEqual(len(received), 1)

    def test_clean_raises_when_both_thread_and_arc_set(self):
        update = PlotUpdate(thread=self.thread, arc=self.arc, content="Bad", block_number=1)
        with self.assertRaises(ValidationError):
            update.clean()

    def test_clean_raises_when_neither_set(self):
        update = PlotUpdate(content="Bad", block_number=1)
        with self.assertRaises(ValidationError):
            update.clean()


# ---------------------------------------------------------------------------
# PlotUpdateVersion
# ---------------------------------------------------------------------------


class TestPlotUpdateVersion(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.thread = _make_thread(creator=self.char1, status="active")
        self.update = PlotUpdate.create_update(self.thread, self.char1, "Original")

    def test_create_version_starts_at_one(self):
        v = PlotUpdateVersion.create_version(self.update, "Original", editor=self.char1)
        self.assertEqual(v.version_number, 1)

    def test_create_version_increments(self):
        v1 = PlotUpdateVersion.create_version(self.update, "First", editor=self.char1)
        v2 = PlotUpdateVersion.create_version(self.update, "Second", editor=self.char1)
        self.assertEqual(v1.version_number, 1)
        self.assertEqual(v2.version_number, 2)

    def test_create_version_stores_content(self):
        v = PlotUpdateVersion.create_version(self.update, "Snapshot A", editor=self.char1)
        self.assertEqual(v.content, "Snapshot A")

    def test_rollback_to_creates_new_version(self):
        PlotUpdateVersion.create_version(self.update, "v1 content", editor=self.char1)
        rollback = PlotUpdateVersion.rollback_to(self.update, 1, editor=self.char1)
        self.assertEqual(rollback.version_number, 2)
        self.assertTrue(rollback.is_rollback)
        self.assertEqual(rollback.rolled_back_from, 1)
        self.assertEqual(rollback.content, "v1 content")

    def test_unique_together_enforced(self):
        PlotUpdateVersion.create_version(self.update, "Content", editor=self.char1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PlotUpdateVersion.objects.create(
                parent=self.update,
                version_number=1,
                content="Dup",
                editor=self.char1,
                editor_name=self.char1.key,
            )


# ---------------------------------------------------------------------------
# ThreadLink — accept + mirror + signal
# ---------------------------------------------------------------------------


class TestThreadLinkAccept(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.t1 = _make_thread("Thread Alpha", creator=self.char1, status="active")
        self.t2 = _make_thread("Thread Beta", creator=self.char2, status="active")
        self.link = ThreadLink.objects.create(
            from_thread=self.t1,
            to_thread=self.t2,
            link_type=ThreadLink.LinkType.RELATED,
            is_accepted=False,
        )

    def test_accept_sets_is_accepted(self):
        self.link.accept(accepted_by=self.char2)
        self.link.refresh_from_db()
        self.assertTrue(self.link.is_accepted)

    def test_accept_creates_mirrored_reverse_link(self):
        self.link.accept(accepted_by=self.char2)
        self.assertTrue(ThreadLink.objects.filter(from_thread=self.t2, to_thread=self.t1).exists())

    def test_accept_mirror_is_idempotent(self):
        self.link.accept(accepted_by=self.char2)
        self.link.accept(accepted_by=self.char2)
        self.assertEqual(
            ThreadLink.objects.filter(from_thread=self.t2, to_thread=self.t1).count(), 1
        )

    def test_accept_fires_thread_link_accepted_signal(self):
        from evennia_plots.signals import thread_link_accepted

        with catch_signal(thread_link_accepted) as received:
            self.link.accept(accepted_by=self.char2)
        self.assertEqual(len(received), 1)
        self.assertIs(received[0]["link"], self.link)


# ---------------------------------------------------------------------------
# Permissions — can_link, can_view, can_update (with PLOTS_STAFF_LOCK seam)
# ---------------------------------------------------------------------------


class TestThreadPermissions(EvenniaTest):
    def test_can_link_public_active_any_character(self):
        t = _make_thread(creator=self.char1, status="active", privacy="public")
        self.assertTrue(t.can_link(self.char2))

    def test_can_link_private_active_non_creator_denied(self):
        t = _make_thread(creator=self.char1, status="active", privacy="private")
        self.assertFalse(t.can_link(self.char2))

    def test_can_link_private_creator_allowed(self):
        t = _make_thread(creator=self.char1, status="active", privacy="private")
        self.assertTrue(t.can_link(self.char1))

    def test_can_link_proposed_thread_denied(self):
        t = _make_thread(creator=self.char1, privacy="public")  # status=proposed
        self.assertFalse(t.can_link(self.char2))

    def test_can_link_invite_only_invited_allowed(self):
        t = _make_thread(creator=self.char1, status="active", privacy="invite_only")
        t.invited_characters.add(self.char2)
        self.assertTrue(t.can_link(self.char2))

    def test_can_link_invite_only_not_invited_denied(self):
        t = _make_thread(creator=self.char1, status="active", privacy="invite_only")
        self.assertFalse(t.can_link(self.char2))

    def test_can_view_public_any_character(self):
        t = _make_thread(creator=self.char1, status="active", privacy="public")
        self.assertTrue(t.can_view(self.char2))

    def test_can_view_invite_only_any_character(self):
        t = _make_thread(creator=self.char1, status="active", privacy="invite_only")
        self.assertTrue(t.can_view(self.char2))

    def test_can_view_private_non_creator_denied(self):
        t = _make_thread(creator=self.char1, status="active", privacy="private")
        self.assertFalse(t.can_view(self.char2))

    def test_can_view_private_creator_allowed(self):
        t = _make_thread(creator=self.char1, status="active", privacy="private")
        self.assertTrue(t.can_view(self.char1))

    def test_can_view_private_none_denied(self):
        t = _make_thread(creator=self.char1, status="active", privacy="private")
        self.assertFalse(t.can_view(None))

    def test_can_update_participant_allowed(self):
        t = _make_thread(creator=self.char1, status="active")
        PlotParticipant.objects.create(
            thread=t, character=self.char2, character_name=self.char2.key
        )
        self.assertTrue(t.can_update(self.char2))

    def test_can_update_non_participant_denied(self):
        t = _make_thread(creator=self.char1, status="active")
        self.assertFalse(t.can_update(self.char2))

    def test_can_update_concluded_thread_denied(self):
        t = _make_thread(creator=self.char1, status="concluded")
        # creator cannot update a concluded thread
        self.assertFalse(t.can_update(self.char1))

    @override_settings(PLOTS_STAFF_LOCK="cmd:perm(Admin)")
    def test_staff_lock_respected_on_private_can_link(self):
        from evennia_plots.permissions import is_plot_staff

        t = _make_thread(creator=self.char1, status="active", privacy="private")
        # char2 has no Admin perm → not staff → cannot link to private
        self.assertFalse(is_plot_staff(self.char2))
        self.assertFalse(t.can_link(self.char2))


# ---------------------------------------------------------------------------
# ScenePlotLink bridge
# ---------------------------------------------------------------------------


class TestScenePlotLink(EvenniaTest):
    def _mock_scene(self, pk=100):
        scene = MagicMock()
        scene.pk = pk
        return scene

    def test_create_link_stores_scene_id(self):
        thread = _make_thread(creator=self.char1, status="active")
        link, created = ScenePlotLink.create_link(scene=self._mock_scene(pk=42), thread=thread)
        self.assertTrue(created)
        self.assertEqual(link.scene_id, 42)

    def test_create_link_fires_scene_linked_to_thread_signal(self):
        from evennia_plots.signals import scene_linked_to_thread

        thread = _make_thread(creator=self.char1, status="active")
        with catch_signal(scene_linked_to_thread) as received:
            ScenePlotLink.create_link(scene=self._mock_scene(pk=55), thread=thread)
        self.assertEqual(len(received), 1)
        self.assertIs(received[0]["thread"], thread)

    def test_create_link_idempotent_no_duplicate_signal(self):
        from evennia_plots.signals import scene_linked_to_thread

        thread = _make_thread(creator=self.char1, status="active")
        scene = self._mock_scene(pk=77)
        with catch_signal(scene_linked_to_thread) as received:
            ScenePlotLink.create_link(scene=scene, thread=thread)
            _, created2 = ScenePlotLink.create_link(scene=scene, thread=thread)
        self.assertFalse(created2)
        self.assertEqual(len(received), 1)


# ---------------------------------------------------------------------------
# PlotCalendarLink bridge
# ---------------------------------------------------------------------------


class TestPlotCalendarLink(EvenniaTest):
    def _mock_event(self, pk=200, days_from_now=8):
        event = MagicMock()
        event.pk = pk
        event.scheduled_time = timezone.now() + timedelta(days=days_from_now)
        return event

    def test_advance_notice_met_when_7_plus_days(self):
        thread = _make_thread(creator=self.char1, status="active")
        link, created = PlotCalendarLink.create_link(
            thread=thread, event=self._mock_event(pk=201, days_from_now=8)
        )
        self.assertTrue(created)
        self.assertTrue(link.advance_notice_met)

    def test_advance_notice_not_met_when_under_7_days(self):
        thread = _make_thread(creator=self.char1, status="active")
        link, _ = PlotCalendarLink.create_link(
            thread=thread, event=self._mock_event(pk=202, days_from_now=3)
        )
        self.assertFalse(link.advance_notice_met)

    def test_stores_event_id_not_object(self):
        thread = _make_thread(creator=self.char1, status="active")
        link, _ = PlotCalendarLink.create_link(thread=thread, event=self._mock_event(pk=99))
        self.assertEqual(link.event_id, 99)


# ---------------------------------------------------------------------------
# PlotBoardLink bridge
# ---------------------------------------------------------------------------


class TestPlotBoardLink(EvenniaTest):
    def _mock_post(self, pk=300, board_type="ic"):
        post = MagicMock()
        post.pk = pk
        post.board.board_type = board_type
        return post

    def test_is_ic_post_true_for_ic_board(self):
        thread = _make_thread(creator=self.char1, status="active")
        link, created = PlotBoardLink.create_link(
            thread=thread, post=self._mock_post(pk=301, board_type="ic")
        )
        self.assertTrue(created)
        self.assertTrue(link.is_ic_post)

    def test_is_ic_post_false_for_ooc_board(self):
        thread = _make_thread(creator=self.char1, status="active")
        link, _ = PlotBoardLink.create_link(
            thread=thread, post=self._mock_post(pk=302, board_type="ooc")
        )
        self.assertFalse(link.is_ic_post)

    def test_stores_post_id_not_object(self):
        thread = _make_thread(creator=self.char1, status="active")
        link, _ = PlotBoardLink.create_link(thread=thread, post=self._mock_post(pk=777))
        self.assertEqual(link.post_id, 777)


# ---------------------------------------------------------------------------
# Listener — on_scene_linked_to_thread → PlotParticipant
# ---------------------------------------------------------------------------


class TestListenerParticipant(EvenniaTest):
    def _make_scene_with_participants(self, *characters):
        participants = []
        for char in characters:
            sp = MagicMock()
            sp.character_id = char.pk
            sp.character_name = char.key
            participants.append(sp)
        scene = MagicMock()
        scene.pk = 999
        scene.participants.filter.return_value.select_related.return_value = participants
        return scene

    def test_creates_participants_from_scene(self):
        thread = _make_thread(creator=self.char1, status="active")
        scene = self._make_scene_with_participants(self.char1, self.char2)
        on_scene_linked_to_thread(sender=ScenePlotLink, thread=thread, scene=scene, linked_by=None)
        self.assertEqual(PlotParticipant.objects.filter(thread=thread).count(), 2)

    def test_participant_creation_is_idempotent(self):
        thread = _make_thread(creator=self.char1, status="active")
        PlotParticipant.objects.create(
            thread=thread, character=self.char1, character_name=self.char1.key
        )
        scene = self._make_scene_with_participants(self.char1)
        on_scene_linked_to_thread(sender=ScenePlotLink, thread=thread, scene=scene, linked_by=None)
        self.assertEqual(PlotParticipant.objects.filter(thread=thread).count(), 1)

    def test_skips_participants_with_no_character_id(self):
        thread = _make_thread(creator=self.char1, status="active")
        sp = MagicMock()
        sp.character_id = None
        scene = MagicMock()
        scene.pk = 888
        scene.participants.filter.return_value.select_related.return_value = [sp]
        on_scene_linked_to_thread(sender=ScenePlotLink, thread=thread, scene=scene, linked_by=None)
        self.assertEqual(PlotParticipant.objects.filter(thread=thread).count(), 0)


# ---------------------------------------------------------------------------
# Gating — resolve_active_arc, resolve_xp_multiplier
# ---------------------------------------------------------------------------


class TestGating(EvenniaTest):
    def test_resolve_active_arc_uses_thread_arc(self):
        arc = _make_arc(creator=self.char1)
        thread = _make_thread(creator=self.char1, status="active")
        thread.arc = arc
        thread.save(update_fields=["arc"])
        self.assertEqual(resolve_active_arc(thread=thread), arc)

    def test_resolve_active_arc_falls_back_to_global_current(self):
        arc = _make_arc(creator=self.char1)
        arc.is_current = True
        arc.save(update_fields=["is_current"])
        thread = _make_thread(creator=self.char1, status="active")
        self.assertEqual(resolve_active_arc(thread=thread), arc)

    def test_resolve_active_arc_returns_none_when_no_arc(self):
        thread = _make_thread(creator=self.char1, status="active")
        self.assertIsNone(resolve_active_arc(thread=thread))

    def test_resolve_xp_multiplier_no_arc_returns_one(self):
        thread = _make_thread(creator=self.char1, status="active")
        self.assertEqual(resolve_xp_multiplier("rp_session", thread=thread), Decimal("1.0"))

    def test_resolve_xp_multiplier_downtime_arc_returns_zero(self):
        arc = _make_arc(creator=self.char1, arc_type=PlotArc.ArcType.DOWNTIME)
        arc.is_current = True
        arc.save(update_fields=["is_current"])
        thread = _make_thread(creator=self.char1, status="active")
        self.assertEqual(resolve_xp_multiplier("rp_session", thread=thread), Decimal("0.0"))

    def test_thread_arc_wins_over_global_current_arc(self):
        story_arc = _make_arc("Story", creator=self.char1, arc_type=PlotArc.ArcType.STORY)
        story_arc.is_current = True
        story_arc.save(update_fields=["is_current"])

        downtime_arc = _make_arc("Downtime", creator=self.char1, arc_type=PlotArc.ArcType.DOWNTIME)
        thread = _make_thread(creator=self.char1, status="active")
        thread.arc = downtime_arc
        thread.save(update_fields=["arc"])

        self.assertEqual(resolve_xp_multiplier("rp_session", thread=thread), Decimal("0.0"))

    def test_resolve_xp_multiplier_per_arc_override(self):
        arc = _make_arc(creator=self.char1, arc_type=PlotArc.ArcType.STORY)
        arc.xp_mult_lore = Decimal("2.0")
        arc.save(update_fields=["xp_mult_lore"])
        arc.is_current = True
        arc.save(update_fields=["is_current"])
        thread = _make_thread(creator=self.char1, status="active")
        self.assertEqual(resolve_xp_multiplier("lore", thread=thread), Decimal("2.0"))


# ---------------------------------------------------------------------------
# Anti-gaming sweep — _flag_thread_gaming
# ---------------------------------------------------------------------------


class TestAntigaming(EvenniaTest):
    def _set_thread_times(self, thread, created_hours_ago, concluded_offset_hours=0):
        now = timezone.now()
        created_at = now - timedelta(hours=created_hours_ago)
        concluded_at = created_at + timedelta(hours=concluded_offset_hours)
        PlotThread.objects.filter(pk=thread.pk).update(
            status=PlotThread.Status.CONCLUDED,
            bonus_xp_computed=3,
            bonus_xp_awarded=False,
            bonus_xp_flag_reason="",
            created_at=created_at,
            concluded_at=concluded_at,
        )
        return now

    def test_flags_thread_concluded_within_24h(self):
        thread = _make_thread(creator=self.char1)
        now = self._set_thread_times(thread, created_hours_ago=12, concluded_offset_hours=12)
        _flag_thread_gaming(window_end=now + timedelta(hours=1))
        thread.refresh_from_db()
        self.assertEqual(thread.bonus_xp_computed, 0)
        self.assertNotEqual(thread.bonus_xp_flag_reason, "")

    def test_does_not_flag_thread_concluded_after_24h(self):
        thread = _make_thread(creator=self.char1)
        now = self._set_thread_times(thread, created_hours_ago=50, concluded_offset_hours=30)
        _flag_thread_gaming(window_end=now + timedelta(hours=1))
        thread.refresh_from_db()
        self.assertEqual(thread.bonus_xp_computed, 3)
        self.assertEqual(thread.bonus_xp_flag_reason, "")

    def test_already_flagged_threads_skipped(self):
        thread = _make_thread(creator=self.char1)
        now = self._set_thread_times(thread, created_hours_ago=6, concluded_offset_hours=6)
        PlotThread.objects.filter(pk=thread.pk).update(bonus_xp_flag_reason="already flagged")
        _flag_thread_gaming(window_end=now + timedelta(hours=1))
        thread.refresh_from_db()
        # Already-flagged threads are excluded from queryset → bonus_xp_computed unchanged
        self.assertEqual(thread.bonus_xp_computed, 3)

    def test_zero_bonus_threads_skipped(self):
        thread = _make_thread(creator=self.char1)
        self._set_thread_times(thread, created_hours_ago=6, concluded_offset_hours=6)
        PlotThread.objects.filter(pk=thread.pk).update(bonus_xp_computed=0)
        now = timezone.now()
        _flag_thread_gaming(window_end=now + timedelta(hours=1))
        thread.refresh_from_db()
        self.assertEqual(thread.bonus_xp_flag_reason, "")


# ---------------------------------------------------------------------------
# XP Collectors (requires evennia_xp)
# ---------------------------------------------------------------------------


@unittest.skipUnless(apps.is_installed("evennia_xp"), "requires evennia_xp")
class TestCollectors(EvenniaTest):
    def _make_concluded_thread_with_bonus(self, bonus=3):
        now = timezone.now()
        thread = _make_thread(creator=self.char1)
        PlotThread.objects.filter(pk=thread.pk).update(
            status=PlotThread.Status.CONCLUDED,
            bonus_xp_computed=bonus,
            bonus_xp_awarded=False,
            concluded_at=now,
        )
        return thread, now

    def test_yields_award_for_concluded_thread(self):
        from evennia_plots.collectors import collect_thread_bonuses

        thread, now = self._make_concluded_thread_with_bonus(bonus=3)
        PlotParticipant.objects.create(
            thread=thread, character=self.char1, character_name=self.char1.key
        )
        awards = list(collect_thread_bonuses(window_end=now + timedelta(hours=1)))
        self.assertGreater(len(awards), 0)
        self.assertEqual(awards[0].character_id, self.char1.pk)

    def test_creates_plot_bonus_credit(self):
        from evennia_plots.collectors import collect_thread_bonuses

        thread, now = self._make_concluded_thread_with_bonus(bonus=2)
        PlotParticipant.objects.create(
            thread=thread, character=self.char1, character_name=self.char1.key
        )
        list(collect_thread_bonuses(window_end=now + timedelta(hours=1)))
        self.assertTrue(
            PlotBonusCredit.objects.filter(thread=thread, character_id=self.char1.pk).exists()
        )

    def test_idempotent_when_xplog_already_has_credit(self):
        from evennia_xp.models import XPLog

        from evennia_plots.collectors import collect_thread_bonuses

        thread, now = self._make_concluded_thread_with_bonus(bonus=2)
        PlotParticipant.objects.create(
            thread=thread, character=self.char1, character_name=self.char1.key
        )
        window_end = now + timedelta(hours=1)

        # First run creates the credit and yields awards.
        awards_first = list(collect_thread_bonuses(window_end))
        self.assertGreater(len(awards_first), 0)
        credit = PlotBonusCredit.objects.get(thread=thread, character_id=self.char1.pk)

        # Simulate the batch having written the XPLog for that credit.
        XPLog.objects.create(
            character_id=self.char1.pk,
            source_type=XPLog.SourceType.THREAD_BONUS,
            source_ref_id=credit.pk,
            amount=Decimal("2"),
        )

        # Second run with the credit already in XPLog → no awards.
        awards_second = list(collect_thread_bonuses(window_end))
        self.assertEqual(len(awards_second), 0)

    def test_downtime_arc_suppresses_yield(self):
        from evennia_plots.collectors import collect_thread_bonuses

        arc = _make_arc(creator=self.char1, arc_type=PlotArc.ArcType.DOWNTIME)
        arc.is_current = True
        arc.save(update_fields=["is_current"])

        thread, now = self._make_concluded_thread_with_bonus(bonus=3)
        PlotParticipant.objects.create(
            thread=thread, character=self.char1, character_name=self.char1.key
        )
        # Downtime arc → thread_bonus multiplier is 0 → bonus_xp_should_award=False
        awards = list(collect_thread_bonuses(window_end=now + timedelta(hours=1)))
        self.assertEqual(len(awards), 0)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


class TestCmdPlot(EvenniaCommandTest):
    def test_create_makes_thread(self):
        before = PlotThread.objects.count()
        self.call(CmdPlot(), "/create My Thread", caller=self.char1)
        self.assertEqual(PlotThread.objects.count(), before + 1)

    def test_create_outputs_success_message(self):
        result = self.call(CmdPlot(), "/create My Thread", caller=self.char1)
        self.assertIn("Created", result)
        self.assertIn("My Thread", result)

    def test_create_requires_name(self):
        result = self.call(CmdPlot(), "/create", caller=self.char1)
        self.assertIn("Usage", result)

    def test_conclude_sets_thread_status(self):
        thread = _make_thread("ConcTest", creator=self.char1, status="active")
        self.call(CmdPlot(), f"/conclude #{thread.plot_number}", caller=self.char1)
        thread.refresh_from_db()
        self.assertEqual(thread.status, PlotThread.Status.CONCLUDED)

    def test_conclude_outputs_bonus_xp(self):
        thread = _make_thread("BonusTest", creator=self.char1, status="active")
        result = self.call(CmdPlot(), f"/conclude #{thread.plot_number}", caller=self.char1)
        self.assertIn("Bonus XP", result)

    def test_invite_adds_character_to_invite_list(self):
        thread = _make_thread("InviteTest", creator=self.char1, status="active")
        self.call(CmdPlot(), f"/invite #{thread.plot_number}={self.char2.key}", caller=self.char1)
        thread.refresh_from_db()
        self.assertIn(self.char2, thread.invited_characters.all())

    def test_bare_list_returns_non_empty_output(self):
        _make_thread("Visible", creator=self.char1, status="active", privacy="public")
        result = self.call(CmdPlot(), "", caller=self.char1)
        self.assertTrue(len(result) > 0)

    def test_screenreader_fallback_non_empty(self):
        _make_thread("SR Thread", creator=self.char1, status="active", privacy="public")
        with patch("evennia_plots.commands.uses_screenreader", return_value=True):
            result = self.call(CmdPlot(), "", caller=self.char1)
        self.assertTrue(len(result) > 0)


class TestCmdArc(EvenniaCommandTest):
    def test_setcurrent_sets_is_current(self):
        arc = _make_arc("Current Arc", creator=self.char1)
        self.call(CmdArc(), f"/current #{arc.arc_number}", caller=self.char1)
        arc.refresh_from_db()
        self.assertTrue(arc.is_current)

    def test_setcurrent_demotes_existing_current(self):
        old = _make_arc("Old", creator=self.char1)
        old.is_current = True
        old.save(update_fields=["is_current"])

        new = _make_arc("New", creator=self.char1)
        self.call(CmdArc(), f"/current #{new.arc_number}", caller=self.char1)

        old.refresh_from_db()
        new.refresh_from_db()
        self.assertFalse(old.is_current)
        self.assertTrue(new.is_current)

    def test_setcurrent_non_staff_denied(self):
        arc = _make_arc("Restricted", creator=self.char1)
        result = self.call(CmdArc(), f"/current #{arc.arc_number}", caller=self.char2)
        self.assertIn("permission", result.lower())

    def test_create_arc_makes_arc(self):
        before = PlotArc.objects.count()
        self.call(CmdArc(), "/create New Arc", caller=self.char1)
        self.assertEqual(PlotArc.objects.count(), before + 1)


class TestCmdHook(EvenniaCommandTest):
    def test_hook_appends_to_thread_hook_log(self):
        thread = _make_thread("HookTest", creator=self.char1, status="active")
        self.call(CmdHook(), f"{self.char2.key}=#{thread.plot_number}", caller=self.char1)
        thread.refresh_from_db()
        self.assertEqual(len(thread.hook_log), 1)

    def test_hook_records_staff_and_target_names(self):
        thread = _make_thread("HookLog", creator=self.char1, status="active")
        self.call(CmdHook(), f"{self.char2.key}=#{thread.plot_number}", caller=self.char1)
        thread.refresh_from_db()
        entry = thread.hook_log[0]
        self.assertIn("staff", entry)
        self.assertIn("target", entry)

    def test_hook_non_staff_denied(self):
        thread = _make_thread("HookDenied", creator=self.char1, status="active")
        result = self.call(CmdHook(), f"{self.char1.key}=#{thread.plot_number}", caller=self.char2)
        self.assertIn("permission", result.lower())

    def test_hook_rejects_private_thread(self):
        thread = _make_thread("PrivateHook", creator=self.char1, status="active", privacy="private")
        result = self.call(CmdHook(), f"{self.char2.key}=#{thread.plot_number}", caller=self.char1)
        self.assertIn("private", result.lower())


# ---------------------------------------------------------------------------
# Web privacy
# ---------------------------------------------------------------------------


class TestWebPrivacy(EvenniaTest):
    def _anon_request(self, path="/"):
        from django.contrib.auth.models import AnonymousUser

        req = RequestFactory().get(path)
        req.user = AnonymousUser()
        return req

    def test_private_thread_excluded_from_detail_queryset(self):
        from evennia_plots.views import PlotDetailView

        private = _make_thread("Secret", creator=self.char1, status="active", privacy="private")
        view = PlotDetailView()
        view.request = self._anon_request(f"/plots/{private.pk}/")
        self.assertFalse(view.get_queryset().filter(pk=private.pk).exists())

    def test_public_thread_included_in_detail_queryset(self):
        from evennia_plots.views import PlotDetailView

        public = _make_thread("Open", creator=self.char1, status="active", privacy="public")
        view = PlotDetailView()
        view.request = self._anon_request(f"/plots/{public.pk}/")
        self.assertTrue(view.get_queryset().filter(pk=public.pk).exists())

    def test_invite_only_thread_included_in_detail_queryset(self):
        from evennia_plots.views import PlotDetailView

        invite = _make_thread("Invite", creator=self.char1, status="active", privacy="invite_only")
        view = PlotDetailView()
        view.request = self._anon_request(f"/plots/{invite.pk}/")
        self.assertTrue(view.get_queryset().filter(pk=invite.pk).exists())


# ---------------------------------------------------------------------------
# Template compile checks (14 templates)
# ---------------------------------------------------------------------------


class TestTemplateCompile(EvenniaTest):
    """All 14 shipped evennia_plots templates parse without error."""

    TEMPLATES = [  # noqa: RUF012
        "evennia_plots/plot_list.html",
        "evennia_plots/plot_detail.html",
        "evennia_plots/plot_arc_list.html",
        "evennia_plots/plot_arc_detail.html",
        "evennia_plots/plot_tags.html",
        "evennia_plots/plot_tag_create_form.html",
        "evennia_plots/plot_form.html",
        "evennia_plots/plot_edit_form.html",
        "evennia_plots/plot_invite_form.html",
        "evennia_plots/plot_update_form.html",
        "evennia_plots/plot_update_edit_form.html",
        "evennia_plots/plot_update_history.html",
        "evennia_plots/plot_update_diff.html",
        "evennia_plots/plot_arc_form.html",
    ]

    def test_all_templates_compile(self):
        from django.template.loader import get_template

        for name in self.TEMPLATES:
            with self.subTest(template=name):
                self.assertIsNotNone(get_template(name))


# ---------------------------------------------------------------------------
# API privacy (requires djangorestframework)
# ---------------------------------------------------------------------------


class TestAPIPrivacy(EvenniaTest):
    def setUp(self):
        super().setUp()
        try:
            from rest_framework.test import APIRequestFactory, force_authenticate

            self._api_factory = APIRequestFactory()
            self._force_authenticate = force_authenticate
            self._no_drf = False
        except ImportError:
            self._no_drf = True

    def _skip_if_no_drf(self):
        if self._no_drf:
            self.skipTest("requires djangorestframework")

    def _get_list_ids(self, user):
        from evennia_plots.api.views import PlotThreadViewSet

        request = self._api_factory.get("/api/v1/plots/")
        self._force_authenticate(request, user=user)
        view = PlotThreadViewSet.as_view({"get": "list"})
        response = view(request)
        data = response.data
        if isinstance(data, dict) and "results" in data:
            return {item["id"] for item in data["results"]}
        return {item["id"] for item in data}

    def test_private_thread_hidden_from_non_staff(self):
        self._skip_if_no_drf()
        _make_thread("Public", creator=self.char1, status="active", privacy="public")
        private = _make_thread("Secret", creator=self.char1, status="active", privacy="private")
        ids = self._get_list_ids(user=self.account2)
        self.assertNotIn(private.pk, ids)

    def test_proposed_thread_hidden_from_non_staff(self):
        self._skip_if_no_drf()
        proposed = _make_thread("Proposed", creator=self.char1, privacy="public")
        ids = self._get_list_ids(user=self.account2)
        self.assertNotIn(proposed.pk, ids)

    def test_active_public_thread_visible_to_non_staff(self):
        self._skip_if_no_drf()
        active = _make_thread(
            "Active Public", creator=self.char1, status="active", privacy="public"
        )
        ids = self._get_list_ids(user=self.account2)
        self.assertIn(active.pk, ids)

    def test_staff_sees_private_threads(self):
        self._skip_if_no_drf()
        private = _make_thread(
            "StaffSecret", creator=self.char1, status="active", privacy="private"
        )
        ids = self._get_list_ids(user=self.account)
        self.assertIn(private.pk, ids)
