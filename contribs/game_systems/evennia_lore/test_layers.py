# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for lore's two layers: kinds, accuracy, OOC notes, affirmation, sealed
notes, notices and the sealed-lore reminder when a plot thread concludes.

The rule under test throughout: the IC content may mislead characters; the
OOC layer (accuracy, OOC notes, affirmation) never misleads players.
"""

import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, override_settings
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from evennia_lore import layers
from evennia_lore.commands import CmdLore
from evennia_lore.layers import LoreLayerError
from evennia_lore.models import LoreAcquisition, LoreEntry, LoreNotice, PlotLoreLink
from evennia_lore.tests import LoreWebRenderTestCase
from evennia_lore.views import (
    LoreAffirmView,
    LoreApprovalQueueView,
    LoreDeclineView,
    LoreDetailView,
    LoreListView,
)

REVIEWS = []


def record_review(title, description):
    """LORE_STAFF_REVIEW_HOOK stand-in."""
    REVIEWS.append((title, description))


HOOK = "evennia_lore.test_layers.record_review"


def _entry(title="The Exile", author=None, body="They were cast out.", **kwargs):
    return LoreEntry.create_entry(title=title, author=author, body=body, **kwargs)


def _hold(entry, character):
    return LoreAcquisition.objects.create(
        entry=entry, character=character, character_name=character.key
    )


class LayerTestMixin:
    def setUp(self):
        super().setUp()
        REVIEWS.clear()
        # Notices are delivered now or kept; choose explicitly per test.
        patcher = patch("evennia_lore.notices.is_online", return_value=False)
        self.is_online = patcher.start()
        self.addCleanup(patcher.stop)


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


class TestLayerRules(EvenniaTest):
    def test_a_fact_is_always_accurate(self):
        with self.assertRaisesMessage(LoreLayerError, "always accurate"):
            layers.validate("fact", "open")

    def test_inaccurate_and_partly_need_notes_saying_what_is_true(self):
        for accuracy in ("inaccurate", "partly"):
            with self.assertRaisesMessage(LoreLayerError, "OOC notes"):
                layers.validate("rumor", accuracy, "  ")
            layers.validate("rumor", accuracy, "Started by a drunk scout.")

    def test_sealed_notes_need_open_accuracy(self):
        with self.assertRaisesMessage(LoreLayerError, "open"):
            layers.validate("legend", "accurate", "", "It's the Shadow.")
        layers.validate("legend", "open", "", "It's the Shadow.")

    def test_unknown_kind_lists_the_choices(self):
        with self.assertRaisesMessage(LoreLayerError, "Fact, Rumor, Legend"):
            layers.validate("myth", "open")

    @override_settings(LORE_KINDS={"truth": "Truth", "gossip": "Gossip"}, LORE_ACCURATE_KINDS=())
    def test_a_game_defines_its_own_kinds(self):
        self.assertEqual(layers.match_kind("GOSSIP"), "gossip")
        self.assertEqual(layers.default_kind(), "truth")
        layers.validate("truth", "open")

    def test_labels_and_matching(self):
        self.assertEqual(layers.match_kind("Legend"), "legend")
        self.assertEqual(layers.match_accuracy("Partly accurate"), "partly")
        self.assertIsNone(layers.match_accuracy("maybe"))
        self.assertEqual(layers.kind_label("old_kind"), "Old Kind")


class TestEntryLayers(EvenniaTest):
    def test_new_entries_default_to_an_accurate_fact(self):
        entry = _entry(author=self.char1)
        self.assertEqual((entry.kind, entry.accuracy), ("fact", "accurate"))

    def test_a_new_rumor_starts_open(self):
        # An author who never says whether a rumor is true is not recorded as saying it is.
        entry = _entry(author=self.char1, kind="rumor")
        self.assertEqual(entry.accuracy, "open")

    def test_create_entry_refuses_a_broken_combination(self):
        with self.assertRaises(LoreLayerError):
            _entry(author=self.char1, kind="rumor", accuracy="inaccurate")
        self.assertFalse(LoreEntry.objects.exists())

    def test_choosing_fact_settles_an_open_entry_as_accurate(self):
        entry = _entry(author=self.char1, kind="rumor")
        entry.update_layers(kind="fact")
        entry.refresh_from_db()
        self.assertEqual((entry.kind, entry.accuracy), ("fact", "accurate"))

    def test_choosing_fact_for_an_inaccurate_entry_is_refused(self):
        entry = _entry(author=self.char1, kind="rumor", accuracy="inaccurate", ooc_notes="False.")
        with self.assertRaisesMessage(LoreLayerError, "always accurate"):
            entry.update_layers(kind="fact")
        entry.refresh_from_db()
        self.assertEqual(entry.kind, "rumor")

    def test_notes_cannot_be_cleared_while_they_explain_an_inaccuracy(self):
        entry = _entry(author=self.char1, kind="rumor", accuracy="inaccurate", ooc_notes="False.")
        with self.assertRaises(LoreLayerError):
            entry.update_layers(ooc_notes="")
        entry.refresh_from_db()
        self.assertEqual(entry.ooc_notes, "False.")

    def test_an_entry_keeps_a_kind_the_game_later_removed(self):
        entry = _entry(author=self.char1, kind="legend")
        with override_settings(LORE_KINDS={"fact": "Fact", "rumor": "Rumor"}):
            entry.update_layers(accuracy="partly", ooc_notes="Half of it.")
            with self.assertRaises(LoreLayerError):
                entry.update_layers(kind="legend2")
        entry.refresh_from_db()
        self.assertEqual((entry.kind, entry.accuracy), ("legend", "partly"))


# ---------------------------------------------------------------------------
# Affirmation
# ---------------------------------------------------------------------------


@override_settings(LORE_STAFF_REVIEW_HOOK=HOOK)
class TestAffirmation(LayerTestMixin, EvenniaTest):
    def test_request_is_public_and_filed_for_staff(self):
        entry = _entry(author=self.char2, kind="rumor")
        entry.request_affirmation(requested_by=self.char2)
        entry.refresh_from_db()
        self.assertEqual(entry.affirmation, "requested")
        self.assertEqual(entry.affirmation_label(), "Affirmation requested")
        self.assertEqual(len(REVIEWS), 1)
        self.assertIn(f"#{entry.entry_number}", REVIEWS[0][0])
        self.assertIn("never makes a rumor's IC claim true", REVIEWS[0][1])

    def test_a_failing_hook_does_not_undo_the_request(self):
        entry = _entry(author=self.char2)
        with (
            patch(f"{__name__}.record_review", side_effect=RuntimeError("down")),
            self.assertLogs("evennia", level="ERROR"),
        ):
            entry.request_affirmation(requested_by=self.char2)
        entry.refresh_from_db()
        self.assertEqual(entry.affirmation, "requested")

    def test_affirmation_pins_what_staff_saw(self):
        entry = _entry(author=self.char2, kind="rumor", accuracy="inaccurate", ooc_notes="False.")
        entry.affirm(affirmed_by=self.char1)
        entry.refresh_from_db()
        self.assertEqual(entry.affirmation_label(), "Affirmed by staff")
        self.assertEqual(entry.affirmed_by_name, self.char1.key)
        self.assertFalse(entry.edited_since_affirmation)
        # An affirmed, inaccurate rumor stays inaccurate.
        self.assertEqual(entry.accuracy, "inaccurate")

    def test_any_later_edit_shows_until_staff_look_again(self):
        entry = _entry(author=self.char2, kind="rumor", accuracy="partly", ooc_notes="Half.")
        entry.affirm(affirmed_by=self.char1)
        for change in ({"ooc_notes": "Half, and the rest."}, {"accuracy": "open"}):
            entry.update_layers(**change)
            self.assertTrue(entry.edited_since_affirmation)
            self.assertEqual(entry.affirmation_label(), "Affirmed by staff, edited since")
            entry.affirm(affirmed_by=self.char1)
        entry.edit_body("A new telling.", editor=self.char2)
        self.assertTrue(entry.edited_since_affirmation)
        # The affirmed body is kept as the version after affirmed_version.
        kept = entry.versions.get(version_number=entry.affirmed_version + 1)
        self.assertEqual(kept.content, "They were cast out.")

    def test_re_requesting_needs_a_reason(self):
        entry = _entry(author=self.char2)
        entry.request_affirmation(requested_by=self.char2)
        with self.assertRaisesMessage(LoreLayerError, "already requested"):
            entry.request_affirmation(requested_by=self.char2)
        entry.affirm(affirmed_by=self.char1)
        with self.assertRaisesMessage(LoreLayerError, "already affirmed"):
            entry.request_affirmation(requested_by=self.char2)
        entry.update_layers(ooc_notes="More context.")
        entry.request_affirmation(requested_by=self.char2)
        self.assertEqual(entry.affirmation, "requested")

    @override_settings(LORE_REQUIRE_APPROVAL=True)
    def test_unpublished_entries_cannot_be_affirmed(self):
        entry = _entry(author=self.char2)
        with self.assertRaisesMessage(LoreLayerError, "isn't published"):
            entry.affirm(affirmed_by=self.char1)
        with self.assertRaisesMessage(LoreLayerError, "isn't published"):
            entry.request_affirmation(requested_by=self.char2)

    def test_a_decline_is_the_authors_business(self):
        entry = _entry(author=self.char2)
        with self.assertRaisesMessage(LoreLayerError, "Say why"):
            entry.decline(declined_by=self.char1, note=" ")
        entry.decline(declined_by=self.char1, note="Name the source in the OOC notes.")
        entry.refresh_from_db()
        self.assertEqual(entry.affirmation_label(show_decline=True), "Affirmation declined")
        self.assertEqual(entry.affirmation_label(), "")
        self.assertEqual(entry.public_affirmation(), "none")

    def test_decisions_reach_an_offline_author_at_next_login(self):
        from evennia.server.signals import SIGNAL_OBJECT_POST_PUPPET

        entry = _entry(author=self.char2)
        entry.decline(declined_by=self.char1, note="Needs a source.")
        entry.affirm(affirmed_by=self.char1)
        self.assertEqual(LoreNotice.objects.filter(character=self.char2).count(), 2)
        with patch.object(self.char2, "msg") as msg:
            SIGNAL_OBJECT_POST_PUPPET.send(sender=self.char2, account=self.account2, session=None)
        text = msg.call_args[0][0]
        self.assertLess(text.index("declined"), text.index("affirmed"))
        self.assertIn("Needs a source.", text)
        self.assertFalse(LoreNotice.objects.filter(character=self.char2).exists())

    def test_an_online_author_is_told_at_once(self):
        self.is_online.return_value = True
        entry = _entry(author=self.char2)
        with patch.object(self.char2, "msg") as msg:
            entry.affirm(affirmed_by=self.char1)
        self.assertIn("affirmed", msg.call_args[0][0])
        self.assertFalse(LoreNotice.objects.exists())

    def test_staff_affirming_their_own_entry_get_no_notice(self):
        entry = _entry(author=self.char1)
        entry.affirm(affirmed_by=self.char1)
        self.assertFalse(LoreNotice.objects.exists())


class TestReviewedEntriesMigration(EvenniaTest):
    def test_reviewed_entries_become_affirmed_as_they_stand(self):
        with override_settings(LORE_REQUIRE_APPROVAL=True):
            reviewed = _entry("Reviewed", author=self.char2)
        reviewed.publish(reviewed_by=self.char1)
        reviewed.edit_body("Revised.", editor=self.char2)
        plain = _entry("Unreviewed", author=self.char2)

        migration = import_module("evennia_lore.migrations.0004_affirm_reviewed_entries")
        migration.affirm_reviewed(apps, None)

        reviewed.refresh_from_db()
        plain.refresh_from_db()
        self.assertEqual(reviewed.affirmation, "affirmed")
        self.assertEqual(reviewed.affirmed_by_name, self.char1.key)
        self.assertEqual(reviewed.affirmed_version, 1)
        self.assertFalse(reviewed.edited_since_affirmation)
        self.assertEqual(plain.affirmation, "none")


# ---------------------------------------------------------------------------
# Sealed notes
# ---------------------------------------------------------------------------


class TestSealedNotes(LayerTestMixin, EvenniaTest):
    def _legend(self):
        return _entry(
            "The Grudge", author=self.char1, kind="legend", ooc_notes="Told in every camp."
        )

    def test_sealing_needs_open_accuracy(self):
        entry = _entry("Sure Thing", author=self.char1, kind="legend", accuracy="accurate")
        with self.assertRaisesMessage(LoreLayerError, "open"):
            entry.seal("The twist.")
        entry = self._legend()
        entry.seal("It was the Shadow all along.")
        with self.assertRaisesMessage(LoreLayerError, "open"):
            entry.update_layers(accuracy="accurate")

    def test_unseal_publishes_settles_and_tells_every_holder(self):
        from evennia_lore.signals import lore_unsealed

        entry = self._legend()
        entry.seal("It was the Shadow all along.")
        _hold(entry, self.char1)
        _hold(entry, self.char2)
        self.is_online.side_effect = lambda character: character == self.char1
        received = []

        def _receiver(sender, entry, by, **kwargs):
            received.append((entry.pk, by))

        lore_unsealed.connect(_receiver, weak=False)
        self.addCleanup(lore_unsealed.disconnect, _receiver)
        with patch.object(self.char1, "msg") as msg:
            told = entry.unseal("partly", unsealed_by=self.char1)

        entry.refresh_from_db()
        self.assertEqual(told, 2)
        self.assertEqual(entry.ooc_notes, "Told in every camp.\n\nIt was the Shadow all along.")
        self.assertEqual((entry.accuracy, entry.sealed_notes), ("partly", ""))
        self.assertIn("New light on", msg.call_args[0][0])
        self.assertEqual(LoreNotice.objects.get().character, self.char2)
        self.assertEqual(received, [(entry.pk, self.char1)])

    def test_unseal_keeps_a_current_affirmation(self):
        entry = self._legend()
        entry.seal("The twist.")
        entry.affirm(affirmed_by=self.char1)
        entry.unseal("accurate", unsealed_by=self.char1)
        self.assertEqual(entry.affirmation, "affirmed")
        self.assertFalse(entry.edited_since_affirmation)

    def test_unseal_refuses_an_unknown_accuracy(self):
        entry = self._legend()
        entry.seal("The twist.")
        with self.assertRaises(LoreLayerError):
            entry.unseal("bogus")
        entry.refresh_from_db()
        self.assertTrue(entry.has_sealed_notes)

    def test_nothing_to_unseal(self):
        with self.assertRaisesMessage(LoreLayerError, "no sealed notes"):
            self._legend().unseal("open")

    def test_an_empty_seal_removes_it_without_publishing(self):
        entry = self._legend()
        entry.seal("The twist.")
        entry.seal("")
        entry.refresh_from_db()
        self.assertEqual((entry.sealed_notes, entry.ooc_notes), ("", "Told in every camp."))


@unittest.skipUnless(apps.is_installed("evennia_plots"), "evennia-plots not installed")
@override_settings(LORE_STAFF_REVIEW_HOOK=HOOK)
class TestSealedLoreReminder(LayerTestMixin, EvenniaTest):
    def setUp(self):
        super().setUp()
        from evennia_plots.models import PlotThread

        self.thread = PlotThread.create_thread(name="The Long Night", creator=self.char2)
        self.thread.activate()
        self.sealed = _entry("Sealed", author=self.char1, kind="legend")
        self.sealed.seal("The twist.")
        self.open = _entry("Unsealed", author=self.char1, kind="legend")
        for entry in (self.sealed, self.open):
            PlotLoreLink.objects.create(thread_id=self.thread.pk, entry=entry)

    def test_a_player_who_concludes_is_reminded_and_staff_are_told(self):
        self.thread.conclude(concluded_by=self.char2)
        notice = LoreNotice.objects.get(character=self.char2)
        self.assertIn(f"#{self.sealed.entry_number}", notice.message)
        self.assertNotIn(f"#{self.open.entry_number}", notice.message)
        self.assertEqual(len(REVIEWS), 1)
        self.assertIn("The Long Night", REVIEWS[0][1])

    def test_staff_who_conclude_are_reminded_without_a_ticket(self):
        self.thread.conclude(concluded_by=self.char1)
        self.assertTrue(LoreNotice.objects.filter(character=self.char1).exists())
        self.assertEqual(REVIEWS, [])

    def test_without_a_concluder_the_creator_is_reminded(self):
        self.thread.conclude()
        self.assertTrue(LoreNotice.objects.filter(character=self.char2).exists())

    def test_no_sealed_lore_no_reminder(self):
        self.sealed.seal("")
        self.thread.conclude(concluded_by=self.char2)
        self.assertFalse(LoreNotice.objects.exists())
        self.assertEqual(REVIEWS, [])


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@override_settings(LORE_STAFF_REVIEW_HOOK=HOOK)
class TestLayerCommands(LayerTestMixin, EvenniaCommandTest):
    """char1 is staff; char2 is a player."""

    def test_submit_with_a_kind_switch(self):
        from evennia_lore.commands import _lore_submit_save

        self.char2.ndb._lore_submit_ctx = {"title": "Eyes Open", "scene_arg": None, "kind": "rumor"}
        _lore_submit_save(self.char2, "The royal sleeps with their eyes open.")
        entry = LoreEntry.objects.get(title="Eyes Open")
        self.assertEqual((entry.kind, entry.accuracy), ("rumor", "open"))

    def test_submit_switch_names_the_kind_or_is_refused(self):
        with patch.object(CmdLore, "start_new_edit"):
            self.call(CmdLore(), "/submit/rumor Eyes Open", caller=self.char2)
            self.assertEqual(self.char2.ndb._lore_submit_ctx["kind"], "rumor")
            self.call(CmdLore(), "/submit/scene/legend 4=Old Eyes", caller=self.char2)
            self.assertEqual(self.char2.ndb._lore_submit_ctx["kind"], "legend")
            self.char2.ndb._lore_submit_ctx = None
            # An unknown kind must not quietly file the entry as an accurate Fact.
            result = self.call(CmdLore(), "/submit/rumour Eyes Open", caller=self.char2)
        self.assertIn("Unknown kind 'rumour'", result)
        self.assertIsNone(self.char2.ndb._lore_submit_ctx)

    def test_kind_accuracy_and_notes(self):
        entry = _entry(author=self.char2, kind="rumor")
        n = entry.entry_number
        self.call(CmdLore(), f"/kind #{n}=Legend", caller=self.char2)
        result = self.call(CmdLore(), f"/accuracy #{n}=inaccurate", caller=self.char2)
        self.assertIn("+lore/ooc", result)
        self.call(CmdLore(), f"/ooc #{n}=Started by a bored scout.", caller=self.char2)
        self.call(CmdLore(), f"/accuracy #{n}=inaccurate", caller=self.char2)
        entry.refresh_from_db()
        self.assertEqual(
            (entry.kind, entry.accuracy, entry.ooc_notes),
            ("legend", "inaccurate", "Started by a bored scout."),
        )

    def test_others_cannot_change_the_layers(self):
        entry = _entry(author=self.char1, kind="rumor")
        result = self.call(
            CmdLore(), f"/accuracy #{entry.entry_number}=accurate", caller=self.char2
        )
        self.assertIn("Only the entry author", result)

    def test_read_shows_both_layers_with_labels(self):
        entry = _entry(
            author=self.char2, kind="rumor", accuracy="inaccurate", ooc_notes="It's false."
        )
        result = self.call(CmdLore(), f"/read #{entry.entry_number}", caller=self.char2)
        self.assertIn("[Rumor]", result)
        self.assertIn("In character:", result)
        self.assertIn("Out of character (always true):", result)
        self.assertIn("Accuracy: Inaccurate", result)
        self.assertIn("It's false.", result)

    def test_read_hides_sealed_notes_from_players_only(self):
        entry = _entry(author=self.char1, kind="legend")
        entry.seal("It was the Shadow.")
        n = entry.entry_number
        player = self.call(CmdLore(), f"/read #{n}", caller=self.char2)
        self.assertIn("sealed until the story settles this", player)
        self.assertNotIn("It was the Shadow.", player)
        staff = self.call(CmdLore(), f"/read #{n}", caller=self.char1)
        self.assertIn("It was the Shadow.", staff)

    def test_restricted_entries_hide_the_ooc_layer_until_acquired(self):
        entry = _entry(
            author=self.char1,
            kind="rumor",
            accuracy="inaccurate",
            ooc_notes="Secret truth.",
            privacy=LoreEntry.Privacy.RESTRICTED,
        )
        result = self.call(CmdLore(), f"/read #{entry.entry_number}", caller=self.char2)
        self.assertIn("RESTRICTED", result)
        self.assertNotIn("Secret truth.", result)
        self.assertNotIn("Accuracy", result)

    def test_staff_can_read_restricted_sealed_lore_without_acquiring_it(self):
        entry = _entry(author=self.char2, kind="legend", privacy=LoreEntry.Privacy.RESTRICTED)
        entry.seal("A truth for staff to review.")
        result = self.call(CmdLore(), f"/read #{entry.entry_number}", caller=self.char1)
        self.assertIn(entry.body, result)
        self.assertIn(entry.sealed_notes, result)
        self.assertFalse(entry.acquisitions.exists())

    def test_author_requests_staff_affirm_or_decline(self):
        entry = _entry(author=self.char2, kind="rumor")
        n = entry.entry_number
        result = self.call(CmdLore(), f"/affirm #{n}", caller=self.char2)
        self.assertIn("Affirmation requested", result)
        queue = self.call(CmdLore(), "/queue", caller=self.char1)
        self.assertIn("Affirmation Requests", queue)
        self.assertIn(f"#{n}", queue)
        self.call(CmdLore(), f"/decline #{n}=Say where it started.", caller=self.char1)
        author_view = self.call(CmdLore(), f"/read #{n}", caller=self.char2)
        self.assertIn("Say where it started.", author_view)
        self.call(CmdLore(), f"/affirm #{n}", caller=self.char1)
        entry.refresh_from_db()
        self.assertEqual(entry.affirmation, "affirmed")

    def test_a_decline_is_invisible_to_other_players(self):
        entry = _entry(author=self.char1)
        entry.decline(declined_by=self.char1, note="Private note.")
        result = self.call(CmdLore(), f"/read #{entry.entry_number}", caller=self.char2)
        self.assertNotIn("declined", result.lower())
        self.assertNotIn("Private note.", result)

    def test_only_the_author_may_request(self):
        entry = _entry(author=self.char1)
        result = self.call(CmdLore(), f"/affirm #{entry.entry_number}", caller=self.char2)
        self.assertIn("Only an entry's author", result)

    def test_players_cannot_decline_seal_or_unseal(self):
        entry = _entry(author=self.char2, kind="legend")
        n = entry.entry_number
        for switch in (f"/decline #{n}=no", f"/seal #{n}=x", f"/unseal #{n}=open"):
            self.assertIn("Only staff", self.call(CmdLore(), switch, caller=self.char2))

    def test_seal_says_at_once_when_accuracy_isnt_open(self):
        entry = _entry(author=self.char1, kind="legend", accuracy="accurate")
        result = self.call(CmdLore(), f"/seal #{entry.entry_number}", caller=self.char1)
        self.assertIn("=open", result)
        self.assertIsNone(getattr(self.char1.ndb, "_lore_layer_ctx", None))

    def test_seal_and_unseal_in_game(self):
        entry = _entry(author=self.char1, kind="legend")
        n = entry.entry_number
        self.call(CmdLore(), f"/seal #{n}=The twist.", caller=self.char1)
        result = self.call(CmdLore(), f"/unseal #{n}=partly", caller=self.char1)
        self.assertIn("0 holders told", result)
        entry.refresh_from_db()
        self.assertEqual((entry.ooc_notes, entry.accuracy), ("The twist.", "partly"))

    def test_browse_shows_kind_and_affirmation(self):
        entry = _entry(author=self.char1, kind="legend")
        entry.affirm(affirmed_by=self.char1)
        result = self.call(CmdLore(), "", caller=self.char2)
        self.assertIn("[Legend]", result)
        self.assertIn("[Affirmed by staff]", result)


class TestOocEditor(LayerTestMixin, EvenniaCommandTest):
    def test_editor_saves_through_the_rules(self):
        from evennia_lore.commands import _layer_save

        entry = _entry(author=self.char2, kind="rumor", accuracy="partly", ooc_notes="Half.")
        self.char2.ndb._lore_layer_ctx = {"pk": entry.pk, "field": "ooc_notes"}
        with patch.object(self.char2, "msg") as msg:
            self.assertFalse(_layer_save(self.char2, "   "))
        self.assertIn("OOC notes", msg.call_args[0][0])
        self.assertTrue(_layer_save(self.char2, "Half, and the other half is a lie."))
        entry.refresh_from_db()
        self.assertEqual(entry.ooc_notes, "Half, and the other half is a lie.")


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------


class TestLayerPages(LayerTestMixin, LoreWebRenderTestCase):
    def setUp(self):
        super().setUp()
        self.entry = _entry(
            author=self.char2, kind="rumor", accuracy="inaccurate", ooc_notes="Nobody was exiled."
        )

    def test_detail_shows_both_layers(self):
        html = self._render(LoreDetailView, pk=self.entry.pk)
        self.assertIn("In character", html)
        self.assertIn("Out of character", html)
        self.assertIn("Inaccurate", html)
        self.assertIn("Nobody was exiled.", html)
        self.assertIn("Rumor", html)

    def test_sealed_notes_render_for_staff_only(self):
        legend = _entry("The Grudge", author=self.char1, kind="legend")
        legend.seal("The Shadow did it.")
        visitor = self._render(LoreDetailView, pk=legend.pk)
        self.assertNotIn("The Shadow did it.", visitor)
        self.assertIn("sealed until the story settles this", visitor)
        staff = self._render(LoreDetailView, user=self.account, puppet=self.char1, pk=legend.pk)
        self.assertIn("The Shadow did it.", staff)

    def test_author_is_offered_a_request_and_sees_a_decline(self):
        html = self._render(LoreDetailView, user=self.account2, puppet=self.char2, pk=self.entry.pk)
        self.assertIn("Request affirmation", html)
        self.entry.decline(declined_by=self.char1, note="Cite the camp.")
        author = self._render(
            LoreDetailView, user=self.account2, puppet=self.char2, pk=self.entry.pk
        )
        self.assertIn("Cite the camp.", author)
        visitor = self._render(LoreDetailView, pk=self.entry.pk)
        self.assertNotIn("Cite the camp.", visitor)
        self.assertNotIn("declined", visitor.lower())

    def test_staff_are_offered_affirm_and_decline(self):
        html = self._render(LoreDetailView, user=self.account, puppet=self.char1, pk=self.entry.pk)
        self.assertIn(f'action="/lore/{self.entry.pk}/affirm/"', html)
        self.assertIn(f'action="/lore/{self.entry.pk}/decline/"', html)
        self.assertIn('for="id_note"', html)

    def test_list_filters_by_kind_and_never_by_decline(self):
        fact = _entry("Plain Fact", author=self.char1)
        fact.decline(declined_by=self.char1, note="x")
        html = self._render(LoreListView, path_="/lore/?kind=rumor")
        self.assertIn("The Exile", html)
        self.assertNotIn("Plain Fact", html)
        html = self._render(LoreListView, path_="/lore/?affirmation=declined")
        self.assertIn("Plain Fact", html)  # ignored: declines aren't a public filter

    def test_queue_lists_affirmation_requests(self):
        self.entry.request_affirmation(requested_by=self.char2)
        html = self._render(
            LoreApprovalQueueView, user=self.account, puppet=self.char1, path_="/lore/queue/"
        )
        self.assertIn("Affirmation requests", html)
        self.assertIn("The Exile", html)


@override_settings(ROOT_URLCONF="evennia_lore.tests")
class TestAffirmationViews(LayerTestMixin, EvenniaTest):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.entry = _entry(author=self.char2, kind="rumor")

    def _post(self, view, user, puppet, data=None):
        request = self.factory.post("/", data or {})
        request.user = user
        with patch.object(user, "get_all_puppets", return_value=[puppet]):
            return view.as_view()(request, pk=self.entry.pk)

    def test_author_requests_and_staff_affirm(self):
        self._post(LoreAffirmView, self.account2, self.char2)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.affirmation, "requested")
        self._post(LoreAffirmView, self.account, self.char1)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.affirmation, "affirmed")

    def test_other_players_may_not_request(self):
        other = _entry("Staff Entry", author=self.char1)
        request = self.factory.post("/")
        request.user = self.account2
        with (
            patch.object(self.account2, "get_all_puppets", return_value=[self.char2]),
            self.assertRaises(PermissionDenied),
        ):
            LoreAffirmView.as_view()(request, pk=other.pk)

    def test_decline_needs_staff_and_a_note(self):
        with self.assertRaises(PermissionDenied):
            self._post(LoreDeclineView, self.account2, self.char2, {"note": "no"})
        self._post(LoreDeclineView, self.account, self.char1, {"note": ""})
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.affirmation, "none")
        self._post(LoreDeclineView, self.account, self.char1, {"note": "Cite it."})
        self.entry.refresh_from_db()
        self.assertEqual(
            (self.entry.affirmation, self.entry.affirmation_note), ("declined", "Cite it.")
        )


class TestLayerForms(EvenniaTest):
    @override_settings(LORE_DEFAULT_KIND="legend")
    def test_new_form_uses_the_configured_default_kind(self):
        from evennia_lore.forms import LoreEntryCreateForm

        form = LoreEntryCreateForm()
        self.assertEqual(form["kind"].value(), "legend")

    def test_create_form_enforces_the_rules(self):
        from evennia_lore.forms import LoreEntryCreateForm

        form = LoreEntryCreateForm(
            data={"title": "A Rumor", "kind": "rumor", "accuracy": "inaccurate", "body": "x"}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("OOC notes", str(form.non_field_errors()))
        form = LoreEntryCreateForm(
            data={
                "title": "A Rumor",
                "kind": "rumor",
                "accuracy": "",
                "body": "x",
                "privacy": "public",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["accuracy"], "open")

    def test_edit_form_respects_sealed_notes(self):
        from evennia_lore.forms import LoreEntryEditForm

        entry = _entry(author=self.char1, kind="legend")
        entry.seal("Twist.")
        data = {
            "title": entry.title,
            "kind": "legend",
            "accuracy": "accurate",
            "body": entry.body,
            "privacy": "public",
        }
        form = LoreEntryEditForm(data=data, instance=entry)
        self.assertFalse(form.is_valid())
        self.assertIn("open", str(form.non_field_errors()))


class TestLayerAPI(EvenniaTest):
    def _request(self, staff=False, character=None):
        request = MagicMock()
        request.user.is_authenticated = True
        request.user.locks.check_lockstring.return_value = staff
        request.user.get_all_puppets.return_value = [character] if character else []
        request.user.characters.all.return_value = [character] if character else []
        request.user.account = request.user
        return request

    def test_ooc_layer_follows_the_body(self):
        from evennia_lore.api.serializers import LoreEntrySerializer

        entry = _entry(
            author=self.char1,
            kind="rumor",
            accuracy="inaccurate",
            ooc_notes="False.",
            privacy=LoreEntry.Privacy.RESTRICTED,
        )
        data = LoreEntrySerializer(
            entry, context={"request": self._request(character=self.char2)}
        ).data
        self.assertEqual(data["kind"], "rumor")
        self.assertIsNone(data["accuracy"])
        self.assertIsNone(data["ooc_notes"])
        _hold(entry, self.char2)
        data = LoreEntrySerializer(
            entry, context={"request": self._request(character=self.char2)}
        ).data
        self.assertEqual((data["accuracy"], data["ooc_notes"]), ("inaccurate", "False."))
        self.assertNotIn("sealed_notes", data)

    def test_a_decline_reads_as_none_to_others(self):
        from evennia_lore.api.serializers import LoreEntrySerializer

        entry = _entry(author=self.char2)
        entry.decline(declined_by=self.char1, note="x")
        other = LoreEntrySerializer(entry, context={"request": self._request(character=self.char1)})
        self.assertEqual(other.data["affirmation"], "none")
        author = LoreEntrySerializer(
            entry, context={"request": self._request(character=self.char2)}
        )
        self.assertEqual(author.data["affirmation"], "declined")
        staff = LoreEntrySerializer(entry, context={"request": self._request(staff=True)})
        self.assertEqual(staff.data["affirmation"], "declined")

    def test_only_staff_can_filter_for_declines(self):
        from evennia_lore.api.filters import LoreEntryFilter

        entry = _entry(author=self.char2)
        entry.decline(declined_by=self.char1, note="x")
        qs = LoreEntry.objects.all()
        player = LoreEntryFilter({"affirmation": "declined"}, qs, request=self._request()).qs
        self.assertFalse(player.exists())
        staff = LoreEntryFilter({"affirmation": "declined"}, qs, request=self._request(staff=True))
        self.assertEqual(list(staff.qs), [entry])

    def test_none_filter_does_not_identify_other_authors_declines(self):
        from evennia_lore.api.filters import LoreEntryFilter

        declined = _entry("Other author's decline", author=self.char1)
        declined.decline(declined_by=self.char1, note="Private.")
        own_decline = _entry("Own decline", author=self.char2)
        own_decline.decline(declined_by=self.char1, note="Private too.")
        plain = _entry("No request", author=self.char1)
        qs = LoreEntry.objects.all()
        player = LoreEntryFilter(
            {"affirmation": "none"}, qs, request=self._request(character=self.char2)
        )
        self.assertCountEqual(player.qs, [declined, plain])
        staff = LoreEntryFilter({"affirmation": "none"}, qs, request=self._request(staff=True))
        self.assertEqual(list(staff.qs), [plain])


@unittest.skipUnless(apps.is_installed("evennia_guides"), "evennia-guides not installed")
class TestLoreGuidePages(EvenniaTest):
    def test_shipped_pages_parse(self):
        from evennia_guides.pages import parse_page

        folder = Path(__file__).resolve().parent / "guides"
        pages = {
            page.key: page
            for page in (
                parse_page(path.read_text(encoding="utf-8"), source=str(path))
                for path in sorted(folder.glob("*.md"))
            )
        }
        self.assertEqual(set(pages), {"lore", "ic-may-mislead"})
        self.assertEqual(pages["ic-may-mislead"].kind, "principle")
        self.assertIn("ic-may-mislead", pages["lore"].principles)


class TestAnonymousDetail(LoreWebRenderTestCase):
    def test_anonymous_visitors_get_no_affirmation_actions(self):
        entry = _entry(author=self.char2)
        html = self._render(LoreDetailView, pk=entry.pk)
        self.assertNotIn("Request affirmation", html)
        self.assertNotIn("Affirm as it stands", html)
