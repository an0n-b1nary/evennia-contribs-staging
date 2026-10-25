# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Lore's two layers under real partners: jobs tickets, plots reminders, the seed and the web."""

from importlib import import_module
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from evennia_lore import test_lean
from evennia_lore.models import LoreEntry, LoreNotice, PlotLoreLink
from typeclasses.characters import Character
from typeclasses.rooms import Room

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
        from evennia_lore.api.views import LoreEntryViewSet
        from rest_framework.test import APIRequestFactory, force_authenticate

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
