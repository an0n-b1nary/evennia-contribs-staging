# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Command syntax, personal attendance and ranked-choice application boundaries."""

import datetime
import random
from unittest.mock import patch

from django.utils import timezone
from evennia.utils import create
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_calendar import commands
from evennia_calendar.models import (
    RSVP,
    CalendarEvent,
    ClusterRSVP,
    EventCluster,
    PriorityToken,
)
from evennia_calendar.scheduler import run_cluster_lottery


class TestCalendarSyntax(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.when = timezone.now() + datetime.timedelta(days=7)

    def event(self, title, **kwargs):
        return CalendarEvent.create_event(
            creator=self.char1, title=title, scheduled_time=self.when, **kwargs
        )

    def invoke(self, cls, args, caller=None):
        return self.call(cls(), args, caller=caller or self.char2)

    def cluster(self):
        self.invoke(commands.CmdCluster, "/new Parallel mysteries", self.char1)
        return EventCluster.objects.get(title="Parallel mysteries")

    def test_cluster_membership_lock_and_staff_permissions(self):
        cluster = self.cluster()
        event = self.event("Battle")
        self.invoke(commands.CmdCluster, f"/add {event.pk}={cluster.pk}")
        event.refresh_from_db()
        self.assertIsNone(event.cluster_id)
        self.invoke(commands.CmdCluster, f"/add {event.pk}={cluster.pk}", self.char1)
        event.refresh_from_db()
        self.assertEqual(event.cluster_id, cluster.pk)
        self.assertIn("Battle", self.invoke(commands.CmdCluster, str(cluster.pk)))
        self.invoke(commands.CmdCluster, f"/remove {event.pk}", self.char1)
        event.refresh_from_db()
        self.assertIsNone(event.cluster_id)
        self.invoke(commands.CmdCluster, f"/add {event.pk}={cluster.pk}", self.char1)
        self.invoke(commands.CmdCluster, f"/lock {cluster.pk}")
        cluster.refresh_from_db()
        self.assertFalse(cluster.is_locked)
        self.invoke(commands.CmdCluster, f"/lock {cluster.pk}", self.char1)
        cluster.refresh_from_db()
        self.assertTrue(cluster.is_locked)
        self.invoke(commands.CmdCluster, f"/remove {event.pk}", self.char1)
        event.refresh_from_db()
        self.assertEqual(event.cluster_id, cluster.pk)

    def test_rank_replace_mine_and_withdraw_never_create_attendance(self):
        cluster = self.cluster()
        first, second = self.event("Battle"), self.event("Stealth")
        for event in (first, second):
            self.invoke(commands.CmdCluster, f"/add {event.pk}={cluster.pk}", self.char1)
        self.invoke(commands.CmdCluster, f"/rank {cluster.pk}={first.pk}")
        self.assertFalse(ClusterRSVP.objects.exists())
        self.invoke(commands.CmdCluster, f"/lock {cluster.pk}", self.char1)
        self.invoke(commands.CmdCluster, f"/Ra {cluster.pk}={first.pk},{second.pk}")
        application = ClusterRSVP.objects.get()
        self.assertEqual(
            list(application.get_ordered_preferences().values_list("event_id", flat=True)),
            [first.pk, second.pk],
        )
        self.invoke(commands.CmdCluster, f"/rank {cluster.pk}={second.pk},{first.pk}")
        self.assertEqual(
            list(application.get_ordered_preferences().values_list("event_id", flat=True)),
            [second.pk, first.pk],
        )
        self.assertFalse(RSVP.objects.filter(character=self.char2).exists())
        out = self.invoke(commands.CmdCluster, f"/mine {cluster.pk}")
        self.assertIn("Pending", out)
        self.assertIn("Stealth", out)
        self.assertNotIn("Battle", self.invoke(commands.CmdCalendar, "/mine"))
        stranger = create.create_object("evennia.objects.objects.DefaultCharacter", key="Stranger")
        self.assertIn(
            "don't have", self.invoke(commands.CmdCluster, f"/mine {cluster.pk}", stranger)
        )
        self.invoke(commands.CmdCluster, f"/withdraw {cluster.pk}", stranger)
        self.assertTrue(ClusterRSVP.objects.filter(pk=application.pk).exists())
        self.invoke(commands.CmdCluster, f"/withdraw {cluster.pk}")
        self.assertFalse(ClusterRSVP.objects.exists())
        self.assertFalse(RSVP.objects.filter(character=self.char2).exists())

    def test_bad_rankings_preserve_existing_preferences(self):
        cluster = self.cluster()
        first, second = (
            self.event("Battle", cluster=cluster),
            self.event("Stealth", cluster=cluster),
        )
        outsider = self.event("Unrelated")
        self.invoke(commands.CmdCluster, f"/lock {cluster.pk}", self.char1)
        self.invoke(commands.CmdCluster, f"/rank {cluster.pk}={first.pk},{second.pk}")
        application = ClusterRSVP.objects.get()
        for ranking in (f"{first.pk},{first.pk}", str(outsider.pk), "not-an-id", ""):
            self.invoke(commands.CmdCluster, f"/rank {cluster.pk}={ranking}")
            self.assertEqual(
                list(application.get_ordered_preferences().values_list("event_id", flat=True)),
                [first.pk, second.pk],
            )

    def test_personal_events_cover_all_current_statuses_and_exclude_nonattendance(self):
        for status, _label in RSVP.Status.choices:
            event = self.event("Attendance " + status)
            RSVP.objects.create(
                event=event,
                character=self.char2,
                character_name=self.char2.key,
                status=status,
                waitlist_position=3 if status == RSVP.Status.WAITLISTED else None,
            )
        hosted = CalendarEvent.create_event(
            creator=self.char2, title="Hosted", scheduled_time=self.when
        )
        RSVP.objects.create(event=hosted, character=self.char2, status=RSVP.Status.RELEASED)
        for title, when, cancelled in (
            ("Past", timezone.now() - datetime.timedelta(days=1), False),
            ("Cancelled", self.when, True),
        ):
            event = CalendarEvent.create_event(
                creator=self.char2, title=title, scheduled_time=when, is_cancelled=cancelled
            )
            RSVP.objects.create(event=event, character=self.char2, status=RSVP.Status.CONFIRMED)
        self.event("Other host")
        for sr in (False, True):
            with patch.object(commands, "uses_screenreader", return_value=sr):
                out = self.invoke(commands.CmdCalendar, "/MINE")
            self.assertIn("Hosted", out)
            self.assertIn("Host", out)
            for status, label in RSVP.Status.choices:
                if status != RSVP.Status.RELEASED:
                    self.assertIn("Attendance " + status, out)
                    self.assertIn(label, out)
            for excluded in ("Attendance released", "Past", "Cancelled", "Other host", "Released"):
                self.assertNotIn(excluded, out)
            self.assertIn("3", out)

    def test_host_and_current_rsvp_appear_once(self):
        event = CalendarEvent.create_event(
            creator=self.char2, title="Hosting and attending", scheduled_time=self.when
        )
        RSVP.objects.create(event=event, character=self.char2, status=RSVP.Status.CONFIRMED)
        out = self.invoke(commands.CmdCalendar, "/mine")
        self.assertEqual(out.count("Hosting and attending"), 1)
        self.assertIn("Host", out)
        self.assertIn("Confirmed", out)

    def test_mine_does_not_silently_hide_events_after_thirty(self):
        for i in range(31):
            CalendarEvent.create_event(
                creator=self.char2,
                title=f"My event {i:02}",
                scheduled_time=self.when + datetime.timedelta(minutes=i),
            )
        self.assertIn("My event 30", self.invoke(commands.CmdCalendar, "/mine"))

    def test_cluster_seating_creates_the_event_on_personal_calendar(self):
        cluster = self.cluster()
        event = self.event(
            "Seated mystery", cluster=cluster, is_staff_event=True, participant_cap=2
        )
        self.invoke(commands.CmdCluster, f"/lock {cluster.pk}", self.char1)
        self.invoke(commands.CmdCluster, f"/rank {cluster.pk}={event.pk}")
        self.assertNotIn("Seated mystery", self.invoke(commands.CmdCalendar, "/mine"))
        cluster.refresh_from_db()
        run_cluster_lottery(cluster, rng=random.Random(7))
        out = self.invoke(commands.CmdCalendar, "/mine")
        self.assertIn("Seated mystery", out)
        self.assertIn("Lottery Selected", out)
        self.assertIn("Assigned event", self.invoke(commands.CmdCluster, f"/mine {cluster.pk}"))
        self.invoke(commands.CmdCluster, f"/withdraw {cluster.pk}")
        self.assertTrue(ClusterRSVP.objects.filter(character=self.char2).exists())
        self.assertTrue(RSVP.objects.filter(character=self.char2).exists())

    def test_token_renames_and_retired_token_prefix_do_not_redeem(self):
        event = self.event("Token lottery", is_staff_event=True, participant_cap=2)
        token = PriorityToken.objects.create(character=self.char2, character_name=self.char2.key)
        self.assertIn("Unknown", self.invoke(commands.CmdRsvp, "/token"))
        self.assertIn("Priority Tokens", self.invoke(commands.CmdRsvp, "/TOKENS"))
        self.assertIn("one switch", self.invoke(commands.CmdRsvp, f"/token/use {event.pk}"))
        token.refresh_from_db()
        self.assertIsNone(token.redeemed_event_id)
        self.invoke(commands.CmdRsvp, f"/rede {event.pk}")
        token.refresh_from_db()
        self.assertEqual(token.redeemed_event_id, event.pk)
        self.assertEqual(
            RSVP.objects.get(event=event, character=self.char2).status, "lottery_entered"
        )

    def test_stacked_unknown_ambiguous_and_retired_switches_do_not_mutate(self):
        event = self.event("Guarded event")
        for cls, args in (
            (commands.CmdCalendar, "/cluster Unwanted"),
            (commands.CmdCalendar, "/create/garbage Unwanted=2099-01-01 20:00"),
            (commands.CmdCalendar, f"/cancel/garbage {event.pk}"),
            (commands.CmdCalendar, f"/ca {event.pk}"),
            (commands.CmdRsvp, f"/cluster 1={event.pk}"),
            (commands.CmdRsvp, f"/unknown {event.pk}"),
        ):
            out = self.invoke(cls, args, self.char1)
            self.assertTrue("Unknown" in out or "one switch" in out, out)
        self.assertFalse(EventCluster.objects.exists())
        self.assertFalse(RSVP.objects.exists())
        event.refresh_from_db()
        self.assertFalse(event.is_cancelled)
        self.assertEqual(CalendarEvent.objects.count(), 1)

    def test_cluster_guard_refuses_extras_and_retires_view(self):
        cluster = self.cluster()
        for form in (
            "/new/garbage Unwanted",
            f"/lock/garbage {cluster.pk}",
            f"/garbage {cluster.pk}",
            f"/view {cluster.pk}",
        ):
            out = self.invoke(commands.CmdCluster, form, self.char1)
            self.assertTrue("Unknown" in out or "one switch" in out, out)
        self.assertEqual(EventCluster.objects.count(), 1)
        cluster.refresh_from_db()
        self.assertFalse(cluster.is_locked)
