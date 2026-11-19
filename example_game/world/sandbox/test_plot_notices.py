# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real sandbox Plots commands, authoring, shared Inbox and private reads."""

from importlib import import_module
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.http import Http404
from django.test import RequestFactory, override_settings
from django.urls import include, path, reverse
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTest
from rest_framework.test import APIRequestFactory, force_authenticate
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_links.notices import NoticeContext
from evennia_notices import views as inbox
from evennia_notices.commands import CmdNotices
from evennia_notices.models import DeliveryReceipt
from evennia_notices.services import mutate, project
from evennia_plots.api.views import PlotThreadViewSet
from evennia_plots.commands import CmdThread
from evennia_plots.models import PlotNoticeReceipt, PlotThread, StoryThread
from evennia_plots.views import (
    PlotDetailView,
    PlotEditView,
    PlotInviteView,
    PlotListView,
    PlotOwnersView,
    StoryThreadActionView,
    StoryThreadCreateView,
)
from world.sandbox.management.commands.seed_sandbox import Command as SeedSandbox
from world.sandbox.notices_seed import emit_plot_demo_notice

urlpatterns = [path("", include("web.urls"))]


@override_settings(ROOT_URLCONF=__name__)
class PlotNoticeSeams(EvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.char2.account = self.account2

    def request(self, account, character=None, *, data=None, url="/notices/"):
        factory = RequestFactory()
        request = factory.get(url) if data is None else factory.post(url, data=data)
        request.user = account
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        if character is not None:
            request.session["puppet"] = character.pk
        return request

    def test_command_and_web_actions_share_the_same_notice_source(self):
        plot = PlotThread.create_thread(
            "Private test eventual title", self.char1, thread_policy=PlotThread.ThreadPolicy.REQUEST
        )
        plot.activate()
        request = self.request(self.account, self.char1)
        self.assertContains(inbox.inbox(request).render(), "My Notices")
        self.assertNotContains(inbox.inbox(request).render(), "ready for review")
        with self.captureOnCommitCallbacks(execute=True):
            output = self.call(
                CmdThread(), f"/new #{plot.plot_number}=Command fixture", caller=self.char2
            )
            result = StoryThreadCreateView.as_view()(
                self.request(self.account2, self.char2, data={"title": "Web fixture"}),
                pk=plot.pk,
            )
        self.assertIn("Requested", output)
        self.assertEqual(result.status_code, 302)
        self.assertEqual(PlotNoticeReceipt.objects.filter(plot=plot).count(), 2)
        self.assertContains(inbox.inbox(request).render(), "ready for review", count=2)
        self.char1.locks.add(f"puppet:pid({self.account.pk})")
        if self.session.get_puppet() is not None:
            self.account.unpuppet_object(self.session)
        self.account.puppet_object(self.session, self.char1)
        self.assertEqual(self.session.get_puppet(), self.char1)
        self.assertIn("ready for review", self.call(CmdNotices(), "", caller=self.char1))
        command, web = plot.story_threads.order_by("number")
        with self.captureOnCommitCallbacks(execute=True):
            result = StoryThreadActionView.as_view()(
                self.request(self.account, self.char1, data={}),
                pk=plot.pk,
                number=web.number,
                action="accept",
            )
        self.assertEqual(result.status_code, 302)
        self.assertContains(
            inbox.inbox(self.request(self.account2, self.char2)).render(), "was accepted"
        )
        [item] = project(NoticeContext(self.account, self.char1), source="plots")
        detail = inbox.detail(request, item.notice.public_ref).render()
        self.assertContains(detail, f"+thread {command.ref}")
        alt = create_object(Character, key="Alternate plot reader", nohome=True)
        self.account.characters.add(alt)
        for character in (None, alt):
            wrong = self.request(self.account, character)
            self.assertNotContains(inbox.inbox(wrong).render(), "ready for review")
            with self.assertRaises(Http404):
                inbox.detail(wrong, item.notice.public_ref)
        threads = PlotNoticeReceipt.objects.filter(plot=plot)
        self.assertEqual(threads.count(), 3)
        self.assertEqual(DeliveryReceipt.objects.filter(source="plots").count(), 3)

    def test_demo_is_private_repeat_safe_and_visible_only_to_opted_in_character(self):
        session = Mock(logged_in=True)
        session.get_account.return_value = self.account
        session.get_puppet.return_value = self.char1
        sessions = "evennia.server.sessionhandler.SESSIONS.get_sessions"
        before_roster = list(self.account.characters.all())
        with patch(sessions, return_value=[session]):
            with self.assertRaises(ValueError):
                emit_plot_demo_notice(self.account, self.char2, session=session)
            with self.captureOnCommitCallbacks(execute=True):
                emit_plot_demo_notice(self.account, self.char1, session=session)
                emit_plot_demo_notice(self.account, self.char1, session=session)
        self.assertEqual(list(self.account.characters.all()), before_roster)
        self.assertEqual(PlotNoticeReceipt.objects.count(), 1)
        receipt = PlotNoticeReceipt.objects.get()
        plot = receipt.plot
        self.assertEqual(plot.privacy, PlotThread.Privacy.PRIVATE)
        self.assertEqual(plot.owner_ids(), {self.char1.pk})

        context = NoticeContext(self.account, self.char1)
        [item] = project(context, source="plots")
        web = self.request(self.account, self.char1)
        content = inbox.inbox(web).render()
        self.assertContains(content, "A private plot has a thread request")
        detail = inbox.detail(web, item.notice.public_ref).render()
        self.assertContains(detail, f"+thread {receipt.thread.ref}")
        for response in (content, detail):
            self.assertNotContains(response, plot.name)
            self.assertNotContains(response, receipt.thread.title)
            self.assertNotContains(
                response, reverse("evennia_plots:plot-detail", kwargs={"pk": plot.pk})
            )
        self.assertFalse(project(NoticeContext(self.account2, self.char2), source="plots"))
        session.msg.assert_not_called()

        public = self.request(self.account2, self.char2, url="/plots/")
        self.assertNotContains(PlotListView.as_view()(public).render(), plot.name)
        for view in (PlotDetailView, PlotOwnersView, StoryThreadCreateView):
            with self.assertRaises(Http404):
                view.as_view()(web, pk=plot.pk)
        for view in (PlotEditView, PlotInviteView):
            with self.assertRaises(PermissionDenied):
                view.as_view()(public, pk=plot.pk)
            self.assertContains(view.as_view()(web, pk=plot.pk).render(), plot.name)
        for account, expected in ((self.account, 200), (self.account2, 404)):
            api_request = APIRequestFactory().get(f"/api/plots/{plot.pk}/")
            force_authenticate(api_request, user=account)
            result = PlotThreadViewSet.as_view({"get": "retrieve"})(api_request, pk=plot.pk)
            self.assertEqual(result.status_code, expected)

        mutate(context, item.notice.public_ref, "clear")
        with patch(sessions, return_value=[session]), self.captureOnCommitCallbacks(execute=True):
            emit_plot_demo_notice(self.account, self.char1, session=session)
        self.assertFalse(project(context, source="plots"))
        self.assertEqual(PlotNoticeReceipt.objects.count(), 1)
        self.assertEqual(receipt.thread.status, StoryThread.Status.REQUESTED)

    def test_seed_dry_run_never_creates_a_plot_notice_demo(self):
        with patch(
            "world.sandbox.management.commands.seed_sandbox.Command._purge", return_value={}
        ):
            call_command("seed_sandbox", dry_run=True, verbosity=0)
        self.assertFalse(PlotThread.objects.filter(name="Example Plot Inbox").exists())
        self.assertFalse(PlotNoticeReceipt.objects.exists())

    def test_reset_purges_the_demo_plot_but_not_a_namesake(self):
        session = Mock(logged_in=True)
        session.get_account.return_value = self.account
        session.get_puppet.return_value = self.char1
        sessions = "evennia.server.sessionhandler.SESSIONS.get_sessions"
        with patch(sessions, return_value=[session]), self.captureOnCommitCallbacks(execute=True):
            emit_plot_demo_notice(self.account, self.char1, session=session)
        demo = PlotNoticeReceipt.objects.get().plot
        namesake = PlotThread.create_thread(
            "Example Plot Inbox", self.char2, thread_policy=PlotThread.ThreadPolicy.REQUEST
        )
        namesake.activate()

        self.assertEqual(SeedSandbox()._purge(dry_run=True).get("plot_notice_examples"), 1)
        self.assertTrue(PlotThread.objects.filter(pk=demo.pk).exists())
        SeedSandbox()._purge(dry_run=False)
        self.assertFalse(PlotThread.objects.filter(pk=demo.pk).exists())
        self.assertFalse(PlotNoticeReceipt.objects.exists())
        self.assertTrue(PlotThread.objects.filter(pk=namesake.pk).exists())
