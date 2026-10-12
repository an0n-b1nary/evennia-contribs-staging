# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reference game seam: plot owners and threads with every partner installed.

The seeded Founding Storm runs "by request" under the first seeded speaker:
one held thread with a sealed answer, one open thread the second speaker
leads, the second speaker's pending request, and a loose end carried in from
its prequel, The Quiet Before. Pages render through the game's own URLconf and
website/base.html, so a broken reverse or include fails here.
"""

from importlib import import_module
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from evennia.utils.test_resources import EvenniaTest
from typeclasses.characters import Character
from typeclasses.rooms import Room

from world.sandbox import content
from world.sandbox.tests import SeededSandboxMixin


class TestSeededPlotThreads(SeededSandboxMixin, EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        from evennia_plots.models import PlotThread

        self.storm = PlotThread.objects.get(name=content.PLOT_THREAD["name"])
        self.prelude = PlotThread.objects.get(name=content.PLOT_PRELUDE["name"])
        self.owner = self.storm.owners.get().character

    def _render(self, view, user=None, puppet=None, **kwargs):
        request = RequestFactory().get("/")
        request.user = AnonymousUser() if user is None else user
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        if puppet is None:
            response = view.as_view()(request, **kwargs)
        else:
            with mock.patch.object(user, "get_all_puppets", return_value=[puppet]):
                response = view.as_view()(request, **kwargs)
        response.render()
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_the_seed_shows_every_kind_of_thread(self):
        from evennia_plots.models import StoryThread

        threads = {t.title: t for t in self.storm.story_threads.all()}
        held = threads[content.PLOT_STORM_THREADS[0]["title"]]
        led = threads[content.PLOT_STORM_THREADS[1]["title"]]
        request = threads[content.PLOT_STORM_REQUEST["title"]]
        carried = threads[content.PLOT_PRELUDE["loose_end"]]
        self.assertEqual(self.storm.thread_policy, "request")
        self.assertTrue(held.is_held and held.answer_is_sealed)
        self.assertTrue(self.storm.is_owner_led)
        self.assertTrue(led.interests.filter(is_lead=True).exists())
        self.assertEqual(request.status, StoryThread.Status.REQUESTED)
        self.assertEqual(self.prelude.status, "concluded")
        self.assertEqual(carried.carried_from.plot, self.prelude)
        self.assertEqual(carried.carried_from.status, StoryThread.Status.CARRIED)

    def test_the_plot_page_renders_threads_through_the_site(self):
        from evennia_plots.views import PlotDetailView

        html = self._render(PlotDetailView, pk=self.storm.pk)
        self.assertIn(content.PLOT_STORM_THREADS[0]["title"], html)
        self.assertIn("Owner-led", html)
        self.assertIn(content.PLOT_PRELUDE["loose_end"], html)
        self.assertNotIn(content.PLOT_STORM_THREADS[0]["sealed_answer"], html)
        self.assertNotIn(content.PLOT_STORM_REQUEST["title"], html)

    def test_the_owner_sees_requests_and_owner_actions(self):
        from evennia_plots.views import PlotDetailView

        self.account2.characters.add(self.owner)
        html = self._render(PlotDetailView, user=self.account2, puppet=self.owner, pk=self.storm.pk)
        self.assertIn(content.PLOT_STORM_REQUEST["title"], html)
        self.assertIn(f"/plots/{self.storm.pk}/threads/", html)
        self.assertIn("Manage Owners", html)
        self.assertNotIn(content.PLOT_STORM_THREADS[0]["sealed_answer"], html)

    def test_the_prelude_links_its_carried_thread(self):
        from evennia_plots.views import PlotDetailView

        html = self._render(PlotDetailView, pk=self.prelude.pk)
        self.assertIn("Carried to", html)
        self.assertIn(f"/plots/{self.storm.pk}/#threads", html)

    def test_the_answer_page_renders_for_the_owner(self):
        from evennia_plots.views import StoryThreadAnswerView

        held = self.storm.story_threads.get(title=content.PLOT_STORM_THREADS[0]["title"])
        self.account2.characters.add(self.owner)
        html = self._render(
            StoryThreadAnswerView,
            user=self.account2,
            puppet=self.owner,
            pk=self.storm.pk,
            number=held.number,
        )
        self.assertIn(content.PLOT_STORM_THREADS[0]["sealed_answer"], html)

    def test_concluding_the_storm_leaves_loose_ends_and_still_reminds_about_lore(self):
        from evennia_lore.models import LoreNotice
        from evennia_plots.models import StoryThread

        with mock.patch("evennia_lore.notices.is_online", return_value=False):
            self.storm.conclude(concluded_by=self.owner)
        statuses = set(self.storm.story_threads.values_list("status", flat=True))
        self.assertEqual(statuses, {StoryThread.Status.LOOSE_END, StoryThread.Status.DECLINED})
        self.assertTrue(LoreNotice.objects.filter(character=self.owner).exists())
