# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for plot owners and threads (StoryThread).

Covers ownership and the owner backfill, the thread lifecycle under each
policy, held threads and sealed answers (including that a sealed answer never
leaks through any surface), leads and interest, loose ends and carrying, the
+plot thread switches, the web pages and the API, and that threads leave XP
untouched.

EvenniaTest defaults: char1 is staff (Developer); char2 is not. ``self.char3``
is a second non-staff character created here.
"""

import unittest
from datetime import timedelta
from importlib import import_module
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings
from django.utils import timezone
from evennia.utils import create
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from evennia_plots import threads as svc
from evennia_plots.commands import CmdPlot
from evennia_plots.models import (
    PlotCalendarLink,
    PlotOwner,
    PlotParticipant,
    PlotThread,
    ScenePlotLink,
    StoryThread,
    StoryThreadInterest,
    ThreadLink,
)
from evennia_plots.permissions import is_plot_staff

SECRET = "The bell-ringer was the drowned king all along."


def _plot(creator, name="The Drowned Bell", privacy="public", policy=None, active=True):
    plot = PlotThread.create_thread(
        name=name, creator=creator, privacy=privacy, thread_policy=policy
    )
    if active:
        plot.activate()
    return plot


class ThreadTestMixin:
    def setUp(self):
        super().setUp()
        self.char3 = create.create_object(
            "evennia.objects.objects.DefaultCharacter", key="Char3", location=self.room1
        )
        self.assertFalse(is_plot_staff(self.char2))
        self.assertFalse(is_plot_staff(self.char3))


# ---------------------------------------------------------------------------
# Owners
# ---------------------------------------------------------------------------


class TestPlotOwners(ThreadTestMixin, EvenniaTest):
    def test_the_creator_is_the_first_owner(self):
        plot = _plot(self.char2)
        self.assertEqual(plot.owner_ids(), {self.char2.pk})
        self.assertTrue(plot.can_manage(self.char2))
        self.assertFalse(plot.can_manage(self.char3))

    def test_a_plot_without_a_creator_has_no_owner(self):
        plot = PlotThread.create_thread(name="Orphan", creator=None)
        self.assertEqual(plot.owner_ids(), set())
        self.assertTrue(plot.can_manage(self.char1))  # staff

    def test_a_co_owner_manages_the_plot(self):
        plot = _plot(self.char2, privacy="private")
        svc.add_owner(plot, self.char2, self.char3)
        self.assertTrue(plot.can_manage(self.char3))
        self.assertTrue(plot.can_view(self.char3))
        self.assertTrue(plot.can_link(self.char3))
        self.assertTrue(plot.is_participant(self.char3))

    def test_owners_link_to_their_invite_only_plot(self):
        plot = _plot(self.char2, privacy="invite_only")
        self.assertFalse(plot.can_link(self.char3))
        svc.add_owner(plot, self.char2, self.char3)
        self.assertTrue(plot.can_link(self.char3))

    def test_ownership_never_creates_a_participant(self):
        """Owners aren't PlotParticipant rows, so owning a plot pays no XP."""
        plot = _plot(self.char2)
        svc.add_owner(plot, self.char2, self.char3)
        self.assertFalse(PlotParticipant.objects.filter(thread=plot).exists())

    def test_strangers_cannot_add_owners(self):
        plot = _plot(self.char2)
        with self.assertRaises(svc.ThreadError):
            svc.add_owner(plot, self.char3, self.char3)

    def test_the_last_owner_stays_unless_staff_remove_them(self):
        plot = _plot(self.char2)
        with self.assertRaises(svc.ThreadError):
            svc.remove_owner(plot, self.char2, self.char2)
        svc.remove_owner(plot, self.char1, self.char2)
        self.assertEqual(plot.owner_ids(), set())

    def test_staff_stepping_in_is_logged_and_owners_are_not(self):
        plot = _plot(self.char2)
        svc.add_owner(plot, self.char2, self.char3)
        plot.refresh_from_db()
        self.assertEqual(plot.staff_log, [])
        svc.remove_owner(plot, self.char1, self.char3)
        plot.refresh_from_db()
        self.assertEqual(len(plot.staff_log), 1)
        self.assertEqual(plot.staff_log[0]["action"], "removed owner")
        self.assertEqual(plot.staff_log[0]["staff"], self.char1.key)

    def test_backfill_makes_each_creator_an_owner(self):
        migration = import_module("evennia_plots.migrations.0003_backfill_plot_owners")
        with_creator = _plot(self.char2)
        without = PlotThread.create_thread(name="Orphan", creator=None)
        PlotOwner.objects.all().delete()
        migration.backfill_owners(apps, None)
        migration.backfill_owners(apps, None)  # idempotent
        self.assertEqual(with_creator.owner_ids(), {self.char2.pk})
        self.assertEqual(without.owner_ids(), set())
        self.assertEqual(PlotOwner.objects.count(), 1)


