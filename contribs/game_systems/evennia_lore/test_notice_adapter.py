# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Lore decision identity, privacy and durable routing behavior."""

from unittest.mock import Mock, patch

from django.db import transaction
from django.test import override_settings
from evennia.server.sessionhandler import SESSIONS
from evennia.utils.test_resources import EvenniaTest

from evennia_links.notices import NoticeContext
from evennia_lore import notices
from evennia_lore.integrations import notices as lore_integration
from evennia_lore.models import LoreEntry, LoreNotice


class LoreNoticeIdentityTests(EvenniaTest):
    """Historical decisions are distinct, while retrying a decision is idempotent."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.entry = LoreEntry.create_entry("Decision", author=self.char2, body="Content")

    def test_repeat_and_cycle_keep_original_private_note(self):
        self.entry.decline(declined_by=self.char1, note="Original private reason")
        self.entry.decline(declined_by=self.char1, note="Original private reason")
        self.assertEqual(LoreNotice.objects.count(), 1)
        self.entry.affirm(affirmed_by=self.char1)
        self.entry.decline(declined_by=self.char1, note="Original private reason")
        self.assertEqual(LoreNotice.objects.count(), 3)
        first = LoreNotice.objects.order_by("pk").first()
        self.assertEqual(first.envelope["payload"]["note"], "Original private reason")
        self.assertEqual(first.kind, "declined")

    def test_stale_decision_refreshes_author(self):
        stale = LoreEntry.objects.get(pk=self.entry.pk)
        self.entry.author = self.char1
        self.entry.save(update_fields=["author"])
        stale.affirm(affirmed_by=self.char2)
        self.assertEqual(LoreNotice.objects.get().character_id, self.char1.pk)

    def test_seed_suppression_cannot_be_replayed(self):
        self.entry.affirm(notify=False)
        self.entry.affirm()
        self.assertFalse(LoreNotice.objects.exists())

    def test_legacy_unknown_is_preserved(self):
        row = LoreNotice.objects.create(character=self.char2, entry=self.entry, message="private")
        with patch.object(self.char2, "msg") as msg:
            self.assertEqual(notices.deliver_pending(self.char2), 0)
        row.refresh_from_db()
        self.assertEqual(row.route_state, "pending")
        msg.assert_not_called()

    @override_settings(
        LINKS_NOTICE_SOURCES={"lore": "evennia_lore.integrations.notices.LoreNoticeSource"}
    )
    def test_historical_decline_is_author_bound(self):
        from evennia_links.notices import StoredEvent
        from evennia_lore.integrations.notices import LoreNoticeSource, event_for

        self.entry.decline(declined_by=self.char1, note="Private")
        row = LoreNotice.objects.get()
        event = event_for(row)
        stored = StoredEvent(
            **event.__dict__, recipient_kind="character", recipient_id=self.char2.pk
        )
        source = LoreNoticeSource()
        self.assertEqual(
            source.evaluate([stored], NoticeContext(self.account2, self.char2))[
                event.event_id
            ].status,
            "visible",
        )
        self.entry.author = self.char1
        self.entry.save(update_fields=["author"])
        self.assertEqual(
            source.evaluate([stored], NoticeContext(self.account2, self.char2))[
                event.event_id
            ].status,
            "invalid",
        )


@override_settings(
    LINKS_NOTICE_SOURCES={"lore": "evennia_lore.integrations.notices.LoreNoticeSource"}
)
class LoreRoutingTests(EvenniaTest):
    """Real Inbox seams and source receipts preserve one delivery path."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.entry = LoreEntry.create_entry("Routing", author=self.char2, body="Content")
        self.context = NoticeContext(self.account2, self.char2)

    def _decision(self):
        self.entry.decline(declined_by=self.char1, note="Historical reason")
        return LoreNotice.objects.latest("pk")

    def test_forged_envelope_and_wrong_alt_never_visible(self):
        from dataclasses import replace

        from evennia_links.notices import StoredEvent
        from evennia_lore.integrations.notices import LoreNoticeSource, event_for

        row = self._decision()
        event = event_for(row)
        stored = StoredEvent(
            **event.__dict__, recipient_kind="character", recipient_id=self.char2.pk
        )
        forged = replace(stored, payload={**stored.payload, "note": "forged"})
        source = LoreNoticeSource()
        self.assertEqual(source.evaluate([forged], self.context)[event.event_id].status, "invalid")
        self.assertEqual(
            source.evaluate([stored], NoticeContext(self.account, self.char1))[
                event.event_id
            ].status,
            "defer",
        )

    def test_known_system_actor_is_not_legacy_unknown(self):
        self.entry.affirm()
        row = LoreNotice.objects.get()
        self.assertTrue(row.provenance_known)
        self.assertEqual(row.envelope["actors"], [])

    def test_stale_unseal_does_not_publish_twice(self):
        from evennia_lore.layers import LoreLayerError
        from evennia_lore.models import LoreAcquisition

        self.entry.kind = "rumor"
        self.entry.accuracy = "open"
        self.entry.save(update_fields=["kind", "accuracy"])
        self.entry.seal("Private truth")
        LoreAcquisition.objects.create(entry=self.entry, character=self.char2, source="share")
        stale = LoreEntry.objects.get(pk=self.entry.pk)
        self.entry.unseal("accurate", unsealed_by=self.char1)
        with self.assertRaises(LoreLayerError):
            stale.unseal("accurate", unsealed_by=self.char1)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.ooc_notes.count("Private truth"), 1)
        self.assertEqual(LoreNotice.objects.count(), 1)

    def test_restricted_author_sees_own_decision_without_acquisition(self):
        from evennia_links.notices import StoredEvent
        from evennia_lore.integrations.notices import LoreNoticeSource, event_for

        self.entry.privacy = LoreEntry.Privacy.RESTRICTED
        self.entry.save(update_fields=["privacy"])
        row = self._decision()
        event = StoredEvent(
            **event_for(row).__dict__, recipient_kind="character", recipient_id=self.char2.pk
        )
        status = LoreNoticeSource().evaluate([event], self.context)[event.event_id].status
        self.assertEqual(status, "visible")

    def test_failing_row_does_not_abort_puppet_page(self):
        from evennia_lore.models import LoreNoticeCursor

        first = self._decision()
        self.entry.affirm(affirmed_by=self.char1)
        second = LoreNotice.objects.latest("pk")
        LoreNotice.objects.filter(pk__in=[first.pk, second.pk]).update(route_state="pending")
        with patch.object(
            notices, "route_notice", side_effect=[RuntimeError("poison"), "pending"]
        ) as route:
            counts = notices.transfer_pending(self.char2, context=self.context, limit=2)
        self.assertEqual(route.call_count, 2)
        self.assertEqual((counts["retry"], counts["pending"]), (1, 1))
        cursor = LoreNoticeCursor.objects.get(scope=f"character-{self.char2.pk}")
        self.assertEqual(cursor.last_pk, second.pk)

    def test_held_legacy_does_not_starve_new_work(self):
        LoreNotice.objects.create(character=self.char2, message="Unknown provenance")
        row = self._decision()
        first = notices.transfer_pending(self.char2, limit=1)
        self.assertEqual(first["held"], 1)
        second = notices.transfer_pending(self.char2, limit=1)
        self.assertEqual(second["held"], 0)
        self.assertIn(notices.route_notice(row.pk), {"inbox", "pending"})

    def test_attempting_or_terminal_events_never_replay(self):
        row = self._decision()
        for state in ("attempting", "uncertain", "fallback", "inbox", "suppressed"):
            row.route_state = state
            row.save(update_fields=["route_state"])
            with patch.object(notices, "route_event") as route:
                self.assertEqual(notices.route_notice(row.pk), state)
                route.assert_not_called()

    def test_invalid_page_limits_are_refused(self):
        for value in (0, -1, 1001, True):
            with self.assertRaises(ValueError):
                notices.transfer_pending(self.char2, limit=value)

    def test_guest_offline_retains_nothing(self):
        self.char2.tags.add("character", category="guest")
        self.entry.affirm()
        from evennia_lore.models import LoreNoticeCursor

        self.assertFalse(LoreNotice.objects.exists())
        notices.transfer_pending(self.char2)
        self.assertFalse(
            LoreNoticeCursor.objects.filter(scope=f"character-{self.char2.pk}").exists()
        )

    def test_guest_live_owned_session_and_retry_marker(self):
        from unittest.mock import Mock

        session = Mock()
        session._lore_notice_attempts = set()
        session.get_account.return_value = self.account2
        session.get_puppet.return_value = self.char2
        self.char2.tags.add("character", category="guest")
        with patch.object(notices, "_sessions", return_value=[session]):
            with self.captureOnCommitCallbacks(execute=True):
                self.entry.affirm()
            with self.captureOnCommitCallbacks(execute=True):
                self.entry.affirm()
        self.assertEqual(session.msg.call_count, 1)
        self.assertFalse(LoreNotice.objects.exists())

    def test_guest_changed_puppet_before_send_retains_nothing(self):
        from unittest.mock import Mock

        session = Mock()
        session._lore_notice_attempts = set()
        session.get_account.return_value = self.account2
        session.get_puppet.return_value = self.char1
        self.char2.tags.add("character", category="guest")
        with (
            patch.object(notices, "_sessions", return_value=[session]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.entry.affirm()
        session.msg.assert_not_called()
        self.assertFalse(LoreNotice.objects.exists())

    def test_source_mutation_and_outbox_roll_back_together(self):
        with (
            patch.object(LoreNotice.objects, "get_or_create", side_effect=RuntimeError("outbox")),
            self.assertRaises(RuntimeError),
        ):
            self.entry.affirm()
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.affirmation, "none")

    def test_inbox_read_clear_never_changes_lore(self):
        from django.apps import apps

        if not apps.is_installed("evennia_notices"):
            self.skipTest("Inbox physically absent")
        from evennia_notices.models import DeliveryReceipt
        from evennia_notices.services import mutate, project

        row = self._decision()
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        receipt = DeliveryReceipt.objects.get(source="lore")
        reference = receipt.stored_event.notice.public_ref
        before = (
            self.entry.affirmation,
            self.entry.affirmation_note,
            self.entry.acquisitions.count(),
        )
        mutate(self.context, reference, "read")
        mutate(self.context, reference, "clear")
        self.entry.refresh_from_db()
        self.assertEqual(
            before,
            (self.entry.affirmation, self.entry.affirmation_note, self.entry.acquisitions.count()),
        )
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        self.assertFalse(project(self.context))

    def test_partial_inbox_ack_failure_rolls_back_receipt(self):
        from django.apps import apps

        if not apps.is_installed("evennia_notices"):
            self.skipTest("Inbox physically absent")
        from evennia_notices import services
        from evennia_notices.models import DeliveryReceipt

        services.set_preference(self.context, "lore", "immediate")

        row = self._decision()
        with (
            patch.object(notices, "_ack", side_effect=RuntimeError("ack fault")),
            patch.object(services, "_immediate") as hint,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.assertEqual(notices.route_notice(row.pk, fresh=True), "retry")
        hint.assert_not_called()
        self.assertFalse(DeliveryReceipt.objects.filter(source="lore").exists())
        row.refresh_from_db()
        self.assertEqual(row.route_state, "pending")
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        self.assertEqual(DeliveryReceipt.objects.filter(source="lore").count(), 1)

    def test_actor_policy_and_archival_remove_counts_and_text(self):
        from django.apps import apps

        if not apps.is_installed("evennia_notices"):
            self.skipTest("Inbox physically absent")
        from evennia_notices.services import project, summarize

        row = self._decision()
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        with patch("evennia_links.ignoring.notice_ignore_status", return_value="suppress"):
            self.assertFalse(project(self.context))
            self.assertEqual(summarize(self.context), (0, 0))
        self.entry.archive()
        self.assertFalse(project(self.context))

    @override_settings(LINKS_NOTICE_SOURCES={})
    def test_unconfigured_source_uses_validated_fallback(self):
        from unittest.mock import Mock

        row = self._decision()
        session = Mock()
        session._lore_notice_attempts = set()
        session.get_account.return_value = self.account2
        session.get_puppet.return_value = self.char2
        context = NoticeContext(self.account2, self.char2, session)
        with (
            patch.object(notices, "connected_contexts", return_value=[context]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            notices.route_notice(row.pk)
        self.assertEqual(session.msg.call_count, 1)
        row.refresh_from_db()
        self.assertEqual(row.route_state, "fallback")
        self.assertEqual(notices.route_notice(row.pk), "fallback")

    def test_real_social_policy_suppresses_existing_history(self):
        from django.apps import apps

        if not apps.is_installed("evennia_social") or not apps.is_installed("evennia_notices"):
            self.skipTest("Social and Inbox partners required")
        from evennia_notices.services import project, summarize
        from evennia_social import ignore

        self.account.is_superuser = False
        self.account.permissions.clear()
        self.account.save(update_fields=["is_superuser"])
        self.account2.is_superuser = False
        self.account2.permissions.clear()
        self.account2.save(update_fields=["is_superuser"])
        self.char1.permissions.clear()
        self.char2.permissions.clear()
        row = self._decision()
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        self.assertTrue(project(self.context))
        for level in (ignore.HIDDEN, ignore.FULL, ignore.POSTS):
            ignore.set_entry(self.char2, self.char1, level)
            self.assertFalse(project(self.context))
            self.assertEqual(summarize(self.context), (0, 0))
            ignore.clear(self.account2)

    def test_socket_failure_keeps_uncertain_claim(self):
        from unittest.mock import Mock

        row = self._decision()
        session = Mock()
        session.get_account.return_value = self.account2
        session.get_puppet.return_value = self.char2
        session.msg.side_effect = RuntimeError("socket uncertainty")
        context = NoticeContext(self.account2, self.char2, session)
        with (
            override_settings(LINKS_NOTICE_SOURCES={}),
            patch.object(notices, "connected_contexts", return_value=[context]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            notices.route_notice(row.pk)
        row.refresh_from_db()
        self.assertEqual(row.route_state, "uncertain")
        self.assertIsNone(row.acknowledged_at)
        self.assertEqual(notices.route_notice(row.pk), "uncertain")
        self.assertEqual(session.msg.call_count, 1)

    def test_pending_transfer_never_schedules_immediate_hint(self):
        from django.apps import apps

        if not apps.is_installed("evennia_notices"):
            self.skipTest("Inbox physically absent")
        from evennia_notices import services

        services.set_preference(self.context, "lore", "immediate")
        row = self._decision()
        with (
            patch.object(services, "_immediate") as hint,
            self.captureOnCommitCallbacks(execute=True),
        ):
            notices.route_notice(row.pk)
        hint.assert_not_called()

    def test_account_actor_keeps_account_provenance(self):
        self.entry.decline(declined_by=self.account, note="Account-origin decision")
        self.assertEqual(
            LoreNotice.objects.get().envelope["actors"],
            [{"kind": "account", "id": self.account.pk}],
        )

    def test_invalid_actor_rejected_before_mutating_source(self):
        with self.assertRaises(ValueError):
            self.entry.affirm(affirmed_by=object())
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.affirmation, "none")
        self.assertFalse(LoreNotice.objects.exists())

    @override_settings(NOTICES_ROUTINE_LIMIT=1)
    def test_compaction_filters_ignored_constituents_before_rendering(self):
        from django.apps import apps

        if not apps.is_installed("evennia_notices"):
            self.skipTest("Inbox physically absent")
        from evennia_notices.services import project, summarize

        first = self._decision()
        notices.route_notice(first.pk)
        self.entry.affirm()
        second = LoreNotice.objects.latest("pk")
        notices.route_notice(second.pk)
        self.assertEqual(len(project(self.context)), 1)
        with patch("evennia_links.ignoring.notice_ignore_status", return_value="suppress"):
            projected = project(self.context)
            self.assertEqual(len(projected), 1)
            self.assertIn("affirmed", projected[0].text)
            self.assertNotIn("Historical reason", projected[0].text)
            self.assertNotIn("2 Lore", projected[0].text)
            self.assertEqual(summarize(self.context), (1, 0))

    def test_forgetting_unsealed_lore_withdraws_only_alert(self):
        from django.apps import apps

        if not apps.is_installed("evennia_notices"):
            self.skipTest("Inbox physically absent")
        from evennia_lore.models import LoreAcquisition
        from evennia_notices.services import project, summarize

        self.entry.kind, self.entry.accuracy = "rumor", "open"
        self.entry.save(update_fields=["kind", "accuracy"])
        self.entry.seal("True explanation")
        acquisition = LoreAcquisition.objects.create(
            entry=self.entry, character=self.char2, source="share"
        )
        self.entry.unseal("accurate")
        row = LoreNotice.objects.get(kind="unsealed")
        notices.route_notice(row.pk)
        self.assertTrue(project(self.context))
        acquisition.delete()
        self.assertFalse(project(self.context))
        self.assertEqual(summarize(self.context), (0, 0))
        self.entry.refresh_from_db()
        self.assertIn("True explanation", self.entry.ooc_notes)

    def test_genuine_request_or_changed_note_is_a_new_decision(self):
        self.entry.decline(note="First")
        self.entry.request_affirmation(requested_by=self.char2)
        self.entry.decline(note="First")
        self.entry.decline(note="Changed")
        self.assertEqual(LoreNotice.objects.count(), 3)

    def test_guest_advisory_never_retains_source_or_inbox(self):
        from django.apps import apps

        if not apps.is_installed("evennia_plots"):
            self.skipTest("Plots physically absent")
        from evennia_lore.models import PlotLoreLink
        from evennia_plots.models import PlotThread

        self.char2.tags.add("character", category="guest")
        self.entry.kind, self.entry.accuracy = "rumor", "open"
        self.entry.save(update_fields=["kind", "accuracy"])
        self.entry.seal("Sealed explanation")
        thread = PlotThread.create_thread(name="Guest advisory", creator=self.char2)
        PlotLoreLink.objects.create(entry=self.entry, thread_id=thread.pk)
        with self.captureOnCommitCallbacks(execute=True):
            thread.conclude(concluded_by=self.char2)
        self.assertFalse(LoreNotice.objects.filter(character=self.char2).exists())

    def _deleted_actor_mixed_batch(self, actor):
        from django.apps import apps

        if not apps.is_installed("evennia_notices"):
            self.skipTest("Inbox physically absent")
        from evennia_links.notices import StoredEvent
        from evennia_lore.integrations.notices import LoreNoticeSource, event_for
        from evennia_notices.services import mutate, project, summarize

        self.entry.decline(declined_by=actor, note="Historical actor-private reason")
        broken = LoreNotice.objects.get(kind="declined")
        self.entry.affirm()
        for row in LoreNotice.objects.order_by("pk"):
            self.assertEqual(notices.route_notice(row.pk), "inbox")
        self.assertEqual(sum(len(item.events) for item in project(self.context)), 2)
        actor.delete()
        projected = project(self.context)
        self.assertEqual(len(projected), 1)
        self.assertEqual(len(projected[0].events), 1)
        self.assertIn("affirmed", projected[0].text)
        self.assertNotIn("Historical actor-private reason", projected[0].text)
        self.assertEqual(summarize(self.context), (1, 0))
        event = StoredEvent(
            **event_for(broken).__dict__, recipient_kind="character", recipient_id=self.char2.pk
        )
        outcome = LoreNoticeSource().evaluate([event], self.context)[event.event_id]
        self.assertEqual((outcome.status, outcome.reason), ("defer", "provenance"))
        mutate(self.context, projected[0].notice.public_ref, "read")
        self.assertEqual(summarize(self.context), (0, 0))

    def test_deleted_character_actor_does_not_poison_valid_peer(self):
        self._deleted_actor_mixed_batch(self.char1)

    def test_deleted_account_actor_does_not_poison_valid_peer(self):
        import secrets

        from evennia.utils.create import create_account

        actor = create_account("Deleted Lore actor fixture", None, secrets.token_urlsafe(32))
        self._deleted_actor_mixed_batch(actor)

    @override_settings(NOTICES_ROUTINE_LIMIT=1)
    def test_deleted_actor_does_not_poison_compacted_peer(self):
        self._deleted_actor_mixed_batch(self.char1)


@override_settings(LINKS_NOTICE_SOURCES={})
class LoreFallbackTests(EvenniaTest):
    """A durable claim distinguishes a skipped write from an unknown outcome."""

    def setUp(self):
        super().setUp()
        self.account2.characters.add(self.char2)
        self.entry = LoreEntry.create_entry("Fallback", author=self.char2, body="Content")
        self.sessions = []
        self.enterContext(patch.object(SESSIONS, "get_sessions", return_value=self.sessions))

    def _decision(self, guest=False, actor=None):
        self.sessions.clear()
        self.char2.tags.remove("character", category="guest")
        self.entry.request_affirmation(requested_by=self.char2)
        self.entry.decline(declined_by=actor, note="Historical reason")
        if guest:
            self.char2.tags.add("character", category="guest")
        return LoreNotice.objects.latest("pk")

    def _session(self):
        session = Mock()
        session._lore_notice_attempts = set()
        session.get_account.return_value = self.account2
        session.get_puppet.return_value = self.char2
        self.sessions.append(session)
        return session

    def _claim(self, row):
        self.assertEqual(notices.route_notice(row.pk), "attempting")
        self._assert_receipt(row, "attempting")

    def _assert_receipt(self, row, state):
        row.refresh_from_db()
        self.assertEqual(row.route_state, state)
        if state in {"fallback", "invalid"}:
            self.assertIsNotNone(row.acknowledged_at)
        else:
            self.assertIsNone(row.acknowledged_at)

    def _retry_once(self, row, session):
        session.msg.assert_not_called()
        self._assert_receipt(row, "pending")
        self.assertNotIn(row.event_key, session._lore_notice_attempts)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(notices.transfer_pending(self.char2)["attempting"], 1)
        session.msg.assert_called_once()
        self._assert_receipt(row, "fallback")
        self.assertEqual(notices.route_notice(row.pk), "fallback")
        self.assertEqual(notices.transfer_pending(self.char2)["fallback"], 0)
        session.msg.assert_called_once()

    def _fail_refresh_once(self):
        refresh = LoreNotice.refresh_from_db
        errors = [RuntimeError("read fault")]

        def fail_once(row, *args, **kwargs):
            if errors:
                raise errors.pop()
            return refresh(row, *args, **kwargs)

        return patch.object(LoreNotice, "refresh_from_db", autospec=True, side_effect=fail_once)

    def test_unstarted_fallback_retries_once(self):
        for guest in (False, True):
            with self.subTest(guest=guest):
                row = self._decision(guest)
                session = self._session()
                with self.captureOnCommitCallbacks(execute=True):
                    self._claim(row)
                    session.get_puppet.return_value = None
                    if guest:
                        self.sessions.clear()
                session.get_puppet.return_value = self.char2
                self.sessions[:] = [session]
                self._retry_once(row, session)
                self.sessions.clear()

    def test_prewrite_render_failure_retries_once(self):
        for guest in (False, True):
            for fault in ("render", "refresh"):
                with self.subTest(guest=guest, fault=fault):
                    row = self._decision(guest)
                    session = self._session()
                    if fault == "refresh":
                        fault_patch = self._fail_refresh_once()
                    else:
                        target, name = (
                            (lore_integration, "render_payload") if guest else (notices, "_render")
                        )
                        fault_patch = patch.object(target, name, side_effect=RuntimeError("render"))
                    with self.captureOnCommitCallbacks(execute=False) as callbacks:
                        self._claim(row)
                    self.assertEqual(len(callbacks), 1)
                    with fault_patch:
                        callbacks[0]()
                    self._retry_once(row, session)
                    self.sessions.clear()

    def test_empty_advisory_render_has_no_transport_attempt(self):
        from django.apps import apps

        if not apps.is_installed("evennia_plots"):
            self.skipTest("Plots physically absent")
        from evennia_lore.models import PlotLoreLink
        from evennia_plots.models import PlotThread

        self.entry.kind, self.entry.accuracy = "rumor", "open"
        self.entry.save(update_fields=["kind", "accuracy"])
        render = notices._render

        def clear_sealed():
            LoreEntry.objects.filter(pk=self.entry.pk).update(sealed_notes="")

        def render_after_unseal(row):
            clear_sealed()
            return render(row)

        for guest in (False, True):
            with self.subTest(guest=guest):
                self.entry.refresh_from_db()
                self.entry.seal("Sealed explanation")
                thread = PlotThread.create_thread(name="Advisory", creator=self.char2)
                PlotLoreLink.objects.create(entry=self.entry, thread_id=thread.pk)
                thread.conclude(concluded_by=self.char2)
                row = LoreNotice.objects.latest("pk")
                self.assertEqual(row.kind, "advisory")
                session = self._session()
                if guest:
                    self.char2.tags.add("character", category="guest")
                with (
                    patch.object(notices, "_render", side_effect=render_after_unseal),
                    self.captureOnCommitCallbacks(execute=True),
                ):
                    self._claim(row)
                    if guest:
                        clear_sealed()
                self._assert_receipt(row, "pending")
                session.msg.assert_not_called()
                self.char2.tags.remove("character", category="guest")
                self.assertEqual(notices.route_notice(row.pk), "invalid")
                self._assert_receipt(row, "invalid")
                self.sessions.clear()

    def test_failing_session_does_not_skip_eligible_peer(self):
        for guest, fault in ((False, "socket"), (True, "socket"), (True, "puppet getter")):
            with self.subTest(guest=guest, fault=fault):
                row = self._decision(guest)
                first, peer = self._session(), self._session()
                with self.captureOnCommitCallbacks(execute=True):
                    self._claim(row)
                    if fault == "socket":
                        first.msg.side_effect = RuntimeError("write fault")
                    else:
                        first.get_puppet.side_effect = RuntimeError("session fault")
                if fault == "socket":
                    first.msg.assert_called_once()
                else:
                    first.msg.assert_not_called()
                peer.msg.assert_called_once()
                self._assert_receipt(row, "fallback")
                self.assertEqual(notices.route_notice(row.pk), "fallback")
                peer.msg.assert_called_once()
                self.sessions.clear()

    def test_guest_socket_failure_is_not_replayed(self):
        row, session = self._decision(guest=True), self._session()
        session.msg.side_effect = RuntimeError("write fault")
        with self.captureOnCommitCallbacks(execute=True):
            self._claim(row)
        self._assert_receipt(row, "uncertain")
        self.assertIn(row.event_key, session._lore_notice_attempts)
        self.assertEqual(notices.route_notice(row.pk), "uncertain")
        session.msg.assert_called_once()

    def _fresh_guest_hint(self):
        return notices.notify(self.char2, "", entry=self.entry, kind="declined")

    def test_fresh_guest_prewrite_failure_leaves_hint_retryable(self):
        from evennia_lore.models import LoreNoticeCursor

        self.char2.tags.add("character", category="guest")
        cursors = LoreNoticeCursor.objects.order_by("pk").values_list("pk", "scope", "last_pk")
        existing_cursors = list(cursors)
        key = f"lore-{self.entry.pk}-{self.entry.notice_sequence}-declined-{self.char2.pk}"
        first, peer = self._session(), self._session()
        render = lore_integration.render_payload
        failures = [RuntimeError("render")]

        def fail_first_render(payload):
            if failures:
                raise failures.pop()
            return render(payload)

        with (
            patch.object(lore_integration, "render_payload", side_effect=fail_first_render),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self._fresh_guest_hint()
        first.msg.assert_not_called()
        self.assertNotIn(key, first._lore_notice_attempts)
        peer.msg.assert_called_once()
        self.assertIn(key, peer._lore_notice_attempts)
        for _ in range(2):
            with self.captureOnCommitCallbacks(execute=True):
                self._fresh_guest_hint()
        first.msg.assert_called_once()
        peer.msg.assert_called_once()
        self.assertIn(key, first._lore_notice_attempts)

        self.sessions[:] = [first]
        first.msg.reset_mock()
        first.msg.side_effect = RuntimeError("write fault")
        failing_key = f"lore-{self.entry.pk}-{self.entry.notice_sequence}-affirmed-{self.char2.pk}"
        for _ in range(2):
            with self.captureOnCommitCallbacks(execute=True):
                notices.notify(self.char2, "", entry=self.entry, kind="affirmed")
        first.msg.assert_called_once()
        self.assertIn(failing_key, first._lore_notice_attempts)
        self.assertFalse(LoreNotice.objects.exists())
        self.assertEqual(list(cursors.all()), existing_cursors)
        self.assertIsNone(self.char2.ndb.lore_transfer_position)

    def test_existing_guest_honors_prior_transient_attempt(self):
        render = lore_integration.render_payload

        def render_during_fresh_send(payload):
            # Simulate a fresh hint's commit in a second execution context.
            with (
                patch.object(lore_integration, "render_payload", render),
                patch.object(transaction, "on_commit", side_effect=lambda callback: callback()),
            ):
                self.assertTrue(self._fresh_guest_hint())
            return render(payload)

        for scenario in ("prior marker", "peer", "disconnect", "refresh fault", "interleaved"):
            with self.subTest(scenario=scenario):
                row, session = self._decision(guest=True), self._session()
                if scenario != "interleaved":
                    with self.captureOnCommitCallbacks(execute=True):
                        self._fresh_guest_hint()
                    self.assertIn(row.event_key, session._lore_notice_attempts)
                    session.msg.assert_called_once()
                if scenario == "peer":
                    peer = self._session()
                with self.captureOnCommitCallbacks(execute=False) as callbacks:
                    self._claim(row)
                self.assertEqual(len(callbacks), 1)
                if scenario == "disconnect":
                    session.get_puppet.return_value = None
                    self.sessions.clear()
                if scenario == "refresh fault":
                    with self._fail_refresh_once():
                        callbacks[0]()
                elif scenario == "interleaved":
                    with patch.object(
                        lore_integration, "render_payload", side_effect=render_during_fresh_send
                    ):
                        callbacks[0]()
                else:
                    callbacks[0]()
                session.msg.assert_called_once()
                if scenario == "peer":
                    peer.msg.assert_called_once()
                    self._assert_receipt(row, "fallback")
                else:
                    self._assert_receipt(row, "uncertain")
                self.sessions.clear()

    def test_guest_account_swap_during_render_cannot_disclose(self):
        self.account.characters.add(self.char2)
        render = lore_integration.render_payload

        def ignore_status(account, actor):
            return "suppress" if account == self.account else "allow"

        for durable in (True, False):
            with self.subTest(durable=durable):
                self.sessions.clear()
                row = self._decision(guest=True, actor=self.char1) if durable else None
                if not durable:
                    self.entry = LoreEntry.create_entry(
                        "Fresh fallback", author=self.char2, body="Content"
                    )
                session = self._session()
                key = f"lore-{self.entry.pk}-{self.entry.notice_sequence}-declined-{self.char2.pk}"

                def switch_account(payload, session=session):
                    session.get_account.return_value = self.account
                    return render(payload)

                def route(row):
                    if row is not None:
                        self._claim(row)
                    else:
                        notices.notify(
                            self.char2, "", entry=self.entry, kind="declined", actor=self.char1
                        )

                with patch(
                    "evennia_links.ignoring.notice_ignore_status", side_effect=ignore_status
                ):
                    with (
                        patch.object(
                            lore_integration, "render_payload", side_effect=switch_account
                        ),
                        self.captureOnCommitCallbacks(execute=True),
                    ):
                        route(row)
                    self.assertEqual(session.get_account(), self.account)
                    session.msg.assert_not_called()
                    self.assertNotIn(key, session._lore_notice_attempts)
                    session.get_account.return_value = self.account2
                    if durable:
                        self._retry_once(row, session)
                    else:
                        with self.captureOnCommitCallbacks(execute=True):
                            route(row)
                        session.msg.assert_called_once()
                        self.assertIn(key, session._lore_notice_attempts)

    def test_existing_guest_keeps_attempt_when_fresh_send_disconnects(self):
        render = lore_integration.render_payload

        def send_and_disconnect():
            with (
                patch.object(lore_integration, "render_payload", render),
                patch.object(transaction, "on_commit", side_effect=lambda callback: callback()),
            ):
                self.assertTrue(self._fresh_guest_hint())
            session.msg.assert_called_once()
            self.assertIn(row.event_key, session._lore_notice_attempts)
            session.get_puppet.return_value = None
            self.sessions.clear()

        def render_during_fresh_send(payload):
            send_and_disconnect()
            if scenario == "new candidate render fails":
                raise RuntimeError("durable render fault")
            return render(payload)

        for scenario in ("before callback", "during render", "new candidate render fails"):
            with self.subTest(scenario=scenario):
                row, session = self._decision(guest=True), self._session()
                with self.captureOnCommitCallbacks(execute=False) as callbacks:
                    self._claim(row)
                self.assertEqual(len(callbacks), 1)
                if scenario == "before callback":
                    send_and_disconnect()
                    callbacks[0]()
                else:
                    if scenario == "new candidate render fails":
                        self.sessions.clear()
                        session = self._session()
                    with patch.object(
                        lore_integration, "render_payload", side_effect=render_during_fresh_send
                    ):
                        callbacks[0]()
                session.msg.assert_called_once()
                replacement = self._session()
                with self.captureOnCommitCallbacks(execute=True):
                    self.assertEqual(notices.route_notice(row.pk), "uncertain")
                self._assert_receipt(row, "uncertain")
                replacement.msg.assert_not_called()

    def test_final_status_failure_does_not_abort_other_claims(self):
        first = self._decision()
        second, session = self._decision(), self._session()
        ack = notices._ack

        def fault_first_ack(row, state):
            if row.pk == first.pk:
                session.msg.assert_called_once()
                raise RuntimeError("status fault")
            ack(row, state)

        with (
            patch.object(notices, "_ack", side_effect=fault_first_ack),
            self.captureOnCommitCallbacks(execute=True),
            transaction.atomic(),
        ):
            self._claim(first)
            self._claim(second)
        self._assert_receipt(first, "attempting")
        self._assert_receipt(second, "fallback")
        self.assertEqual(notices.route_notice(first.pk), "attempting")
        self.assertEqual(session.msg.call_count, 2)
