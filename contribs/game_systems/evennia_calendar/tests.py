# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_calendar contrib.

Uses EvenniaTest which provides:
    self.char1 (key="Char"), self.char2 (key="Char2") — both in self.room1
    self.account, self.account2

Run with:
    evennia test evennia_calendar --settings test_calendar_settings
"""

import datetime
import random
from typing import ClassVar
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest

from evennia_calendar.models import (
    RSVP,
    CalendarEvent,
    ClusterRSVP,
    ClusterRSVPPreference,
    EventCluster,
    EventExclusion,
    EventTag,
    PriorityToken,
)
from evennia_calendar.scheduler import (
    expire_unconfirmed,
    issue_post_event_tokens,
    promote_waitlist,
    run_cluster_lottery,
    run_lottery,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _future(hours=24):
    return timezone.now() + datetime.timedelta(hours=hours)


def _past(hours=1):
    return timezone.now() - datetime.timedelta(hours=hours)


def _make_event(creator, title="Test Event", hours=48, **kwargs):
    return CalendarEvent.create_event(
        creator=creator,
        title=title,
        scheduled_time=_future(hours),
        **kwargs,
    )


def _make_staff_event(creator, cap=5, hours=96, **kwargs):
    return CalendarEvent.create_event(
        creator=creator,
        title="Staff Event",
        scheduled_time=_future(hours),
        is_staff_event=True,
        participant_cap=cap,
        **kwargs,
    )


def _make_cluster(creator, title="Test Cluster", locked=False):
    c = EventCluster.objects.create(title=title, creator=creator, creator_name=creator.key)
    if locked:
        c.is_locked = True
        c.save(update_fields=["is_locked"])
    return c


def _rsvp_lottery(event, character):
    return RSVP.objects.create(
        event=event,
        character=character,
        character_name=character.key,
        status=RSVP.Status.LOTTERY_ENTERED,
    )


def _seeded_rng(seed=42):
    return random.Random(seed)


# ---------------------------------------------------------------------------
# __init__.py exports
# ---------------------------------------------------------------------------


class TestInitExports(EvenniaTest):
    def test_version_exported(self):
        import evennia_calendar

        self.assertEqual(evennia_calendar.__version__, "0.1.0")

    def test_signals_eagerly_exported(self):
        """Signals must be plain Signal objects importable without AppRegistryNotReady."""
        from django.dispatch import Signal

        import evennia_calendar

        for name in [
            "event_created",
            "event_cancelled",
            "event_starting_soon",
            "lottery_drawn",
            "lottery_selected",
            "lottery_confirmation_expired",
            "rsvp_status_changed",
            "waitlist_promoted",
            "cluster_drawn",
            "cluster_seat_assigned",
        ]:
            self.assertIsInstance(
                getattr(evennia_calendar, name),
                Signal,
                msg=f"evennia_calendar.{name} should be a Signal",
            )

    def test_models_lazily_exported(self):
        """Model classes are accessible via __getattr__."""
        import evennia_calendar

        for name in [
            "CalendarEvent",
            "EventCluster",
            "RSVP",
            "ClusterRSVP",
            "ClusterRSVPPreference",
            "EventTag",
            "PriorityToken",
            "EventExclusion",
        ]:
            obj = getattr(evennia_calendar, name)
            self.assertTrue(hasattr(obj, "objects"), msg=f"{name} should be a model")

    def test_enum_aliases_exported(self):
        """Inner-class enums are accessible via top-level aliases."""
        import evennia_calendar

        self.assertIs(evennia_calendar.Emphasis, CalendarEvent.Emphasis)
        self.assertIs(evennia_calendar.ClusterStatus, ClusterRSVP.Status)
        self.assertIs(evennia_calendar.RSVPStatus, RSVP.Status)
        self.assertIs(evennia_calendar.TokenScope, PriorityToken.Scope)


# ---------------------------------------------------------------------------
# EventTag
# ---------------------------------------------------------------------------


class TestEventTag(EvenniaTest):
    def test_create_tag(self):
        tag = EventTag.objects.create(name="Arcane")
        self.assertEqual(str(tag), "Arcane")

    def test_tag_unique(self):
        EventTag.objects.create(name="Military")
        with transaction.atomic(), self.assertRaises(IntegrityError):
            EventTag.objects.create(name="Military")


# ---------------------------------------------------------------------------
# EventCluster
# ---------------------------------------------------------------------------


class TestEventCluster(EvenniaTest):
    def test_create_cluster(self):
        cluster = _make_cluster(self.char1)
        self.assertEqual(cluster.creator, self.char1)
        self.assertFalse(cluster.is_locked)
        self.assertFalse(cluster.has_run)

    def test_draw_time_is_72h_before_earliest_member(self):
        cluster = _make_cluster(self.char1)
        ev1 = _make_staff_event(self.char1, hours=100, cluster=cluster)
        _make_staff_event(self.char1, hours=200, cluster=cluster)
        draw_time = cluster.draw_time
        expected = ev1.scheduled_time - datetime.timedelta(hours=72)
        self.assertAlmostEqual(draw_time.timestamp(), expected.timestamp(), delta=1)

    def test_draw_time_none_for_empty_cluster(self):
        cluster = _make_cluster(self.char1)
        self.assertIsNone(cluster.draw_time)

    def test_has_run_true_after_draw(self):
        cluster = _make_cluster(self.char1, locked=True)
        ev = _make_staff_event(self.char1, hours=96, cluster=cluster)
        ev.lottery_drawn_at = timezone.now()
        ev.save(update_fields=["lottery_drawn_at"])
        self.assertTrue(cluster.has_run)

    def test_clean_rejects_mixed_staff_flags(self):
        from django.core.exceptions import ValidationError

        cluster = _make_cluster(self.char1)
        _make_event(self.char1, cluster=cluster, is_staff_event=False)
        _make_event(self.char1, cluster=cluster, is_staff_event=True)
        with self.assertRaises(ValidationError):
            cluster.clean()

    def test_clean_rejects_mixed_scheduled_times(self):
        """Cluster members must share scheduled_time (parallel events)."""
        from django.core.exceptions import ValidationError

        cluster = _make_cluster(self.char1)
        _make_event(self.char1, cluster=cluster, hours=48)
        _make_event(self.char1, cluster=cluster, hours=72)
        with self.assertRaises(ValidationError):
            cluster.clean()

    def test_clean_accepts_uniform_members(self):
        cluster = _make_cluster(self.char1)
        when = _future(48)
        CalendarEvent.create_event(
            creator=self.char1, title="A", scheduled_time=when, cluster=cluster
        )
        CalendarEvent.create_event(
            creator=self.char1, title="B", scheduled_time=when, cluster=cluster
        )
        cluster.clean()  # no ValidationError raised


# ---------------------------------------------------------------------------
# CalendarEvent
# ---------------------------------------------------------------------------


class TestCalendarEvent(EvenniaTest):
    def test_create_event_factory(self):
        ev = _make_event(self.char1)
        self.assertEqual(ev.creator, self.char1)
        self.assertEqual(ev.creator_name, self.char1.key)
        self.assertFalse(ev.is_cancelled)
        self.assertFalse(ev.is_staff_event)

    def test_is_past_false_for_future(self):
        ev = _make_event(self.char1, hours=24)
        self.assertFalse(ev.is_past)

    def test_is_past_true_for_past(self):
        ev = CalendarEvent.create_event(
            creator=self.char1, title="Past", scheduled_time=_past(hours=2)
        )
        self.assertTrue(ev.is_past)

    def test_lottery_draw_time_is_72h_before(self):
        ev = _make_staff_event(self.char1, hours=96)
        expected = ev.scheduled_time - datetime.timedelta(hours=72)
        self.assertEqual(ev.lottery_draw_time, expected)

    def test_lottery_draw_time_none_for_player_event(self):
        ev = _make_event(self.char1)
        self.assertIsNone(ev.lottery_draw_time)

    def test_confirmation_deadline_is_48h_before(self):
        ev = _make_event(self.char1, hours=72)
        expected = ev.scheduled_time - datetime.timedelta(hours=48)
        self.assertEqual(ev.confirmation_deadline, expected)

    def test_seats_remaining_none_for_unlimited(self):
        ev = _make_event(self.char1)
        self.assertIsNone(ev.seats_remaining)

    def test_seats_remaining_counts_confirmed(self):
        ev = _make_event(self.char1, participant_cap=3)
        RSVP.objects.create(
            event=ev,
            character=self.char1,
            character_name=self.char1.key,
            status=RSVP.Status.CONFIRMED,
        )
        self.assertEqual(ev.seats_remaining, 2)

    def test_is_clustered_when_cluster_set(self):
        cluster = _make_cluster(self.char1)
        ev = _make_event(self.char1, cluster=cluster)
        self.assertTrue(ev.is_clustered)

    def test_cancel_sets_flag(self):
        ev = _make_event(self.char1)
        ev.cancel()
        self.assertTrue(ev.is_cancelled)

    def test_str_contains_title(self):
        ev = _make_event(self.char1, title="Founders Ball")
        self.assertIn("Founders Ball", str(ev))


# ---------------------------------------------------------------------------
# ClusterRSVP + ClusterRSVPPreference
# ---------------------------------------------------------------------------


class TestClusterRSVP(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.cluster = _make_cluster(self.char1, locked=True)
        self.ev1 = _make_staff_event(self.char1, hours=100, cluster=self.cluster)
        self.ev2 = _make_staff_event(self.char1, hours=200, cluster=self.cluster)

    def test_create_cluster_rsvp(self):
        crsvp = ClusterRSVP.objects.create(
            cluster=self.cluster,
            character=self.char2,
            character_name=self.char2.key,
        )
        self.assertEqual(crsvp.status, ClusterRSVP.Status.PENDING)

    def test_unique_per_cluster_character(self):
        ClusterRSVP.objects.create(
            cluster=self.cluster,
            character=self.char2,
            character_name=self.char2.key,
        )
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ClusterRSVP.objects.create(
                cluster=self.cluster,
                character=self.char2,
                character_name=self.char2.key,
            )

    def test_preference_rank_unique_per_rsvp(self):
        crsvp = ClusterRSVP.objects.create(
            cluster=self.cluster,
            character=self.char2,
            character_name=self.char2.key,
        )
        ClusterRSVPPreference.objects.create(cluster_rsvp=crsvp, event=self.ev1, rank=1)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ClusterRSVPPreference.objects.create(cluster_rsvp=crsvp, event=self.ev2, rank=1)

    def test_get_ordered_preferences(self):
        crsvp = ClusterRSVP.objects.create(
            cluster=self.cluster,
            character=self.char2,
            character_name=self.char2.key,
        )
        ClusterRSVPPreference.objects.create(cluster_rsvp=crsvp, event=self.ev2, rank=2)
        ClusterRSVPPreference.objects.create(cluster_rsvp=crsvp, event=self.ev1, rank=1)
        prefs = list(crsvp.get_ordered_preferences())
        self.assertEqual(prefs[0].event, self.ev1)
        self.assertEqual(prefs[1].event, self.ev2)


# ---------------------------------------------------------------------------
# RSVP
# ---------------------------------------------------------------------------


class TestRSVP(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.event = _make_event(self.char1, participant_cap=3)

    def test_confirm_sets_status(self):
        rsvp = RSVP.objects.create(
            event=self.event,
            character=self.char2,
            character_name=self.char2.key,
            status=RSVP.Status.LOTTERY_SELECTED,
        )
        rsvp.confirm()
        self.assertEqual(rsvp.status, RSVP.Status.CONFIRMED)

    def test_release_sets_status(self):
        rsvp = RSVP.objects.create(
            event=self.event,
            character=self.char2,
            character_name=self.char2.key,
            status=RSVP.Status.LOTTERY_SELECTED,
        )
        rsvp.release()
        self.assertEqual(rsvp.status, RSVP.Status.RELEASED)

    def test_unique_per_event_character(self):
        RSVP.objects.create(
            event=self.event,
            character=self.char2,
            character_name=self.char2.key,
            status=RSVP.Status.CONFIRMED,
        )
        with transaction.atomic(), self.assertRaises(IntegrityError):
            RSVP.objects.create(
                event=self.event,
                character=self.char2,
                character_name=self.char2.key,
                status=RSVP.Status.CONFIRMED,
            )


# ---------------------------------------------------------------------------
# PriorityToken
# ---------------------------------------------------------------------------


class TestPriorityToken(EvenniaTest):
    def test_is_redeemed_false_initially(self):
        ev = _make_staff_event(self.char1)
        token = PriorityToken.objects.create(
            character=self.char2,
            character_name=self.char2.key,
            source_event=ev,
            scope=PriorityToken.Scope.EVENT,
        )
        self.assertFalse(token.is_redeemed)

    def test_is_redeemed_true_after_redemption(self):
        ev = _make_staff_event(self.char1)
        token = PriorityToken.objects.create(
            character=self.char2,
            character_name=self.char2.key,
            source_event=ev,
            scope=PriorityToken.Scope.EVENT,
            redeemed_at=timezone.now(),
        )
        self.assertTrue(token.is_redeemed)

    def test_str_contains_scope(self):
        token = PriorityToken.objects.create(
            character=self.char2,
            character_name=self.char2.key,
            scope=PriorityToken.Scope.CLUSTER_RANK1,
        )
        self.assertIn("Cluster", str(token))


# ---------------------------------------------------------------------------
# EventExclusion
# ---------------------------------------------------------------------------


class TestEventExclusion(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.ev1 = _make_event(self.char1, title="Event A")
        self.ev2 = _make_event(self.char1, title="Event B")

    def test_canonical_ordering_enforced(self):
        high, low = sorted([self.ev1, self.ev2], key=lambda e: e.pk, reverse=True)
        ex = EventExclusion.objects.create(
            event_a=high,
            event_b=low,
            created_by=self.char1,
            creator_name=self.char1.key,
        )
        self.assertLessEqual(ex.event_a_id, ex.event_b_id)

    def test_are_exclusive_returns_true(self):
        EventExclusion.objects.create(
            event_a=self.ev1,
            event_b=self.ev2,
            created_by=self.char1,
            creator_name=self.char1.key,
        )
        self.assertTrue(EventExclusion.are_exclusive(self.ev1, self.ev2))
        self.assertTrue(EventExclusion.are_exclusive(self.ev2, self.ev1))

    def test_are_exclusive_returns_false_when_unlinked(self):
        self.assertFalse(EventExclusion.are_exclusive(self.ev1, self.ev2))

    def test_get_exclusions_for(self):
        EventExclusion.objects.create(
            event_a=self.ev1,
            event_b=self.ev2,
            created_by=self.char1,
            creator_name=self.char1.key,
        )
        result = list(EventExclusion.get_exclusions_for(self.ev1))
        self.assertIn(self.ev2, result)


# ---------------------------------------------------------------------------
# Scheduler: run_lottery (standalone)
# ---------------------------------------------------------------------------


class TestRunLottery(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.event = _make_staff_event(self.char1, cap=2, hours=96)

    def test_lottery_selects_up_to_cap(self):
        _rsvp_lottery(self.event, self.char1)
        _rsvp_lottery(self.event, self.char2)
        run_lottery(self.event, rng=_seeded_rng())
        selected = self.event.rsvps.filter(status=RSVP.Status.LOTTERY_SELECTED).count()
        self.assertEqual(selected, 2)

    def test_lottery_leaves_extras_entered(self):
        from evennia.utils.create import create_object

        char3 = create_object("typeclasses.characters.Character", key="Char3")
        _rsvp_lottery(self.event, self.char1)
        _rsvp_lottery(self.event, self.char2)
        _rsvp_lottery(self.event, char3)
        run_lottery(self.event, rng=_seeded_rng())
        entered = self.event.rsvps.filter(status=RSVP.Status.LOTTERY_ENTERED).count()
        self.assertEqual(entered, 1)

    def test_lottery_sets_drawn_at(self):
        _rsvp_lottery(self.event, self.char2)
        run_lottery(self.event, rng=_seeded_rng())
        self.event.refresh_from_db()
        self.assertIsNotNone(self.event.lottery_drawn_at)

    def test_lottery_idempotent(self):
        _rsvp_lottery(self.event, self.char2)
        run_lottery(self.event, rng=_seeded_rng())
        first_drawn_at = self.event.lottery_drawn_at
        run_lottery(self.event, rng=_seeded_rng())
        self.event.refresh_from_db()
        self.assertEqual(self.event.lottery_drawn_at, first_drawn_at)

    def test_token_holder_seated_first(self):
        PriorityToken.objects.create(
            character=self.char2,
            character_name=self.char2.key,
            scope=PriorityToken.Scope.EVENT,
        )
        _rsvp_lottery(self.event, self.char1)
        _rsvp_lottery(self.event, self.char2)
        self.event.participant_cap = 1
        self.event.save(update_fields=["participant_cap"])
        run_lottery(self.event, rng=_seeded_rng())
        char2_rsvp = self.event.rsvps.get(character=self.char2)
        self.assertEqual(char2_rsvp.status, RSVP.Status.LOTTERY_SELECTED)

    def test_lottery_skips_non_staff_event(self):
        ev = _make_event(self.char1)
        _rsvp_lottery(ev, self.char2)
        run_lottery(ev)
        rsvp = ev.rsvps.get(character=self.char2)
        self.assertEqual(rsvp.status, RSVP.Status.LOTTERY_ENTERED)

    def test_lottery_skips_clustered_event(self):
        cluster = _make_cluster(self.char1)
        ev = _make_staff_event(self.char1, hours=96, cluster=cluster)
        _rsvp_lottery(ev, self.char2)
        run_lottery(ev)
        rsvp = ev.rsvps.get(character=self.char2)
        self.assertEqual(rsvp.status, RSVP.Status.LOTTERY_ENTERED)


# ---------------------------------------------------------------------------
# Scheduler: run_cluster_lottery
# ---------------------------------------------------------------------------


class TestRunClusterLottery(EvenniaTest):
    def _setup_cluster(self, caps=(2, 2)):
        cluster = _make_cluster(self.char1, locked=True)
        events = []
        for i, cap in enumerate(caps):
            ev = _make_staff_event(self.char1, cap=cap, hours=100 + i * 10, cluster=cluster)
            events.append(ev)
        return cluster, events

    def _add_crsvp(self, cluster, character, ranked_events):
        crsvp = ClusterRSVP.objects.create(
            cluster=cluster,
            character=character,
            character_name=character.key,
        )
        for rank, ev in enumerate(ranked_events, start=1):
            ClusterRSVPPreference.objects.create(cluster_rsvp=crsvp, event=ev, rank=rank)
        return crsvp

    def test_players_seated_in_rank_order(self):
        cluster, (ev1, ev2) = self._setup_cluster()
        self._add_crsvp(cluster, self.char2, [ev1, ev2])
        run_cluster_lottery(cluster, rng=_seeded_rng())
        crsvp = ClusterRSVP.objects.get(cluster=cluster, character=self.char2)
        self.assertEqual(crsvp.status, ClusterRSVP.Status.SEATED)
        concrete = crsvp.concrete_rsvps.first()
        self.assertIsNotNone(concrete)
        self.assertEqual(concrete.event, ev1)

    def test_overflow_falls_to_rank2(self):
        from evennia.utils.create import create_object

        cluster, (ev1, ev2) = self._setup_cluster(caps=(1, 2))
        char3 = create_object("typeclasses.characters.Character", key="Char3")
        self._add_crsvp(cluster, self.char2, [ev1, ev2])
        self._add_crsvp(cluster, char3, [ev1, ev2])
        run_cluster_lottery(cluster, rng=_seeded_rng(seed=1))
        statuses = set(ClusterRSVP.objects.filter(cluster=cluster).values_list("status", flat=True))
        self.assertIn(ClusterRSVP.Status.SEATED, statuses)
        self.assertNotIn(ClusterRSVP.Status.UNSEATED, statuses)

    def test_unseated_gets_token(self):
        from evennia.utils.create import create_object

        cluster, (ev1,) = self._setup_cluster(caps=(1,))
        char3 = create_object("typeclasses.characters.Character", key="Char3")
        self._add_crsvp(cluster, self.char2, [ev1])
        self._add_crsvp(cluster, char3, [ev1])
        run_cluster_lottery(cluster, rng=_seeded_rng(seed=42))
        unseated = ClusterRSVP.objects.filter(cluster=cluster, status=ClusterRSVP.Status.UNSEATED)
        self.assertEqual(unseated.count(), 1)
        token = PriorityToken.objects.filter(
            source_cluster=cluster, scope=PriorityToken.Scope.CLUSTER_RANK1
        )
        self.assertGreaterEqual(token.count(), 1)

    def test_cluster_draw_idempotent(self):
        cluster, (ev1,) = self._setup_cluster(caps=(2,))
        self._add_crsvp(cluster, self.char2, [ev1])
        run_cluster_lottery(cluster, rng=_seeded_rng())
        ev1.refresh_from_db()
        drawn_at = ev1.lottery_drawn_at
        run_cluster_lottery(cluster, rng=_seeded_rng())
        ev1.refresh_from_db()
        self.assertEqual(ev1.lottery_drawn_at, drawn_at)

    def test_cluster_draw_refuses_unlocked(self):
        cluster = _make_cluster(self.char1, locked=False)
        ev1 = _make_staff_event(self.char1, hours=96, cluster=cluster)
        self._add_crsvp(cluster, self.char2, [ev1])
        run_cluster_lottery(cluster, rng=_seeded_rng())
        ev1.refresh_from_db()
        self.assertIsNone(ev1.lottery_drawn_at)

    def test_token_preseat_rank1(self):
        cluster, (ev1, ev2) = self._setup_cluster(caps=(1, 2))
        PriorityToken.objects.create(
            character=self.char2,
            character_name=self.char2.key,
            source_cluster=cluster,
            scope=PriorityToken.Scope.CLUSTER_RANK1,
        )
        self._add_crsvp(cluster, self.char2, [ev1, ev2])
        run_cluster_lottery(cluster, rng=_seeded_rng())
        crsvp = ClusterRSVP.objects.get(cluster=cluster, character=self.char2)
        concrete = crsvp.concrete_rsvps.first()
        self.assertEqual(concrete.event, ev1)

    def test_sets_lottery_drawn_at_on_all_members(self):
        cluster, (ev1, ev2) = self._setup_cluster()
        run_cluster_lottery(cluster, rng=_seeded_rng())
        ev1.refresh_from_db()
        ev2.refresh_from_db()
        self.assertIsNotNone(ev1.lottery_drawn_at)
        self.assertIsNotNone(ev2.lottery_drawn_at)

    def test_double_issuance_guard(self):
        """Token holder bumped to rank-2 gets exactly one replacement token, not two."""
        from evennia.utils.create import create_object

        cluster, (ev1, ev2) = self._setup_cluster(caps=(1, 2))
        char3 = create_object("typeclasses.characters.Character", key="Char3")
        PriorityToken.objects.create(
            character=self.char2,
            character_name=self.char2.key,
            source_cluster=cluster,
            scope=PriorityToken.Scope.CLUSTER_RANK1,
        )
        PriorityToken.objects.create(
            character=char3,
            character_name=char3.key,
            source_cluster=cluster,
            scope=PriorityToken.Scope.CLUSTER_RANK1,
        )
        self._add_crsvp(cluster, self.char2, [ev1, ev2])
        self._add_crsvp(cluster, char3, [ev1, ev2])
        run_cluster_lottery(cluster, rng=_seeded_rng())
        total_unredeemed = PriorityToken.objects.filter(
            scope=PriorityToken.Scope.CLUSTER_RANK1, redeemed_at__isnull=True
        ).count()
        self.assertEqual(total_unredeemed, 1)


# ---------------------------------------------------------------------------
# Scheduler: expire_unconfirmed
# ---------------------------------------------------------------------------


class TestExpireUnconfirmed(EvenniaTest):
    def test_releases_lottery_selected(self):
        ev = _make_staff_event(self.char1, cap=2, hours=96)
        rsvp = RSVP.objects.create(
            event=ev,
            character=self.char2,
            character_name=self.char2.key,
            status=RSVP.Status.LOTTERY_SELECTED,
        )
        expire_unconfirmed(ev)
        rsvp.refresh_from_db()
        self.assertEqual(rsvp.status, RSVP.Status.RELEASED)

    def test_releases_invited(self):
        ev = _make_event(self.char1, participant_cap=3)
        rsvp = RSVP.objects.create(
            event=ev,
            character=self.char2,
            character_name=self.char2.key,
            status=RSVP.Status.INVITED,
        )
        expire_unconfirmed(ev)
        rsvp.refresh_from_db()
        self.assertEqual(rsvp.status, RSVP.Status.RELEASED)

    def test_leaves_confirmed_alone(self):
        ev = _make_event(self.char1)
        rsvp = RSVP.objects.create(
            event=ev,
            character=self.char2,
            character_name=self.char2.key,
            status=RSVP.Status.CONFIRMED,
        )
        expire_unconfirmed(ev)
        rsvp.refresh_from_db()
        self.assertEqual(rsvp.status, RSVP.Status.CONFIRMED)


# ---------------------------------------------------------------------------
# Scheduler: issue_post_event_tokens
# ---------------------------------------------------------------------------


class TestIssuePostEventTokens(EvenniaTest):
    def test_issues_token_to_lottery_entered(self):
        ev = _make_staff_event(self.char1, hours=96)
        _rsvp_lottery(ev, self.char2)
        issue_post_event_tokens(ev)
        token = PriorityToken.objects.filter(
            character=self.char2,
            source_event=ev,
            scope=PriorityToken.Scope.EVENT,
        )
        self.assertTrue(token.exists())

    def test_skips_clustered_events(self):
        cluster = _make_cluster(self.char1, locked=True)
        ev = _make_staff_event(self.char1, hours=96, cluster=cluster)
        _rsvp_lottery(ev, self.char2)
        issue_post_event_tokens(ev)
        self.assertEqual(PriorityToken.objects.count(), 0)

    def test_skips_non_staff_events(self):
        ev = _make_event(self.char1)
        RSVP.objects.create(
            event=ev,
            character=self.char2,
            character_name=self.char2.key,
            status=RSVP.Status.LOTTERY_ENTERED,
        )
        issue_post_event_tokens(ev)
        self.assertEqual(PriorityToken.objects.count(), 0)


# ---------------------------------------------------------------------------
# Scheduler: promote_waitlist
# ---------------------------------------------------------------------------


class TestPromoteWaitlist(EvenniaTest):
    def test_promotes_first_waitlisted(self):
        ev = _make_event(self.char1, participant_cap=1)
        RSVP.objects.create(
            event=ev,
            character=self.char1,
            character_name=self.char1.key,
            status=RSVP.Status.CONFIRMED,
        )
        rsvp2 = RSVP.objects.create(
            event=ev,
            character=self.char2,
            character_name=self.char2.key,
            status=RSVP.Status.WAITLISTED,
            waitlist_position=1,
        )
        promote_waitlist(ev, count=1)
        rsvp2.refresh_from_db()
        self.assertEqual(rsvp2.status, RSVP.Status.CONFIRMED)


# ---------------------------------------------------------------------------
# CALENDAR_STAFF_LOCK seam (commands module)
# ---------------------------------------------------------------------------


class TestCalendarStaffLock(EvenniaTest):
    """CALENDAR_STAFF_LOCK is honoured by the shared _is_staff() in commands.py.

    char1 has Developer (Builder+) by default in EvenniaTest; char2 has no
    special perms. Both CmdCalendar and CmdRsvp are in the same merged module.
    """

    def test_default_is_perm_builder(self):
        from evennia_calendar.commands import _is_staff

        self.assertTrue(_is_staff(self.char1))
        self.assertFalse(_is_staff(self.char2))

    def test_nondefault_lock_respected(self):
        from django.test import override_settings

        from evennia_calendar.commands import _is_staff

        with override_settings(CALENDAR_STAFF_LOCK="cmd:perm(Developer)"):
            self.assertTrue(_is_staff(self.char1))
            self.assertFalse(_is_staff(self.char2))

    def test_exception_returns_false(self):
        from django.test import override_settings

        from evennia_calendar.commands import _is_staff

        with override_settings(CALENDAR_STAFF_LOCK="cmd:invalid!!lock??"):
            self.assertFalse(_is_staff(self.char1))


# ---------------------------------------------------------------------------
# Command: CmdCalendar — smoke tests
# ---------------------------------------------------------------------------


class TestCmdCalendar(EvenniaTest):
    def _call_cmd(self, cmdstr, caller=None):
        from evennia.commands.cmdhandler import cmdhandler

        from evennia_calendar.commands import CmdCalendar

        caller = caller or self.char1
        cmd = CmdCalendar()
        cmd.caller = caller
        parts = cmdstr.split(" ", 1)
        cmd.switches = []
        cmd.args = ""
        if "/" in parts[0]:
            sw_part = parts[0].split("/", 1)[1]
            cmd.switches = sw_part.split("/")
        if len(parts) > 1:
            cmd.args = parts[1]
        cmd.func()

    def test_list_upcoming_empty(self):
        from evennia_calendar.commands import CmdCalendar

        cmd = CmdCalendar()
        cmd.caller = self.char1
        cmd.switches = []
        cmd.args = ""
        cmd.func()
        self.assertTrue(True)  # No exception raised.

    def test_view_invalid_id(self):
        from evennia_calendar.commands import CmdCalendar

        cmd = CmdCalendar()
        cmd.caller = self.char1
        cmd.switches = ["view"]
        cmd.args = "notanumber"
        cmd.func()
        # Should send an error message, not raise.
        self.assertTrue(True)

    def test_cancel_requires_owner_or_staff(self):
        ev = _make_event(self.char1)
        from evennia_calendar.commands import CmdCalendar

        cmd = CmdCalendar()
        cmd.caller = self.char2  # not the creator
        cmd.switches = ["cancel"]
        cmd.args = str(ev.pk)
        cmd.func()
        ev.refresh_from_db()
        self.assertFalse(ev.is_cancelled)  # char2 was blocked

    def test_staff_toggle_requires_staff(self):
        ev = _make_event(self.char2)  # char2 owns it
        from evennia_calendar.commands import CmdCalendar

        cmd = CmdCalendar()
        cmd.caller = self.char2  # not staff
        cmd.switches = ["staff"]
        cmd.args = str(ev.pk)
        cmd.func()
        ev.refresh_from_db()
        self.assertFalse(ev.is_staff_event)  # blocked


# ---------------------------------------------------------------------------
# Command: CmdRsvp — anti-favoritism + basic flow
# ---------------------------------------------------------------------------


class TestCmdRsvp(EvenniaTest):
    def _run_rsvp(self, caller, switches, args):
        from evennia_calendar.commands import CmdRsvp

        cmd = CmdRsvp()
        cmd.caller = caller
        cmd.switches = switches
        cmd.args = args
        cmd.func()

    def test_rsvp_open_event_confirms(self):
        ev = _make_event(self.char1)
        self._run_rsvp(self.char2, [], str(ev.pk))
        rsvp = RSVP.objects.filter(event=ev, character=self.char2).first()
        self.assertIsNotNone(rsvp)
        self.assertEqual(rsvp.status, RSVP.Status.CONFIRMED)

    def test_rsvp_capped_full_waitlists(self):
        ev = _make_event(self.char1, participant_cap=1)
        # Fill the seat.
        RSVP.objects.create(
            event=ev,
            character=self.char1,
            character_name=self.char1.key,
            status=RSVP.Status.CONFIRMED,
        )
        self._run_rsvp(self.char2, [], str(ev.pk))
        rsvp = RSVP.objects.filter(event=ev, character=self.char2).first()
        self.assertIsNotNone(rsvp)
        self.assertEqual(rsvp.status, RSVP.Status.WAITLISTED)

    def test_rsvp_staff_event_enters_lottery(self):
        ev = _make_staff_event(self.char1, hours=96)
        self._run_rsvp(self.char2, [], str(ev.pk))
        rsvp = RSVP.objects.filter(event=ev, character=self.char2).first()
        self.assertIsNotNone(rsvp)
        self.assertEqual(rsvp.status, RSVP.Status.LOTTERY_ENTERED)

    def test_invite_blocked_on_staff_event(self):
        """Anti-favoritism: /invite is rejected for staff events."""
        ev = _make_staff_event(self.char1, hours=96)
        self._run_rsvp(self.char1, ["invite"], f"{ev.pk}={self.char2.key}")
        # char2 must NOT have been invited.
        rsvp = RSVP.objects.filter(event=ev, character=self.char2).first()
        self.assertIsNone(rsvp)

    def test_cluster_rsvp_requires_locked_cluster(self):
        cluster = _make_cluster(self.char1, locked=False)
        ev = _make_staff_event(self.char1, hours=96, cluster=cluster)
        self._run_rsvp(self.char2, ["cluster"], f"{cluster.pk}={ev.pk}")
        # ClusterRSVP must NOT be created.
        self.assertFalse(ClusterRSVP.objects.filter(cluster=cluster, character=self.char2).exists())

    def test_cluster_rsvp_creates_preferences(self):
        cluster = _make_cluster(self.char1, locked=True)
        ev1 = _make_staff_event(self.char1, hours=100, cluster=cluster)
        ev2 = _make_staff_event(self.char1, hours=100, cluster=cluster)
        self._run_rsvp(self.char2, ["cluster"], f"{cluster.pk}={ev1.pk},{ev2.pk}")
        crsvp = ClusterRSVP.objects.filter(cluster=cluster, character=self.char2).first()
        self.assertIsNotNone(crsvp)
        prefs = list(crsvp.get_ordered_preferences())
        self.assertEqual(prefs[0].event, ev1)
        self.assertEqual(prefs[1].event, ev2)

    def test_screenreader_fallback_non_empty(self):
        """The uses_screenreader shim returns False and doesn't crash."""
        from evennia_calendar import commands as cmd_mod

        orig = getattr(cmd_mod, "uses_screenreader", None)
        self.assertIsNotNone(orig)
        # The fallback always returns False without crashing.
        self.assertFalse(orig(self.char1))