# ---------------------------------------------------------------------------
# Thread lifecycle
# ---------------------------------------------------------------------------


class TestThreadPolicy(ThreadTestMixin, EvenniaTest):
    def test_open_policy_lets_anyone_who_can_link_add(self):
        plot = _plot(self.char2)
        self.assertEqual(plot.thread_policy, PlotThread.ThreadPolicy.OPEN)
        thread = svc.add_thread(plot, self.char3, "Venture to the drowned chapel")
        self.assertEqual(thread.status, StoryThread.Status.OPEN)
        self.assertEqual(thread.ref, f"#{plot.plot_number}.1")

    def test_request_policy_makes_a_request_that_owners_decide(self):
        plot = _plot(self.char2, policy="request")
        thread = svc.add_thread(plot, self.char3, "Why do the wells run red?")
        self.assertEqual(thread.status, StoryThread.Status.REQUESTED)
        with self.assertRaises(svc.ThreadError):
            svc.accept(thread, self.char3)
        svc.accept(thread, self.char2)
        self.assertEqual(thread.status, StoryThread.Status.OPEN)
        self.assertEqual(thread.decided_by, self.char2)

    def test_owners_add_directly_under_request_policy(self):
        plot = _plot(self.char2, policy="request")
        thread = svc.add_thread(plot, self.char2, "Investigate the ferryman")
        self.assertEqual(thread.status, StoryThread.Status.OPEN)

    def test_declining_keeps_the_reason(self):
        plot = _plot(self.char2, policy="request")
        thread = svc.add_thread(plot, self.char3, "Burn the chapel")
        svc.decline(thread, self.char2, "Not this arc.")
        thread.refresh_from_db()
        self.assertEqual(thread.status, StoryThread.Status.DECLINED)
        self.assertEqual(thread.decline_reason, "Not this arc.")

    def test_only_the_requester_withdraws(self):
        plot = _plot(self.char2, policy="request")
        thread = svc.add_thread(plot, self.char3, "Ask the gulls")
        with self.assertRaises(svc.ThreadError):
            svc.withdraw(thread, self.char2)
        svc.withdraw(thread, self.char3)
        self.assertFalse(StoryThread.objects.filter(pk=thread.pk).exists())

    def test_owners_only_policy_refuses_others(self):
        plot = _plot(self.char2, policy="owners")
        with self.assertRaises(svc.ThreadError):
            svc.add_thread(plot, self.char3, "Sneak in a thread")
        self.assertEqual(svc.add_thread(plot, self.char1, "Staff may").status, "open")

    def test_the_can_link_rule_gates_adding_and_requesting(self):
        private = _plot(self.char2, name="Quiet Pact", privacy="private")
        with self.assertRaises(svc.ThreadError):
            svc.add_thread(private, self.char3, "Peek")
        invite = _plot(self.char2, name="Guest List", privacy="invite_only", policy="request")
        self.assertFalse(svc.can_request(invite, self.char3))
        invite.invited_characters.add(self.char3)
        self.assertTrue(svc.can_request(invite, self.char3))

    def test_owners_may_seed_threads_before_the_plot_is_active(self):
        proposed = _plot(self.char2, active=False)
        svc.add_thread(proposed, self.char2, "Set up the mystery")
        with self.assertRaises(svc.ThreadError):
            svc.add_thread(proposed, self.char3, "Too early")

    def test_numbers_count_within_each_plot(self):
        first = _plot(self.char2)
        second = _plot(self.char2, name="The Second Bell")
        a = svc.add_thread(first, self.char2, "One")
        b = svc.add_thread(first, self.char2, "Two")
        c = svc.add_thread(second, self.char2, "Other plot")
        self.assertEqual((a.number, b.number, c.number), (1, 2, 1))

    def test_titles_are_required_and_bounded(self):
        plot = _plot(self.char2)
        with self.assertRaises(svc.ThreadError):
            svc.add_thread(plot, self.char2, "   ")
        with self.assertRaises(svc.ThreadError):
            svc.add_thread(plot, self.char2, "x" * 201)


