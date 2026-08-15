# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_lore.

Covers models, bridges, commands, trickle engine, the web pages (rendered
for real), and API privacy.

This module doubles as a **test URLconf** (see ``urlpatterns`` below). Cases
that reverse a URL or render a template opt in with
``@override_settings(ROOT_URLCONF=__name__)``. The default URLconf mounts
*only* this contrib's routes — the realistic install where a game runs lore
without evennia_regions/scenes/plots — so the outbound partner links have to
degrade rather than raise. ``PartnerRoutesUrlConf`` is the other half of that
pair, for cases that want the links present.

Run:
    evennia test --settings test_lore_settings.py evennia_lore
"""

from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, override_settings
from django.urls import include, path
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from evennia.web.urls import urlpatterns as evennia_default_urlpatterns

from evennia_lore.commands import CmdForget, CmdHint, CmdInvestigate, CmdLore, CmdShare
from evennia_lore.models import (
    LoreAcquisition,
    LoreEntry,
    LoreRegionLink,
    LoreSceneLink,
    LoreTag,
    LoreVersion,
    PlotLoreLink,
)
from evennia_lore.selection import _build_pool, _lean_matches, select_passive_lore
from evennia_lore.views import (
    LoreApprovalQueueView,
    LoreCompendiumView,
    LoreCreateView,
    LoreDetailView,
    LoreEditView,
    LoreLeanView,
    LoreListView,
    LoreVersionDiffView,
    LoreVersionHistoryView,
)

# ---------------------------------------------------------------------------
# Test URLconfs (see the module docstring)
# ---------------------------------------------------------------------------


def _stub_page(request, pk):
    """Stand-in for a partner contrib's detail page."""
    return HttpResponse(f"stub {pk}")


# evennia_lore mounts its routes without a namespace, exactly as its urls.py
# documents. Evennia's own routes come along because website/base.html — which
# every lore template extends — reverses "index" and the account routes.
urlpatterns = [
    path("lore/", include("evennia_lore.urls")),
    *evennia_default_urlpatterns,
]


