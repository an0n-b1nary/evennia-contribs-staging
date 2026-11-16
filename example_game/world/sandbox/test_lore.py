# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Lore's two layers under real partners: jobs tickets, plots reminders, the seed and the web."""

from importlib import import_module
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_lore import test_lean
from evennia_lore.models import LoreEntry, LoreNotice, PlotLoreLink
from world.sandbox import content
from world.sandbox.seeding import SeededSandboxMixin


@override_settings(ROOT_URLCONF="web.urls")
class LoreLeanSeams(test_lean.TestLoreLeanPersistence):
    """Exercise persistent leans through the real character and mounted lore pages."""

    character_typeclass = Character
    room_typeclass = Room

    def test_plot_lean_survives_cache_eviction(self):
        from evennia_lore.commands import CmdInvestigate
        from evennia_plots.models import PlotThread

        plot = PlotThread.create_thread(name="The Codex", creator=self.char1)
        PlotLoreLink.objects.create(entry=self.entry, thread_id=plot.pk)
        self.call(CmdInvestigate(), f"/plot #{plot.plot_number}", caller=self.char2)
        self._reload_character()
        self._assert_lean("plot", plot.plot_number, 2)

    def test_region_lean_survives_cache_eviction(self):
        from evennia_lore.commands import CmdInvestigate
        from evennia_lore.models import LoreRegionLink
        from evennia_regions.models import Region

        region = Region.objects.create(name="The Archive")
        LoreRegionLink.objects.create(entry=self.entry, region_id=region.pk)
        self.call(CmdInvestigate(), "/region The Archive", caller=self.char2)
        self._reload_character()
        self._assert_lean("region", region.name, 2)


class LoreReviewSeams(EvenniaTest):
    """LORE_STAFF_REVIEW_HOOK reaches evennia-jobs through this game's settings."""

    character_typeclass = Character
    room_typeclass = Room

    def test_affirmation_request_files_a_staff_ticket(self):
        from evennia_jobs.models import Job, JobType

        entry = LoreEntry.create_entry(title="Camp Gossip", author=self.char2, kind="rumor")
        entry.request_affirmation(requested_by=self.char2)
        job = Job.objects.get()
        self.assertEqual(job.job_type, JobType.DISCUSS)
        self.assertIn(f"#{entry.entry_number} Camp Gossip", job.title)
        self.assertIn("+lore/affirm", job.description)