class TestThreadResolution(ThreadTestMixin, EvenniaTest):
    def setUp(self):
        super().setUp()
        self.plot = _plot(self.char2)
        self.thread = svc.add_thread(self.plot, self.char2, "Investigate the drowned bell")

    def test_a_lead_resolves_an_unheld_thread(self):
        with self.assertRaises(svc.ThreadError):
            svc.resolve(self.thread, self.char3, "Found it.")
        self.assertTrue(svc.toggle_lead(self.thread, self.char3))
        svc.resolve(self.thread, self.char3, "Found it under the pier.")
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.status, StoryThread.Status.RESOLVED)
        self.assertEqual(self.thread.resolved_by, self.char3)

    def test_the_threads_creator_resolves_their_unheld_thread(self):
        mine = svc.add_thread(self.plot, self.char3, "Talk to the ferryman")
        svc.resolve(mine, self.char3, "He talked.")
        self.assertEqual(mine.status, StoryThread.Status.RESOLVED)

    def test_only_owners_resolve_a_held_thread(self):
        svc.set_held(self.thread, self.char2, True)
        svc.toggle_lead(self.thread, self.char3)
        with self.assertRaises(svc.ThreadError):
            svc.resolve(self.thread, self.char3, "Guessing.")
        svc.resolve(self.thread, self.char2, "As planned.")
        self.assertEqual(self.thread.status, StoryThread.Status.RESOLVED)

    def test_a_summary_is_required(self):
        with self.assertRaises(svc.ThreadError):
            svc.resolve(self.thread, self.char2, " ")

    def test_drop_and_reopen(self):
        svc.drop(self.thread, self.char2)
        self.assertEqual(self.thread.status, StoryThread.Status.DROPPED)
        svc.reopen(self.thread, self.char2)
        self.assertEqual(self.thread.status, StoryThread.Status.OPEN)
        self.assertIsNone(self.thread.resolved_at)

    def test_only_owners_drop(self):
        with self.assertRaises(svc.ThreadError):
            svc.drop(self.thread, self.char3)

    def test_lead_and_interest_toggle(self):
        self.assertTrue(svc.toggle_interest(self.thread, self.char3))
        self.assertTrue(svc.toggle_lead(self.thread, self.char3))
        interest = StoryThreadInterest.objects.get(thread=self.thread, character=self.char3)
        self.assertTrue(interest.is_lead)
        self.assertFalse(svc.toggle_lead(self.thread, self.char3))
        self.assertFalse(svc.toggle_interest(self.thread, self.char3))
        self.assertFalse(StoryThreadInterest.objects.filter(thread=self.thread).exists())

    def test_many_characters_may_lead(self):
        svc.toggle_lead(self.thread, self.char2)
        svc.toggle_lead(self.thread, self.char3)
        self.assertEqual(self.thread.interests.filter(is_lead=True).count(), 2)

    def test_strangers_cannot_follow_threads_on_a_private_plot(self):
        private = _plot(self.char2, name="Quiet Pact", privacy="private")
        thread = svc.add_thread(private, self.char2, "Hidden question")
        with self.assertRaises(svc.ThreadError):
            svc.toggle_interest(thread, self.char3)

    def test_requests_are_shown_only_to_managers_and_the_requester(self):
        self.plot.thread_policy = PlotThread.ThreadPolicy.REQUEST
        self.plot.save(update_fields=["thread_policy"])
        request = svc.add_thread(self.plot, self.char3, "May I?")
        stranger = create.create_object(
            "evennia.objects.objects.DefaultCharacter", key="Char4", location=self.room1
        )
        self.assertIn(request, svc.visible_threads(self.plot, self.char2))
        self.assertIn(request, svc.visible_threads(self.plot, self.char3))
        self.assertNotIn(request, svc.visible_threads(self.plot, stranger))
        self.assertIn(self.thread, svc.visible_threads(self.plot, stranger))