class PartnerRoutesUrlConf:
    """
    ROOT_URLCONF stand-in that also mounts region/scene/plot detail routes.

    Django resolves a ROOT_URLCONF that is not a string by reading
    ``urlpatterns`` straight off the object, so a bare class is enough — and
    it keeps the partner routes out of this module's own ``urlpatterns``,
    where their presence would hide the degradation the default case proves.
    """

    urlpatterns = [  # noqa: RUF012
        path("lore/", include("evennia_lore.urls")),
        path("regions/<int:pk>/", _stub_page, name="region-detail"),
        path("scenes/<int:pk>/", _stub_page, name="scene-detail"),
        path("plots/<int:pk>/", _stub_page, name="plot-detail"),
        *evennia_default_urlpatterns,
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(title="Test Lore", author=None, body="", summary="", privacy=None):
    return LoreEntry.create_entry(
        title=title, author=author, body=body, summary=summary, privacy=privacy
    )


def _make_tag(name="Magic", is_major=False):
    return LoreTag.objects.create(name=name, is_major=is_major)


def _room_context_provider(session):
    """Module-level provider for exercising the LORE_SESSION_CONTEXT_PROVIDER seam.

    Returns the session's room as room_id (what a real game's provider does for
    the room-weighting path), with no region/thread context.
    """
    room = getattr(session, "room", None)
    return {"room_id": room.pk if room else None, "region_id": None, "thread_ids": set()}


# ---------------------------------------------------------------------------
# LoreTag model
# ---------------------------------------------------------------------------


class TestLoreTag(EvenniaTest):
    def test_create_tag(self):
        tag = _make_tag("History", is_major=True)
        self.assertEqual(tag.name, "History")
        self.assertTrue(tag.is_major)

    def test_str(self):
        tag = _make_tag("Lore", is_major=False)
        self.assertIn("Minor", str(tag))
        self.assertIn("Lore", str(tag))


# ---------------------------------------------------------------------------
# LoreEntry model
# ---------------------------------------------------------------------------


class TestLoreEntryFactory(EvenniaTest):
    def test_entry_number_starts_at_one(self):
        e = _make_entry(author=self.char1)
        self.assertEqual(e.entry_number, 1)

    def test_entry_number_increments(self):
        e1 = _make_entry("First", author=self.char1)
        e2 = _make_entry("Second", author=self.char1)
        self.assertEqual(e1.entry_number, 1)
        self.assertEqual(e2.entry_number, 2)

    @override_settings(LORE_REQUIRE_APPROVAL=False)
    def test_default_status_is_published(self):
        e = _make_entry(author=self.char1)
        self.assertEqual(e.status, LoreEntry.Status.PUBLISHED)

    @override_settings(LORE_REQUIRE_APPROVAL=True)
    def test_require_approval_status_is_submitted(self):
        e = _make_entry(author=self.char1)
        self.assertEqual(e.status, LoreEntry.Status.SUBMITTED)

    def test_author_name_denormalized(self):
        e = _make_entry(author=self.char1)
        self.assertEqual(e.author_name, self.char1.key)

    def test_create_entry_collision_hardened(self):
        """Entry factory retries on duplicate entry_number (mirrors Job.create_job)."""
        real_create = LoreEntry.objects.create
        state = {"raised": False}

        def flaky_create(*args, **kwargs):
            if not state["raised"]:
                state["raised"] = True
                raise IntegrityError("simulated duplicate entry_number")
            return real_create(*args, **kwargs)

        with patch.object(LoreEntry.objects, "create", side_effect=flaky_create):
            e = LoreEntry.create_entry(title="Racy", author=self.char1, body="x")

        self.assertTrue(state["raised"])
        self.assertEqual(e.entry_number, 1)

    def test_create_entry_raises_after_exhausting_retries(self):
        with (
            patch.object(LoreEntry.objects, "create", side_effect=IntegrityError("always fails")),
            self.assertRaises(IntegrityError),
        ):
            LoreEntry.create_entry(title="Doomed", author=self.char1, body="x")


class TestLoreEntryLifecycle(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.entry = _make_entry(author=self.char1)

    def test_publish_transitions_status(self):
        self.entry.status = LoreEntry.Status.SUBMITTED
        self.entry.save()
        self.entry.publish(reviewed_by=self.char1)
        self.assertEqual(self.entry.status, LoreEntry.Status.PUBLISHED)

    def test_reject_soft_archives(self):
        self.entry.status = LoreEntry.Status.SUBMITTED
        self.entry.save()
        self.entry.reject(reviewed_by=self.char1, editor=self.char1)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, LoreEntry.Status.REJECTED)
        self.assertTrue(self.entry.is_archived)

    def test_flag_and_unflag(self):
        self.entry.flag(flagged_by=self.char1, reason="Inaccurate")
        self.assertTrue(self.entry.is_flagged)
        self.entry.unflag()
        self.assertFalse(self.entry.is_flagged)

    def test_edit_body_creates_version(self):
        self.entry.body = "old body"
        self.entry.save()
        self.entry.edit_body("new body", editor=self.char1)
        self.assertEqual(LoreVersion.objects.filter(parent=self.entry).count(), 1)
        self.assertEqual(self.entry.body, "new body")

    def test_is_accessible_to_public(self):
        self.assertTrue(self.entry.is_accessible_to(self.char2))

    def test_is_accessible_to_restricted_without_acquisition(self):
        self.entry.privacy = LoreEntry.Privacy.RESTRICTED
        self.entry.save()
        self.assertFalse(self.entry.is_accessible_to(self.char2))

    def test_is_accessible_to_restricted_with_acquisition(self):
        self.entry.privacy = LoreEntry.Privacy.RESTRICTED
        self.entry.save()
        LoreAcquisition.objects.create(
            entry=self.entry, character=self.char2, character_name=self.char2.key
        )
        self.assertTrue(self.entry.is_accessible_to(self.char2))

    def test_is_in_passive_pool(self):
        self.assertTrue(self.entry.is_in_passive_pool())

    def test_restricted_not_in_passive_pool(self):
        self.entry.privacy = LoreEntry.Privacy.RESTRICTED
        self.entry.save()
        self.assertFalse(self.entry.is_in_passive_pool())


# ---------------------------------------------------------------------------
# Bridge models
# ---------------------------------------------------------------------------


class TestLoreAcquisition(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.entry = _make_entry(author=self.char1)

    def test_create_acquisition(self):
        acq = LoreAcquisition.objects.create(
            entry=self.entry, character=self.char2, character_name=self.char2.key
        )
        self.assertEqual(acq.source, LoreAcquisition.Source.PASSIVE)

    def test_unique_entry_character(self):
        LoreAcquisition.objects.create(
            entry=self.entry, character=self.char2, character_name=self.char2.key
        )
        with (
            transaction.atomic(),
            self.assertRaises(IntegrityError),
        ):
            LoreAcquisition.objects.create(
                entry=self.entry, character=self.char2, character_name=self.char2.key
            )

    def test_session_id_survives_entry_cascade(self):
        """Acquisition rows survive LoreEntry deletion (session_id stays as int)."""
        acq = LoreAcquisition.objects.create(
            entry=self.entry,
            character=self.char2,
            character_name=self.char2.key,
            session_id=42,
        )
        pk = acq.pk
        self.entry.delete()
        self.assertFalse(LoreAcquisition.objects.filter(pk=pk).exists())


class TestPlotLoreLink(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.entry = _make_entry(author=self.char1)

    def test_create_and_str(self):
        link = PlotLoreLink.objects.create(thread_id=99, entry=self.entry)
        self.assertEqual(link.thread_id, 99)
        self.assertIn("99", str(link))

    def test_unique_thread_entry(self):
        PlotLoreLink.objects.create(thread_id=1, entry=self.entry)
        with (
            transaction.atomic(),
            self.assertRaises(IntegrityError),
        ):
            PlotLoreLink.objects.create(thread_id=1, entry=self.entry)


class TestLoreSceneLink(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.entry = _make_entry(author=self.char1)

    def test_create_and_str(self):
        link = LoreSceneLink.objects.create(entry=self.entry, scene_id=55)
        self.assertEqual(link.scene_id, 55)
        self.assertIn("55", str(link))

    def test_entry_cascade_deletes_link(self):
        link = LoreSceneLink.objects.create(entry=self.entry, scene_id=55)
        self.entry.delete()
        self.assertFalse(LoreSceneLink.objects.filter(pk=link.pk).exists())


class TestLoreRegionLink(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.entry = _make_entry(author=self.char1)

    def test_create_and_str(self):
        link = LoreRegionLink.objects.create(entry=self.entry, region_id=7)
        self.assertEqual(link.region_id, 7)
        self.assertIn("7", str(link))


# ---------------------------------------------------------------------------
# Trickle engine (_build_pool / select_passive_lore)
# ---------------------------------------------------------------------------


class TestBuildPool(EvenniaTest):
    def _session(self, room=None):
        from evennia_rptracker.models import RPSession

        return RPSession.objects.create(
            character=self.char1,
            character_name=self.char1.key,
            room=room,
            room_name=room.key if room else "",
            status=RPSession.Status.COMPLETED,
        )

    @override_settings(LORE_SESSION_CONTEXT_PROVIDER=None)
    def test_empty_pool_no_entries(self):
        session = self._session()
        self.assertEqual(_build_pool(self.char1, session), [])

    @override_settings(LORE_SESSION_CONTEXT_PROVIDER=None)
    def test_major_tag_gives_weight_2(self):
        entry = _make_entry("Tagged", author=self.char1)
        tag = _make_tag("Magic", is_major=True)
        entry.tags.add(tag)
        session = self._session()
        pool = _build_pool(self.char1, session)
        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0][1], 2)

    @override_settings(LORE_SESSION_CONTEXT_PROVIDER=None)
    def test_owned_entries_excluded(self):
        entry = _make_entry("Known", author=self.char1)
        entry.tags.add(_make_tag("Tag"))
        LoreAcquisition.objects.create(
            entry=entry, character=self.char1, character_name=self.char1.key
        )
        session = self._session()
        pool = _build_pool(self.char1, session)
        self.assertEqual(pool, [])

    @override_settings(LORE_SESSION_CONTEXT_PROVIDER=None)
    def test_restricted_entries_excluded(self):
        entry = _make_entry("Secret", author=self.char1, privacy=LoreEntry.Privacy.RESTRICTED)
        entry.tags.add(_make_tag("Tag"))
        session = self._session()
        pool = _build_pool(self.char1, session)
        self.assertEqual(pool, [])

    @override_settings(LORE_SESSION_CONTEXT_PROVIDER="evennia_lore.tests._room_context_provider")
    def test_room_weight_5_via_provider_seam(self):
        """The configured provider is resolved + called end-to-end (settings seam).

        Exercises the real LORE_SESSION_CONTEXT_PROVIDER path: _resolve_context
        imports the dotted callable, invokes it with the session, and the room_id
        it returns drives the room-weighting branch (+5).
        """
        entry = _make_entry("Room Lore", author=self.char1)
        entry.rooms.add(self.room1)
        session = self._session(room=self.room1)
        pool = _build_pool(self.char1, session)
        self.assertEqual(pool[0][1], 5)

    @override_settings(LORE_SESSION_CONTEXT_PROVIDER="evennia_lore.nonexistent.provider")
    def test_provider_resolution_failure_degrades_to_tag_only(self):
        """A broken provider path must not raise — context falls back to empty."""
        entry = _make_entry("Tag Only", author=self.char1)
        entry.rooms.add(self.room1)  # room signal would add +5 if provider worked
        entry.tags.add(_make_tag("Topic"))
        session = self._session()
        pool = _build_pool(self.char1, session)
        # Provider failed → no room_id → only the tag weight (1) applies.
        self.assertEqual(pool[0][1], 1)

    @override_settings(
        LORE_SESSION_CONTEXT_PROVIDER=None,
        LORE_PASSIVE_LEAN_MULTIPLIER=Decimal("2.0"),
    )
    def test_lean_multiplier_applied(self):
        entry = _make_entry("Tag Lean Entry", author=self.char1)
        tag = _make_tag("History", is_major=False)
        entry.tags.add(tag)
        self.char1.lore_lean_type = "tag"
        self.char1.lore_lean_value = "History"
        session = self._session()
        pool = _build_pool(self.char1, session)
        # base weight = 1 (minor tag), multiplied by 2 = 2
        self.assertEqual(pool[0][1], 2)


class TestSelectPassiveLore(EvenniaTest):
    def _session(self):
        from evennia_rptracker.models import RPSession

        return RPSession.objects.create(
            character=self.char1,
            character_name=self.char1.key,
            room=self.room1,
            room_name=self.room1.key,
            status=RPSession.Status.COMPLETED,
        )

    @override_settings(LORE_SESSION_CONTEXT_PROVIDER=None)
    def test_returns_none_when_pool_empty(self):
        session = self._session()
        result = select_passive_lore(self.char1, session)
        self.assertIsNone(result)

    @override_settings(LORE_SESSION_CONTEXT_PROVIDER=None, LORE_PASSIVE_WEEKLY_CEILING=3)
    def test_ceiling_blocks_acquisition(self):
        for i in range(3):
            e = _make_entry(f"Old {i}", author=self.char1)
            LoreAcquisition.objects.create(
                entry=e,
                character=self.char1,
                character_name=self.char1.key,
                source=LoreAcquisition.Source.PASSIVE,
            )
        eligible = _make_entry("New", author=self.char1)
        eligible.tags.add(LoreTag.objects.create(name="AnTag"))
        session = self._session()
        result = select_passive_lore(self.char1, session)
        self.assertIsNone(result)

    @override_settings(LORE_SESSION_CONTEXT_PROVIDER=None)
    def test_creates_acquisition_and_fires_signal(self):
        entry = _make_entry("Discoverable", author=self.char1)
        entry.tags.add(_make_tag("Topic"))
        session = self._session()
        fired = []
        from evennia_lore.signals import lore_acquired

        def handler(sender, acquisition, character, entry, **kwargs):
            fired.append(entry)

        lore_acquired.connect(handler)
        try:
            with patch("random.choices", return_value=[entry]):
                result = select_passive_lore(self.char1, session)
        finally:
            lore_acquired.disconnect(handler)

        self.assertEqual(result, entry)
        self.assertEqual(len(fired), 1)
        acq = LoreAcquisition.objects.get(entry=entry, character=self.char1)
        self.assertEqual(acq.source, LoreAcquisition.Source.PASSIVE)
        self.assertEqual(acq.session_id, session.pk)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


class TestCmdLoreStaffLock(EvenniaCommandTest):
    """LORE_STAFF_LOCK is honored by the commands' is_staff() helper."""

    def test_default_staff_check_allows_char1(self):
        from evennia_lore.commands import is_staff

        self.assertTrue(is_staff(self.char1))

    def test_default_staff_check_blocks_char2(self):
        from evennia_lore.commands import is_staff

        self.assertFalse(is_staff(self.char2))


class TestCmdLoreBrowse(EvenniaCommandTest):
    def test_bare_browse_empty(self):
        result = self.call(CmdLore(), "", caller=self.char1)
        self.assertIn("empty", result.lower())

    def test_bare_browse_shows_entries(self):
        _make_entry("Visible Lore", author=self.char1)
        result = self.call(CmdLore(), "", caller=self.char1)
        self.assertIn("Visible Lore", result)


class TestCmdLoreSubmitAndRead(EvenniaCommandTest):
    def test_submit_inline_via_editor_save(self):
        """Simulate what start_new_edit callback does on save."""
        from evennia_lore.commands import _lore_submit_save

        self.char1.ndb._lore_submit_ctx = {"title": "My Entry", "scene_arg": None}
        _lore_submit_save(self.char1, "Full body content.")
        entry = LoreEntry.objects.get(title="My Entry")
        self.assertEqual(entry.body, "Full body content.")
        self.assertEqual(entry.author, self.char1)

    def test_read_existing(self):
        entry = _make_entry("Readable", author=self.char1, body="Body text here.")
        result = self.call(CmdLore(), f"/read #{entry.entry_number}", caller=self.char1)
        self.assertIn("Readable", result)
        self.assertIn("Body text here.", result)

    def test_read_restricted_shows_stub(self):
        entry = _make_entry(
            "Restricted", author=self.char1, body="Secret.", privacy=LoreEntry.Privacy.RESTRICTED
        )
        result = self.call(CmdLore(), f"/read #{entry.entry_number}", caller=self.char2)
        self.assertIn("RESTRICTED", result)
        self.assertNotIn("Secret.", result)


class TestCmdLoreApproveReject(EvenniaCommandTest):
    def test_approve_publishes_submitted_entry(self):
        from django.test import override_settings

        with override_settings(LORE_REQUIRE_APPROVAL=True):
            entry = _make_entry("Pending", author=self.char2)
        self.call(CmdLore(), f"/approve #{entry.entry_number}", caller=self.char1)
        entry.refresh_from_db()
        self.assertEqual(entry.status, LoreEntry.Status.PUBLISHED)

    def test_non_staff_cannot_approve(self):
        from django.test import override_settings

        with override_settings(LORE_REQUIRE_APPROVAL=True):
            entry = _make_entry("Pending2", author=self.char1)
        result = self.call(CmdLore(), f"/approve #{entry.entry_number}", caller=self.char2)
        self.assertIn("staff", result)


class TestCmdShare(EvenniaCommandTest):
    def test_share_creates_acquisition(self):
        entry = _make_entry("Shareable", author=self.char1)
        # char1 (staff) shares directly
        self.call(CmdShare(), f"{self.char2.key}=#{entry.entry_number}", caller=self.char1)
        self.assertTrue(
            LoreAcquisition.objects.filter(
                entry=entry,
                character=self.char2,
                source=LoreAcquisition.Source.SHARED,
            ).exists()
        )


class TestCmdForget(EvenniaCommandTest):
    def test_forget_removes_acquisition(self):
        entry = _make_entry("Forgettable", author=self.char1)
        LoreAcquisition.objects.create(
            entry=entry, character=self.char2, character_name=self.char2.key
        )
        self.call(CmdForget(), f"#{entry.entry_number}", caller=self.char2)
        self.assertFalse(LoreAcquisition.objects.filter(entry=entry, character=self.char2).exists())


class TestCmdInvestigate(EvenniaCommandTest):
    def test_clear_lean(self):
        self.char1.lore_lean_type = "tag"
        self.char1.lore_lean_value = "Magic"
        self.call(CmdInvestigate(), "/clear", caller=self.char1)
        self.assertIsNone(self.char1.lore_lean_type)

    def test_tag_lean_sets_attributes(self):
        _make_tag("Alchemy")
        self.call(CmdInvestigate(), "/tag Alchemy", caller=self.char1)
        self.assertEqual(self.char1.lore_lean_type, "tag")
        self.assertEqual(self.char1.lore_lean_value, "Alchemy")

    def test_entry_lean_sets_number(self):
        entry = _make_entry("The Codex", author=self.char1)
        self.call(CmdInvestigate(), f"/entry #{entry.entry_number}", caller=self.char1)
        self.assertEqual(self.char1.lore_lean_type, "entry")
        self.assertEqual(self.char1.lore_lean_value, entry.entry_number)


# ---------------------------------------------------------------------------
# API privacy (serializer-level)
# ---------------------------------------------------------------------------


class TestLoreAPIPrivacy(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.restricted = _make_entry(
            "Secret", author=self.char1, privacy=LoreEntry.Privacy.RESTRICTED, body="classified"
        )

    def _make_request(self, is_staff_val=False):
        req = MagicMock()
        req.user.is_authenticated = True
        req.user.locks.check_lockstring.return_value = is_staff_val
        return req

    def test_restricted_body_hidden_from_non_staff(self):
        from evennia_lore.api.serializers import LoreEntrySerializer

        req = self._make_request(is_staff_val=False)
        # No acquisition for char2 → body should be None
        req.user.get_all_puppets.return_value = [self.char2]
        req.user.account = req.user
        data = LoreEntrySerializer(self.restricted, context={"request": req}).data
        self.assertIsNone(data["body"])

    def test_restricted_body_visible_to_staff(self):
        from evennia_lore.api.serializers import LoreEntrySerializer

        req = self._make_request(is_staff_val=True)
        data = LoreEntrySerializer(self.restricted, context={"request": req}).data
        self.assertEqual(data["body"], "classified")

    def test_restricted_body_visible_after_acquisition(self):
        from evennia_lore.api.serializers import LoreEntrySerializer

        LoreAcquisition.objects.create(
            entry=self.restricted, character=self.char2, character_name=self.char2.key
        )
        req = self._make_request(is_staff_val=False)
        req.user.get_all_puppets.return_value = [self.char2]
        req.user.account = req.user
        data = LoreEntrySerializer(self.restricted, context={"request": req}).data
        self.assertEqual(data["body"], "classified")


# ---------------------------------------------------------------------------
# Web pages: render for real
# ---------------------------------------------------------------------------


@override_settings(ROOT_URLCONF=__name__)
class LoreWebRenderTestCase(EvenniaTest):
    """
    Shared machinery for rendering lore pages for real.

    A CBV returns a lazy TemplateResponse, so a test that only inspects
    context_data never compiles the template — which is how a lore list that
    raised TemplateSyntaxError on every empty result shipped under a green
    suite. Every case below calls response.render().

    RequestFactory + direct view invocation rather than Django's TestClient,
    because the TestClient triggers an Evennia template-context RecursionError
    on authenticated HTML pages.

    EvenniaTest defaults: account/char1 = Developer (staff); account2/char2 =
    non-staff. Bare test accounts have no sessions, so get_all_puppets()
    returns [] — every case that needs a character patches it.
    """

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _request(self, path_="/lore/", user=None):
        request = self.factory.get(path_)
        request.user = AnonymousUser() if user is None else user
        # Evennia's general_context processor reads request.session["puppet"]
        # for any authenticated user, and RequestFactory attaches no session.
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        return request

    def _render(self, view, *, path_="/lore/", user=None, puppet=None, **kwargs):
        request = self._request(path_, user)
        if puppet is None:
            response = view.as_view()(request, **kwargs)
        else:
            with patch.object(user, "get_all_puppets", return_value=[puppet]):
                response = view.as_view()(request, **kwargs)
        response.render()
        return response.content.decode()


class TestLoreListRenders(LoreWebRenderTestCase):
    def setUp(self):
        super().setUp()
        self.tag = _make_tag("Ruins", is_major=True)
        self.entry = _make_entry(title="The Sunken Road", author=self.char1, summary="A road.")
        self.entry.tags.add(self.tag)

    def test_list_renders_entries_and_theme_badges(self):
        html = self._render(LoreListView)
        self.assertIn("The Sunken Road", html)
        self.assertIn("Ruins", html)
        self.assertIn(f'href="/lore/{self.entry.pk}/"', html)

    def test_empty_list_renders_its_empty_state(self):
        LoreEntry.objects.all().delete()
        self.assertIn("No lore entries found.", self._render(LoreListView))

    def test_empty_filtered_list_says_so(self):
        # The message used to be built as message="...{% if %}...{% endif %}",
        # which does not parse — a tag inside a quoted argument ends the outer
        # tag at the first %}. Both branches are now separate includes.
        html = self._render(LoreListView, path_="/lore/?search=nothing")
        self.assertIn("No lore entries found matching your filters.", html)
        self.assertIn("Clear", html)

    def test_pagination_links_carry_the_active_filter(self):
        # The template used to try to accumulate the query string with nested
        # {% with %} blocks, which cannot work — a {% with %} assignment dies
        # at its own {% endwith %} — so page 2 dropped the filter and showed
        # page 2 of the unfiltered list.
        for i in range(3):
            _make_entry(title=f"Sunken Chapter {i}", author=self.char1)
        request = self._request("/lore/?search=Sunken")
        response = LoreListView.as_view(paginate_by=2)(request)
        response.render()
        html = response.content.decode()
        self.assertIn('href="?search=Sunken&page=2"', html)

    def test_staff_see_the_approval_queue_link(self):
        html = self._render(LoreListView, user=self.account, puppet=self.char1)
        self.assertIn('href="/lore/queue/"', html)

    def test_anonymous_visitors_are_offered_no_authoring_links(self):
        html = self._render(LoreListView)
        self.assertNotIn('href="/lore/new/"', html)


class TestLoreDetailRenders(LoreWebRenderTestCase):
    def setUp(self):
        super().setUp()
        self.entry = _make_entry(
            title="The Sunken Road",
            author=self.char1,
            body="It runs beneath the harbour.",
            summary="A road.",
        )

    def test_detail_renders_the_body_of_a_public_entry(self):
        html = self._render(LoreDetailView, pk=self.entry.pk)
        self.assertIn("The Sunken Road", html)
        self.assertIn("It runs beneath the harbour.", html)

    def test_restricted_entry_renders_a_stub_instead_of_the_body(self):
        restricted = _make_entry(
            title="The Ninth Seal",
            author=self.char1,
            body="Secret text.",
            summary="Something is sealed.",
            privacy=LoreEntry.Privacy.RESTRICTED,
        )
        html = self._render(LoreDetailView, pk=restricted.pk)
        self.assertIn("Restricted Content", html)
        self.assertIn("Something is sealed.", html)
        self.assertNotIn("Secret text.", html)

    def test_author_is_offered_edit_and_history(self):
        html = self._render(LoreDetailView, user=self.account, puppet=self.char1, pk=self.entry.pk)
        self.assertIn(f'href="/lore/{self.entry.pk}/edit/"', html)
        self.assertIn(f'href="/lore/{self.entry.pk}/history/"', html)

    @override_settings(LORE_REQUIRE_APPROVAL=True)
    def test_staff_are_offered_approve_and_reject_on_a_submitted_entry(self):
        submitted = _make_entry(title="Draft Lore", author=self.char2)
        self.assertEqual(submitted.status, LoreEntry.Status.SUBMITTED)
        html = self._render(LoreDetailView, user=self.account, puppet=self.char1, pk=submitted.pk)
        self.assertIn(f'action="/lore/{submitted.pk}/approve/"', html)
        self.assertIn(f'action="/lore/{submitted.pk}/reject/"', html)

    # -- partner links ------------------------------------------------------
    #
    # region_list / linked_scenes / linked_plots are populated by resolving
    # evennia_regions, evennia_scenes and evennia_plots models at request time.
    # None of the three is installed during a contrib-only run, so the lists
    # are always empty here and the view can never reach those branches. The
    # two cases below render the template directly against the real view
    # context with stub partner objects spliced in — the one thing this
    # environment cannot produce for itself.

    def _detail_html(self, **extra):
        request = self._request(f"/lore/{self.entry.pk}/")
        view = LoreDetailView()
        view.request = request
        view.kwargs = {"pk": self.entry.pk}
        view.object = self.entry
        context = view.get_context_data()
        context.update(extra)
        return render_to_string("evennia_lore/lore_detail.html", context, request=request)

    def _partners(self):
        return {
            "region_list": [SimpleNamespace(pk=7, name="The Harbour")],
            "linked_scenes": [SimpleNamespace(pk=8, title="Low Tide")],
            "linked_plots": [SimpleNamespace(pk=9, name="The Drowning")],
        }

    def test_partner_links_render_as_plain_text_when_routes_are_unmounted(self):
        html = self._detail_html(**self._partners())
        for name in ("The Harbour", "Low Tide", "The Drowning"):
            self.assertIn(name, html)
        # A bare {% url %} raised NoReverseMatch here, turning the whole detail
        # page into a 500. {% url ... as %} assigns "" instead, so the partner
        # name renders as plain text.
        self.assertNotIn("/regions/7/", html)
        self.assertNotIn("/scenes/8/", html)
        self.assertNotIn("/plots/9/", html)

    @override_settings(ROOT_URLCONF=PartnerRoutesUrlConf)
    def test_partner_links_become_links_once_the_routes_are_mounted(self):
        html = self._detail_html(**self._partners())
        self.assertIn('href="/regions/7/"', html)
        self.assertIn('href="/scenes/8/"', html)
        self.assertIn('href="/plots/9/"', html)


class TestLoreCompendiumRenders(LoreWebRenderTestCase):
    def test_compendium_lists_acquired_entries(self):
        entry = _make_entry(title="Tidebound", author=self.char1)
        LoreAcquisition.objects.create(
            entry=entry,
            character=self.char2,
            character_name=self.char2.key,
            source=LoreAcquisition.Source.SHARED,
        )
        html = self._render(
            LoreCompendiumView, path_="/lore/mine/", user=self.account2, puppet=self.char2
        )
        self.assertIn("Tidebound", html)
        self.assertIn("Shared", html)

    def test_empty_compendium_renders_its_empty_state(self):
        html = self._render(
            LoreCompendiumView, path_="/lore/mine/", user=self.account2, puppet=self.char2
        )
        self.assertIn("acquired any lore yet", html)


class TestLoreQueueRenders(LoreWebRenderTestCase):
    @override_settings(LORE_REQUIRE_APPROVAL=True)
    def test_queue_lists_submitted_entries_with_review_actions(self):
        entry = _make_entry(title="Pending Lore", author=self.char2)
        html = self._render(
            LoreApprovalQueueView, path_="/lore/queue/", user=self.account, puppet=self.char1
        )
        self.assertIn("Pending Lore", html)
        self.assertIn(f'action="/lore/{entry.pk}/approve/"', html)

    def test_empty_queue_renders_its_empty_state(self):
        html = self._render(
            LoreApprovalQueueView, path_="/lore/queue/", user=self.account, puppet=self.char1
        )
        self.assertIn("No entries awaiting approval.", html)


class TestLoreFormsRender(LoreWebRenderTestCase):
    def test_create_form_renders(self):
        html = self._render(
            LoreCreateView, path_="/lore/new/", user=self.account2, puppet=self.char2
        )
        self.assertIn("Submit Lore Entry", html)
        self.assertIn("Entry details", html)
        self.assertIn("id_title", html)
        self.assertIn('name="csrfmiddlewaretoken"', html)

    def test_edit_form_renders_with_the_existing_entry(self):
        entry = _make_entry(title="Tidebound", author=self.char2, body="Old body.")
        html = self._render(
            LoreEditView,
            path_=f"/lore/{entry.pk}/edit/",
            user=self.account2,
            puppet=self.char2,
            pk=entry.pk,
        )
        self.assertIn("Edit: Tidebound", html)
        self.assertIn("Old body.", html)
        self.assertIn("Save Changes", html)

    def test_lean_form_renders(self):
        html = self._render(
            LoreLeanView, path_="/lore/lean/", user=self.account2, puppet=self.char2
        )
        self.assertIn("Set Investigation Lean", html)
        self.assertIn("id_lean_type", html)
        self.assertIn("Save Lean", html)


class TestLoreHistoryRenders(LoreWebRenderTestCase):
    def setUp(self):
        super().setUp()
        self.entry = _make_entry(title="Tidebound", author=self.char1, body="New body.")

    def test_history_lists_versions_with_diff_links(self):
        version = LoreVersion.create_version(
            parent=self.entry, content="Old body.", editor=self.char1
        )
        html = self._render(
            LoreVersionHistoryView,
            path_=f"/lore/{self.entry.pk}/history/",
            pk=self.entry.pk,
        )
        self.assertIn(f"v{version.version_number}", html)
        self.assertIn(f'href="/lore/{self.entry.pk}/diff/{version.version_number}/"', html)

    def test_empty_history_renders_its_empty_state(self):
        html = self._render(
            LoreVersionHistoryView,
            path_=f"/lore/{self.entry.pk}/history/",
            pk=self.entry.pk,
        )
        self.assertIn("No version history yet.", html)

    def test_diff_renders_added_and_removed_lines(self):
        version = LoreVersion.create_version(
            parent=self.entry, content="Old body.", editor=self.char1
        )
        html = self._render(
            LoreVersionDiffView,
            path_=f"/lore/{self.entry.pk}/diff/{version.version_number}/",
            pk=self.entry.pk,
            version_number=version.version_number,
        )
        self.assertIn("Old body.", html)
        self.assertIn("New body.", html)
        self.assertIn("added lines", html)

    def test_identical_version_renders_the_no_differences_notice(self):
        version = LoreVersion.create_version(
            parent=self.entry, content=self.entry.body, editor=self.char1
        )
        html = self._render(
            LoreVersionDiffView,
            path_=f"/lore/{self.entry.pk}/diff/{version.version_number}/",
            pk=self.entry.pk,
            version_number=version.version_number,
        )
        self.assertIn("no differences", html)