# ---------------------------------------------------------------------------
# Web: EventInviteView anti-favoritism gate
# ---------------------------------------------------------------------------


class TestEventInviteViewAntiCheating(EvenniaTest):
    def _make_request(self, user=None):
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.post("/calendar/1/invite/")
        request.user = user or self.account
        return request

    def test_invite_view_raises_on_staff_event(self):
        from django.core.exceptions import PermissionDenied

        from evennia_calendar.views import EventInviteView

        ev = _make_staff_event(self.char1, hours=96)

        class MockRequest:
            user = type(
                "U",
                (),
                {
                    "is_authenticated": True,
                    "is_superuser": False,
                    "locks": type(
                        "L",
                        (),
                        {"check_lockstring": staticmethod(lambda a, b: False)},
                    )(),
                },
            )()

        view = EventInviteView()
        view.request = MockRequest()
        view.kwargs = {"pk": ev.pk}
        with self.assertRaises(PermissionDenied):
            view.check_permission(character_id=self.char1.pk, target=ev)


# ---------------------------------------------------------------------------
# Web: ClusterDetailView attaches a per-event RSVP count
# ---------------------------------------------------------------------------


class TestClusterDetailViewCounts(EvenniaTest):
    """The cluster page exposes a per-event RSVP count (event.rsvp_count).

    Regression: the count must be attached to each member event, not passed
    as a dict the template has to index (which needs a non-stdlib filter).
    """

    def _build_cluster(self):
        cluster = _make_cluster(self.char1)
        when = _future(100)
        ev1 = CalendarEvent.create_event(
            creator=self.char1,
            title="Alpha",
            scheduled_time=when,
            is_staff_event=True,
            cluster=cluster,
        )
        ev2 = CalendarEvent.create_event(
            creator=self.char1,
            title="Beta",
            scheduled_time=when,
            is_staff_event=True,
            cluster=cluster,
        )
        RSVP.objects.create(
            event=ev1,
            character=self.char1,
            character_name=self.char1.key,
            status=RSVP.Status.CONFIRMED,
        )
        RSVP.objects.create(
            event=ev1,
            character=self.char2,
            character_name=self.char2.key,
            status=RSVP.Status.CONFIRMED,
        )
        return cluster, ev1, ev2

    def test_per_event_counts_attached(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        from evennia_calendar.views import ClusterDetailView

        cluster, ev1, ev2 = self._build_cluster()
        factory = RequestFactory()
        request = factory.get("/")
        request.user = AnonymousUser()
        response = ClusterDetailView.as_view()(request, pk=cluster.pk)
        self.assertEqual(response.status_code, 200)
        counts = {ev.pk: ev.rsvp_count for ev in response.context_data["member_events"]}
        self.assertEqual(counts[ev1.pk], 2)
        self.assertEqual(counts[ev2.pk], 0)


# ---------------------------------------------------------------------------
# Web: Template compile checks (12 templates)
# ---------------------------------------------------------------------------


class TestTemplateCompile(EvenniaTest):
    """Verify all 12 evennia_calendar templates load without error.

    Uses django.template.loader.get_template — host-independent (no server
    required). This is the per-plan risk-#5 mitigation for the web surface.
    """

    TEMPLATES: ClassVar[list[str]] = [
        "evennia_calendar/calendar_month.html",
        "evennia_calendar/calendar_list.html",
        "evennia_calendar/calendar_detail.html",
        "evennia_calendar/calendar_cluster.html",
        "evennia_calendar/event_form.html",
        "evennia_calendar/event_cancel.html",
        "evennia_calendar/event_invite_form.html",
        "evennia_calendar/event_tag_form.html",
        "evennia_calendar/event_tag_create_form.html",
        "evennia_calendar/cluster_form.html",
        "evennia_calendar/cluster_membership_form.html",
        "evennia_calendar/exclusion_form.html",
    ]

    def test_all_templates_compile(self):
        from django.template.loader import get_template

        for tname in self.TEMPLATES:
            with self.subTest(template=tname):
                t = get_template(tname)
                self.assertIsNotNone(t, f"get_template returned None for {tname}")


# ---------------------------------------------------------------------------
# API: CalendarEventViewSet excludes cancelled events + serializer field set
# ---------------------------------------------------------------------------


class TestCalendarEventViewSet(EvenniaTest):
    def setUp(self):
        super().setUp()
        # Minimal DRF import guard.
        try:
            from rest_framework.test import APIRequestFactory

            self._has_drf = True
        except ImportError:
            self._has_drf = False

    def test_viewset_excludes_cancelled(self):
        if not self._has_drf:
            self.skipTest("djangorestframework not installed")
        from rest_framework.test import APIRequestFactory

        from evennia_calendar.api.views import CalendarEventViewSet

        _make_event(self.char1, title="Active")
        ev_cancelled = _make_event(self.char1, title="Cancelled")
        ev_cancelled.cancel()

        factory = APIRequestFactory()
        request = factory.get("/api/v1/events/")
        request.user = self.account

        view = CalendarEventViewSet.as_view({"get": "list"})
        response = view(request)
        titles = [item["title"] for item in response.data.get("results", response.data)]
        self.assertIn("Active", titles)
        self.assertNotIn("Cancelled", titles)

    def test_serializer_required_fields_present(self):
        if not self._has_drf:
            self.skipTest("djangorestframework not installed")
        from evennia_calendar.api.serializers import CalendarEventSerializer

        required_fields = {
            "id",
            "title",
            "description",
            "scheduled_time",
            "emphasis",
            "emphasis_display",
            "creator_name",
            "is_staff_event",
            "is_cancelled",
            "cluster",
            "cluster_title",
        }
        declared = set(CalendarEventSerializer.Meta.fields)
        self.assertEqual(
            required_fields,
            declared,
            f"Serializer fields mismatch. Missing: {required_fields - declared}",
        )