class TestPlotEndAndCarrying(ThreadTestMixin, EvenniaTest):
    def setUp(self):
        super().setUp()
        self.plot = _plot(self.char2, policy="request")
        self.open = svc.add_thread(self.plot, self.char2, "Who rang the bell?")
        self.request = svc.add_thread(self.plot, self.char3, "Dredge the harbour")
        self.done = svc.add_thread(self.plot, self.char2, "Find the bell")
        svc.resolve(self.done, self.char2, "Found.")

    def test_concluding_turns_open_threads_into_loose_ends(self):
        self.plot.conclude(concluded_by=self.char2)
        self.open.refresh_from_db()
        self.request.refresh_from_db()
        self.done.refresh_from_db()
        self.assertEqual(self.open.status, StoryThread.Status.LOOSE_END)
        self.assertEqual(self.request.status, StoryThread.Status.DECLINED)
        self.assertEqual(self.done.status, StoryThread.Status.RESOLVED)

    def test_archiving_does_the_same(self):
        self.plot.archive()
        self.open.refresh_from_db()
        self.assertEqual(self.open.status, StoryThread.Status.LOOSE_END)

    def _sequel(self, owner=None):
        sequel = _plot(owner or self.char2, name="The Second Bell")
        ThreadLink.objects.create(
            from_thread=sequel,
            to_thread=self.plot,
            link_type=ThreadLink.LinkType.SEQUEL,
            is_accepted=True,
        )
        return sequel

    def test_a_loose_end_carries_into_a_declared_sequel(self):
        svc.seal(self.open, self.char2, SECRET)
        self.plot.conclude()
        self.open.refresh_from_db()
        sequel = self._sequel()
        self.assertEqual(svc.carry_targets(self.open, self.char2), [sequel])
        new, answer_carried = svc.carry(self.open, self.char2, sequel)
        self.open.refresh_from_db()
        self.assertTrue(answer_carried)
        self.assertEqual(self.open.status, StoryThread.Status.CARRIED)
        self.assertEqual(self.open.carried_to, new)
        self.assertEqual((new.plot, new.status, new.title), (sequel, "open", self.open.title))
        self.assertTrue(new.is_held)
        self.assertEqual(new.sealed_answer, SECRET)

    def test_carrying_needs_a_sequel_link(self):
        self.plot.conclude()
        self.open.refresh_from_db()
        unrelated = _plot(self.char2, name="Elsewhere")
        with self.assertRaises(svc.ThreadError):
            svc.carry(self.open, self.char2, unrelated)

    def test_carrying_needs_both_plots_run_by_the_carrier(self):
        self.plot.conclude()
        self.open.refresh_from_db()
        sequel = self._sequel(owner=self.char3)
        with self.assertRaises(svc.ThreadError):
            svc.carry(self.open, self.char2, sequel)

    def test_a_sealed_answer_never_reaches_new_owners(self):
        svc.seal(self.open, self.char2, SECRET)
        self.plot.conclude()
        self.open.refresh_from_db()
        sequel = self._sequel()
        svc.add_owner(sequel, self.char2, self.char3)
        new, answer_carried = svc.carry(self.open, self.char2, sequel)
        self.assertFalse(answer_carried)
        self.assertEqual(new.sealed_answer, "")

    def test_only_loose_ends_carry(self):
        sequel = self._sequel()
        with self.assertRaises(svc.ThreadError):
            svc.carry(self.open, self.char2, sequel)


# ---------------------------------------------------------------------------
# Held threads and sealed answers
# ---------------------------------------------------------------------------


