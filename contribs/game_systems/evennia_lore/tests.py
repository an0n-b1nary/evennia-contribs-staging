# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_lore.

Covers models, bridges, commands, trickle engine, and API privacy.

Run:
    evennia test --settings test_lore_settings.py evennia_lore
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.db import IntegrityError, transaction
from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(title="Test Lore", author=None, body="", summary="", privacy=None):
    return LoreEntry.create_entry(
        title=title, author=author, body=body, summary=summary, privacy=privacy
    )


def _make_tag(name="Magic", is_major=False):
    return LoreTag.objects.create(name=name, is_major=is_major)


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
        from world.rptracker.models import RPSession

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

    @override_settings(LORE_SESSION_CONTEXT_PROVIDER=None)
    def test_room_weight_5_via_provider_stub(self):
        """Stub provider injecting room_id exercises the room weight path."""
        entry = _make_entry("Room Lore", author=self.char1)
        entry.rooms.add(self.room1)
        session = self._session()

        def stub_provider(s):
            return {"room_id": self.room1.pk, "region_id": None, "thread_ids": set()}

        with (
            override_settings(LORE_SESSION_CONTEXT_PROVIDER="builtins.print"),
            patch(
                "evennia_lore.selection._resolve_context",
                return_value=stub_provider(session),
            ),
        ):
            pool = _build_pool(self.char1, session)
        self.assertEqual(pool[0][1], 5)

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
        from world.rptracker.models import RPSession

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