class LoreLayerSeams(EvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room

    def test_staff_can_review_restricted_sealed_notes_in_game(self):
        from evennia_lore.commands import CmdLore

        entry = LoreEntry.create_entry(
            title="A hidden legend", author=self.char2, kind="legend", privacy="restricted"
        )
        entry.seal("The archivist knows the truth.")
        player = self.call(CmdLore(), f"/read #{entry.entry_number}", caller=self.char2)
        self.assertNotIn(entry.sealed_notes, player)
        staff = self.call(CmdLore(), f"/read #{entry.entry_number}", caller=self.char1)
        self.assertIn(entry.sealed_notes, staff)
        self.assertFalse(entry.acquisitions.exists())

    def test_api_filter_preserves_private_declines(self):
        from rest_framework.test import APIRequestFactory, force_authenticate

        from evennia_lore.api.views import LoreEntryViewSet

        declined = LoreEntry.create_entry(title="Declined legend", author=self.char1)
        declined.decline(declined_by=self.char1, note="For the author only.")
        plain = LoreEntry.create_entry(title="Unreviewed legend", author=self.char1)
        self.account2.characters.add(self.char2)
        request = APIRequestFactory().get("/api/lore/entries/", {"affirmation": "none"})
        force_authenticate(request, user=self.account2)
        response = LoreEntryViewSet.as_view({"get": "list"})(request)
        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(
            [row["id"] for row in response.data["results"]], [declined.pk, plain.pk]
        )
        self.assertTrue(all(row["affirmation"] == "none" for row in response.data["results"]))

    @override_settings(LORE_DEFAULT_KIND="legend")
    def test_web_submission_uses_the_configured_default_kind(self):
        from django.urls import resolve, reverse

        from evennia_lore.views import LoreCreateView

        self.account2.characters.add(self.char2)
        path_ = reverse("lore-create")
        factory = RequestFactory()
        request = factory.get(path_, HTTP_ACCEPT="text/html")
        request.user = self.account2
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        request.resolver_match = resolve(path_)
        response = LoreCreateView.as_view()(request)
        response.render()
        self.assertIn('<option value="legend" selected>', response.content.decode())
        form = response.context_data["form"]
        request = factory.post(
            path_,
            {
                "title": "A legend from the web",
                "body": "The river has turned gold.",
                "kind": form["kind"].value(),
                "accuracy": form["accuracy"].value() or "",
                "privacy": "public",
            },
        )
        request.user = self.account2
        response = LoreCreateView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        entry = LoreEntry.objects.get(title="A legend from the web")
        self.assertEqual((entry.kind, entry.accuracy), ("legend", "open"))


class SeededLoreSeams(SeededSandboxMixin, EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def _seeded(self, slug):
        spec = next(spec for spec in content.LORE_ENTRIES if spec["slug"] == slug)
        return LoreEntry.objects.get(title=spec["title"])

    def test_seed_shows_each_layer_feature(self):
        founding = self._seeded("founding")
        self.assertEqual((founding.kind, founding.affirmation), ("fact", "affirmed"))
        self.assertFalse(founding.edited_since_affirmation)
        rumor = self._seeded("rumors")
        self.assertEqual((rumor.kind, rumor.accuracy), ("rumor", "inaccurate"))
        self.assertTrue(rumor.ooc_notes)
        legend = self._seeded("exile")
        self.assertEqual((legend.kind, legend.accuracy), ("legend", "open"))
        self.assertTrue(legend.has_sealed_notes)
        # Seeded affirmation is nobody's decision, so nobody is sent a notice.
        self.assertFalse(LoreNotice.objects.exists())

    def test_reseeding_replaces_the_lore_rather_than_duplicating_it(self):
        from django.core.management import call_command

        call_command("seed_sandbox", verbosity=0)
        titles = [spec["title"] for spec in content.LORE_ENTRIES]
        self.assertEqual(LoreEntry.all_objects.filter(title__in=titles).count(), len(titles))

    def test_concluding_the_seeded_thread_flags_its_sealed_legend(self):
        from evennia_jobs.models import Job
        from evennia_plots.models import PlotThread

        legend = self._seeded("exile")
        thread = PlotThread.objects.get(name=content.PLOT_THREAD["name"])
        self.assertTrue(PlotLoreLink.objects.filter(thread_id=thread.pk, entry=legend).exists())
        with mock.patch("evennia_lore.notices.is_online", return_value=False):
            thread.conclude(concluded_by=self.char2)
        notice = LoreNotice.objects.get(character=self.char2)
        self.assertIn(f"#{legend.entry_number}", notice.message)
        self.assertTrue(Job.objects.filter(title__contains="Sealed lore").exists())

    def test_detail_page_separates_the_layers_and_keeps_the_seal(self):
        from django.urls import resolve, reverse

        from evennia_lore.views import LoreDetailView

        legend = self._seeded("exile")
        path_ = reverse("lore-detail", kwargs={"pk": legend.pk})
        request = RequestFactory().get(path_, HTTP_ACCEPT="text/html")
        request.user = AnonymousUser()
        request.resolver_match = resolve(path_)
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        response = LoreDetailView.as_view()(request, pk=legend.pk)
        response.render()
        html = response.content.decode()
        self.assertIn("In character", html)
        self.assertIn("Out of character", html)
        self.assertIn("Legend", html)
        self.assertIn("sealed until the story settles this", html)
        self.assertNotIn(legend.sealed_notes, html)

    def test_lore_guide_pages_load_with_the_game_guides(self):
        from evennia_guides import pages

        pages.reset()
        self.assertIsNotNone(pages.get_page("lore"))
        self.assertEqual(pages.get_page("ic-may-mislead").kind, "principle")
        problems = [item for item in pages.validate() if item[0] == "error"]
        self.assertEqual(problems, [])


class LoreNoticeSeams(EvenniaTest):
    """Real Lore decisions render privately in the host's Inbox."""

    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)

    def test_real_opt_in_is_idempotent_and_selected_character_scoped(self):
        from django.test import override_settings

        from evennia_links.notices import NoticeContext
        from evennia_notices import views
        from evennia_notices.services import project
        from world.sandbox.notices_seed import emit_lore_demo_notices

        with override_settings(ROOT_URLCONF="web.urls"):
            entry = emit_lore_demo_notices(self.account, self.char1)
            emit_lore_demo_notices(self.account, self.char1)
            self.assertEqual(LoreNotice.objects.filter(entry=entry).count(), 1)
            self.assertEqual(len(project(NoticeContext(self.account, self.char1))), 1)
            request = RequestFactory().get("/notices/")
            request.user = self.account
            request.session = import_module(settings.SESSION_ENGINE).SessionStore()
            request.session["puppet"] = self.char1.pk
            response = views.inbox(request).render()
            self.assertContains(response, "Staff affirmed your lore entry")
            item = project(NoticeContext(self.account, self.char1))[0]
            detail = views.detail(request, item.notice.public_ref).render()
            self.assertContains(detail, f"/lore/{entry.pk}/")
            request.session["puppet"] = self.char2.pk
            response = views.inbox(request).render()
            self.assertNotContains(response, "Staff affirmed your lore entry")

    def test_first_summary_imports_known_pending_without_reading_content(self):
        from unittest.mock import patch

        from evennia_links.notices import NoticeContext
        from evennia_lore import notices
        from evennia_notices.listeners import session_summary
        from evennia_notices.services import project

        self.account.puppet_object(self.session, self.char1)
        entry = LoreEntry.create_entry("Private author fixture", author=self.char1, body="Content")
        with patch.object(notices, "_safe_route", return_value="retry"):
            entry.decline(note="Original private reason")
        with patch.object(self.session, "msg") as message:
            session_summary(self.char1, session=self.session)
        self.assertEqual(LoreNotice.objects.get(entry=entry).route_state, "inbox")
        self.assertIn(
            "Original private reason", project(NoticeContext(self.account, self.char1))[0].text
        )
        self.assertTrue(message.called)
        self.assertNotIn("Original private reason", str(message.call_args_list))

    def test_missing_optional_lore_web_route_keeps_alert_readable(self):
        from django.test import override_settings

        from evennia_links.notices import NoticeContext
        from evennia_notices import views
        from evennia_notices.services import project
        from world.sandbox.notices_seed import emit_lore_demo_notices

        emit_lore_demo_notices(self.account, self.char1)
        with override_settings(ROOT_URLCONF="evennia_notices.tests.test_web"):
            request = RequestFactory().get("/notices/")
            request.user = self.account
            request.session = import_module(settings.SESSION_ENGINE).SessionStore()
            request.session["puppet"] = self.char1.pk
            response = views.inbox(request).render()
            self.assertContains(response, "Staff affirmed your lore entry")
            item = project(NoticeContext(self.account, self.char1))[0]
            detail = views.detail(request, item.notice.public_ref).render()
            self.assertContains(detail, "+lore/read")
            self.assertNotContains(detail, "/lore/")