class TestSealedAnswers(ThreadTestMixin, EvenniaTest):
    def setUp(self):
        super().setUp()
        self.plot = _plot(self.char2)
        self.thread = svc.add_thread(self.plot, self.char2, "Who rang the bell?")

    def test_sealing_marks_the_thread_held(self):
        svc.seal(self.thread, self.char2, SECRET)
        self.thread.refresh_from_db()
        self.assertTrue(self.thread.is_held)
        self.assertIsNotNone(self.thread.sealed_at)
        self.assertTrue(self.plot.is_owner_led)

    def test_only_owners_seal(self):
        with self.assertRaises(svc.ThreadError):
            svc.seal(self.thread, self.char3, "My guess")

    def test_edits_keep_earlier_wordings_and_the_first_sealed_time(self):
        svc.seal(self.thread, self.char2, "First idea")
        first_sealed = self.thread.sealed_at
        svc.seal(self.thread, self.char2, SECRET)
        self.assertEqual(self.thread.sealed_at, first_sealed)
        versions = list(self.thread.answer_versions.values_list("content", flat=True))
        self.assertEqual(versions, ["First idea"])

    def test_a_held_thread_with_an_answer_cannot_be_released(self):
        svc.seal(self.thread, self.char2, SECRET)
        with self.assertRaises(svc.ThreadError):
            svc.set_held(self.thread, self.char2, False)
        svc.seal(self.thread, self.char2, "")
        svc.set_held(self.thread, self.char2, False)
        self.assertFalse(self.thread.is_held)

    def test_who_can_read_it(self):
        svc.seal(self.thread, self.char2, SECRET)
        self.assertTrue(svc.can_read_answer(self.thread, self.char2))
        self.assertTrue(svc.can_read_answer(self.thread, self.char1))  # staff
        self.assertFalse(svc.can_read_answer(self.thread, self.char3))
        self.assertFalse(svc.can_read_answer(self.thread, None))

    def test_resolving_reveals_only_when_asked(self):
        svc.seal(self.thread, self.char2, SECRET)
        svc.resolve(self.thread, self.char2, "Solved.")
        self.assertTrue(self.thread.answer_is_sealed)
        self.assertFalse(svc.can_read_answer(self.thread, self.char3))
        svc.reveal(self.thread, self.char2)
        self.assertTrue(svc.can_read_answer(self.thread, self.char3))

    def test_resolve_with_reveal(self):
        svc.seal(self.thread, self.char2, SECRET)
        svc.resolve(self.thread, self.char2, "Solved.", reveal_answer=True)
        self.assertTrue(self.thread.sealed_answer_revealed)

    def test_an_open_thread_cannot_be_revealed(self):
        svc.seal(self.thread, self.char2, SECRET)
        with self.assertRaises(svc.ThreadError):
            svc.reveal(self.thread, self.char2)

    def test_staff_resolving_a_held_thread_is_logged(self):
        svc.seal(self.thread, self.char2, SECRET)
        svc.resolve(self.thread, self.char1, "Owner went idle; staff closed it.")
        self.plot.refresh_from_db()
        self.assertEqual([e["action"] for e in self.plot.staff_log], ["resolved held thread"])

    def test_the_database_refuses_an_answer_on_an_unheld_thread(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            StoryThread.objects.filter(pk=self.thread.pk).update(sealed_answer="x", is_held=False)


# ---------------------------------------------------------------------------
# XP is untouched by threads
# ---------------------------------------------------------------------------


class TestThreadsLeaveXPAlone(ThreadTestMixin, EvenniaTest):
    def _bonus(self, with_threads):
        plot = _plot(self.char2, name=f"Bonus {with_threads}")
        event = type(
            "Event", (), {"pk": 7 + with_threads, "scheduled_time": timezone.now() + timedelta(8)}
        )()
        PlotCalendarLink.create_link(plot, event)
        ScenePlotLink.objects.create(thread=plot, scene_id=1)
        ScenePlotLink.objects.create(thread=plot, scene_id=2)
        if with_threads:
            open_one = svc.add_thread(plot, self.char2, "Open")
            svc.seal(open_one, self.char2, SECRET)
            resolved = svc.add_thread(plot, self.char2, "Resolved")
            svc.resolve(resolved, self.char2, "Done.")
        return plot.conclude()

    def test_the_conclusion_bonus_ignores_threads(self):
        self.assertEqual(self._bonus(with_threads=False), 4)
        self.assertEqual(self._bonus(with_threads=True), 4)

    @unittest.skipUnless(apps.is_installed("evennia_xp"), "requires evennia_xp")
    def test_owners_who_did_not_take_part_receive_no_bonus(self):
        from evennia_plots.integrations.xp import collect_thread_bonuses

        plot = _plot(self.char2)
        svc.add_owner(plot, self.char2, self.char3)
        PlotParticipant.objects.create(thread=plot, character=self.char2, character_name="c2")
        now = timezone.now()
        PlotThread.objects.filter(pk=plot.pk).update(
            status=PlotThread.Status.CONCLUDED, bonus_xp_computed=3, concluded_at=now
        )
        awarded = {a.character_id for a in collect_thread_bonuses(now + timedelta(hours=1))}
        self.assertEqual(awarded, {self.char2.pk})


# ---------------------------------------------------------------------------
# +plot thread switches
# ---------------------------------------------------------------------------


class TestCmdPlotThreads(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.plot = _plot(self.char2, policy="request")
        self.n = self.plot.plot_number

    def _plot_cmd(self, args, caller):
        return self.call(CmdPlot(), args, caller=caller)

    def test_the_thread_alias_is_gone(self):
        self.assertEqual(CmdPlot.aliases, [])

    def test_owners_and_staff_add_directly_under_request_policy(self):
        self.assertIn("Added thread", self._plot_cmd(f"/thread #{self.n}=Who rang?", self.char2))
        self.assertIn("Added thread", self._plot_cmd(f"/thread #{self.n}=Dredge it", self.char1))
        self.assertEqual(
            list(self.plot.story_threads.values_list("status", flat=True)), ["open", "open"]
        )

    def test_request_accept_and_display(self):
        player = create.create_object(
            "evennia.objects.objects.DefaultCharacter", key="Char3", location=self.room1
        )
        out = self._plot_cmd(f"/thread #{self.n}=Dredge the harbour", player)
        self.assertIn("Requested thread", out)
        self.assertIn("is open", self._plot_cmd(f"/thread/accept #{self.n}.1", self.char2))
        out = self._plot_cmd(f"#{self.n}", player)
        self.assertIn("Threads (by request)", out)
        self.assertIn("Dredge the harbour", out)

    def test_seal_resolve_and_reveal(self):
        self._plot_cmd(f"/thread #{self.n}=Who rang the bell?", self.char2)
        out = self._plot_cmd(f"/thread/seal #{self.n}.1={SECRET}", self.char2)
        self.assertIn("Sealed the answer", out)
        shown = self._plot_cmd(f"#{self.n}", self.char2)
        self.assertIn("[Held]", shown)
        self.assertIn("Owner-led", shown)
        out = self._plot_cmd(f"/thread/resolve #{self.n}.1=The king rang it.", self.char2)
        self.assertIn("stays sealed", out)
        self.assertNotIn(SECRET, self._plot_cmd(f"#{self.n}", self.char2))
        self.assertIn("Revealed", self._plot_cmd(f"/thread/reveal #{self.n}.1", self.char2))
        self.assertIn(SECRET, self._plot_cmd(f"#{self.n}", self.char2))

    def test_thread_policy_and_owner_switches(self):
        self.assertIn("owners only", self._plot_cmd(f"/threads #{self.n}=owners", self.char2))
        out = self._plot_cmd(f"/owner #{self.n}={self.char1.key}", self.char2)
        self.assertIn("now owns", out)
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.thread_policy, "owners")
        self.assertTrue(self.plot.is_owner(self.char1))

    def test_a_bad_reference_is_explained(self):
        out = self._plot_cmd(f"/thread/lead #{self.n}", self.char2)
        self.assertIn("not a thread reference", out)

    def test_conclude_names_the_loose_ends(self):
        self._plot_cmd(f"/thread #{self.n}=Who rang the bell?", self.char2)
        out = self._plot_cmd(f"/conclude #{self.n}", self.char2)
        self.assertIn(f"Loose ends: #{self.n}.1", out)


# ---------------------------------------------------------------------------
# Sealed answers never leak
# ---------------------------------------------------------------------------


@override_settings(ROOT_URLCONF="evennia_plots.tests")
class TestSealedAnswerNeverLeaks(ThreadTestMixin, EvenniaCommandTest):
    """Every surface a player can reach, checked with the answer sealed."""

    def setUp(self):
        super().setUp()
        self.plot = _plot(self.char2)
        self.thread = svc.add_thread(self.plot, self.char2, "Who rang the bell?")
        svc.seal(self.thread, self.char2, SECRET)
        self.factory = RequestFactory()

    def _render(self, view, *, user=None, puppet=None, **kwargs):
        request = self.factory.get("/")
        request.user = AnonymousUser() if user is None else user
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        if puppet is None:
            response = view.as_view()(request, **kwargs)
        else:
            with patch.object(user, "get_all_puppets", return_value=[puppet]):
                response = view.as_view()(request, **kwargs)
        if hasattr(response, "render"):
            response.render()
        return response

    def test_in_game(self):
        self.assertNotIn(
            SECRET, self.call(CmdPlot(), f"#{self.plot.plot_number}", caller=self.char3)
        )
        out = self.call(CmdPlot(), f"/thread/answer #{self.plot.plot_number}.1", caller=self.char3)
        self.assertNotIn(SECRET, out)
        self.assertIn(
            SECRET,
            self.call(CmdPlot(), f"/thread/answer #{self.plot.plot_number}.1", caller=self.char2),
        )

    def test_plot_page(self):
        from evennia_plots.views import PlotDetailView

        self.account2.characters.add(self.char2)
        html = self._render(PlotDetailView, pk=self.plot.pk).content.decode()
        self.assertIn("Who rang the bell?", html)
        self.assertNotIn(SECRET, html)

    def test_answer_page_is_a_404_for_others(self):
        from django.http import Http404

        from evennia_plots.views import StoryThreadAnswerView

        with self.assertRaises(Http404):
            self._render(
                StoryThreadAnswerView,
                user=self.account2,
                puppet=self.char3,
                pk=self.plot.pk,
                number=self.thread.number,
            )

    def test_api_for_players_and_staff(self):
        try:
            from rest_framework.test import APIRequestFactory, force_authenticate
        except ImportError:
            self.skipTest("requires djangorestframework")
        from evennia_plots.api.views import PlotThreadViewSet

        for user in (self.account2, self.account):
            request = APIRequestFactory().get("/api/v1/plots/")
            force_authenticate(request, user=user)
            response = PlotThreadViewSet.as_view({"get": "list"})(request)
            response.render()
            body = response.content.decode()
            self.assertIn("Who rang the bell?", body)
            self.assertNotIn(SECRET, body)
            self.assertNotIn("sealed_answer", body)

    @unittest.skipUnless(apps.is_installed("evennia_scenes"), "requires evennia_scenes")
    def test_map_panel(self):
        from evennia_plots.integrations.maps import provide_detail

        Scene = apps.get_model("evennia_scenes", "Scene")
        ScenePlotLink.create_link(Scene.objects.create(room=self.room1, title="A scene"), self.plot)
        with patch("evennia_plots.integrations.maps._thread_url", lambda pk: f"/plots/{pk}/"):
            section = provide_detail(
                sender=None, room_id=self.room1.id, room=self.room1, staff=True
            )
        self.assertNotIn(SECRET, repr(section))

    def test_carrying_to_new_owners(self):
        self.plot.conclude()
        self.thread.refresh_from_db()
        sequel = _plot(self.char2, name="Sequel")
        svc.add_owner(sequel, self.char2, self.char3)
        ThreadLink.objects.create(
            from_thread=sequel, to_thread=self.plot, link_type="sequel", is_accepted=True
        )
        new, _ = svc.carry(self.thread, self.char2, sequel)
        self.assertNotIn(
            SECRET, self.call(CmdPlot(), f"/thread/answer {new.ref}", caller=self.char3)
        )
        self.assertFalse(svc.can_read_answer(new, self.char3))


# ---------------------------------------------------------------------------
# Web pages
# ---------------------------------------------------------------------------


@override_settings(ROOT_URLCONF="evennia_plots.tests")
class TestThreadWebPages(ThreadTestMixin, EvenniaTest):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.plot = _plot(self.char2, policy="request")
        self.held = svc.add_thread(self.plot, self.char2, "Who rang the bell?")
        svc.seal(self.held, self.char2, SECRET)
        self.request = svc.add_thread(self.plot, self.char3, "Dredge the harbour")
        self.account2.characters.add(self.char2)

    def _response(self, view, method="get", data=None, *, user=None, puppet=None, **kwargs):
        request = getattr(self.factory, method)("/", data or {})
        request.user = AnonymousUser() if user is None else user
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        request._messages = _NullMessages()
        if puppet is None:
            response = view.as_view()(request, **kwargs)
        else:
            with patch.object(user, "get_all_puppets", return_value=[puppet]):
                response = view.as_view()(request, **kwargs)
        if hasattr(response, "render"):
            response.render()
        return response

    def _as_owner(self, view, method="get", data=None, **kwargs):
        return self._response(view, method, data, user=self.account2, puppet=self.char2, **kwargs)

    def test_plot_page_shows_threads_to_the_owner(self):
        from evennia_plots.views import PlotDetailView

        html = self._as_owner(PlotDetailView, pk=self.plot.pk).content.decode()
        self.assertIn('id="threads"', html)
        self.assertIn("Who rang the bell?", html)
        self.assertIn("Owner-led", html)
        self.assertIn("Held", html)
        self.assertIn("Dredge the harbour", html)  # owners see requests
        self.assertIn("Accept", html)
        self.assertIn("Manage Owners", html)
        self.assertNotIn(SECRET, html)

    def test_plot_page_for_visitors_hides_requests(self):
        from evennia_plots.views import PlotDetailView

        html = self._response(PlotDetailView, pk=self.plot.pk).content.decode()
        self.assertIn("Who rang the bell?", html)
        self.assertNotIn("Dredge the harbour", html)
        self.assertNotIn("Manage Owners", html)

    def test_plot_page_empty_state(self):
        from evennia_plots.views import PlotDetailView

        bare = _plot(self.char2, name="Quiet Plot")
        html = self._response(PlotDetailView, pk=bare.pk).content.decode()
        self.assertIn("No open threads.", html)

    def test_plot_list_counts_open_threads(self):
        from evennia_plots.views import PlotListView

        html = self._response(PlotListView).content.decode()
        self.assertIn("1 open thread", html)
        self.assertIn("Owner-led", html)
        self.assertIn(self.char2.key, html)  # owners column

    def test_thread_form_offers_a_request_to_non_owners(self):
        from evennia_plots.views import StoryThreadCreateView

        html = self._response(
            StoryThreadCreateView, user=self.account2, puppet=self.char3, pk=self.plot.pk
        ).content.decode()
        self.assertIn("Request a Thread", html)
        self.assertIn("Send Request", html)
        self.assertIn("Posting as", html)

    def test_owner_adds_a_thread_through_the_form(self):
        from evennia_plots.views import StoryThreadCreateView

        response = self._as_owner(
            StoryThreadCreateView, "post", {"title": "Ask the gulls"}, pk=self.plot.pk
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            self.plot.story_threads.filter(title="Ask the gulls", status="open").exists()
        )

    def test_accept_action(self):
        from evennia_plots.views import StoryThreadActionView

        response = self._as_owner(
            StoryThreadActionView,
            "post",
            pk=self.plot.pk,
            number=self.request.number,
            action="accept",
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("#threads"))
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, StoryThread.Status.OPEN)

    def test_unknown_action_is_a_404(self):
        from django.http import Http404

        from evennia_plots.views import StoryThreadActionView

        with self.assertRaises(Http404):
            self._as_owner(
                StoryThreadActionView,
                "post",
                pk=self.plot.pk,
                number=self.held.number,
                action="explode",
            )

    def test_answer_page_for_the_owner(self):
        from evennia_plots.views import StoryThreadAnswerView

        html = self._as_owner(
            StoryThreadAnswerView, pk=self.plot.pk, number=self.held.number
        ).content.decode()
        self.assertIn(SECRET, html)
        self.assertIn("Sealed", html)
        self.assertIn("No earlier wordings.", html)

    def test_resolve_page_offers_the_reveal_to_owners(self):
        from evennia_plots.views import StoryThreadResolveView

        html = self._as_owner(
            StoryThreadResolveView, pk=self.plot.pk, number=self.held.number
        ).content.decode()
        self.assertIn("Reveal the planned answer", html)
        response = self._as_owner(
            StoryThreadResolveView,
            "post",
            {"summary": "The king rang it.", "reveal": "on"},
            pk=self.plot.pk,
            number=self.held.number,
        )
        self.assertEqual(response.status_code, 302)
        self.held.refresh_from_db()
        self.assertTrue(self.held.sealed_answer_revealed)

    def test_revealed_answer_shows_on_the_plot_page(self):
        from evennia_plots.views import PlotDetailView

        svc.resolve(self.held, self.char2, "The king rang it.", reveal_answer=True)
        html = self._response(PlotDetailView, pk=self.plot.pk).content.decode()
        self.assertIn("The planned answer", html)
        self.assertIn(SECRET, html)

    def test_carry_page_empty_state(self):
        from evennia_plots.views import StoryThreadCarryView

        self.plot.conclude()
        html = self._as_owner(
            StoryThreadCarryView, pk=self.plot.pk, number=self.held.number
        ).content.decode()
        self.assertIn("No sequel plots you run.", html)

    def test_owners_page(self):
        from evennia_plots.views import PlotOwnersView

        html = self._as_owner(PlotOwnersView, pk=self.plot.pk).content.decode()
        self.assertIn("Current owners", html)
        self.assertIn(self.char2.key, html)
        response = self._as_owner(
            PlotOwnersView, "post", {"character_name": "Char3", "action": "add"}, pk=self.plot.pk
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.plot.is_owner(self.char3))


class _NullMessages:
    """Stand-in message storage: RequestFactory requests have no middleware."""

    def add(self, level, message, extra_tags=""):
        pass

    def __iter__(self):
        return iter(())
