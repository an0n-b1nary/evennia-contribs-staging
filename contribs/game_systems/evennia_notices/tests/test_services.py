# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Behavioral contracts for retries, privacy, ownership and source decisions."""

from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import override_settings
from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest

from evennia_links.ignoring import ignore_mode_requested
from evennia_links.notices import (
    ActorRef,
    Evaluation,
    NoticeContext,
    NoticeEvent,
    RenderedNotice,
    notify,
    transfer,
)
from evennia_notices.models import DeliveryReceipt, Notice
from evennia_notices.models import NoticeEvent as Stored
from evennia_notices.services import maintain, mutate, project, route, set_preference, summarize


class Source:
    """Primitive state source with explicit contextual and temporary deferrals."""

    label = "Test source"

    def evaluate(self, events, context):
        result = {}
        for event in events:
            status = event.payload.get("status", "visible")
            if (event.payload.get("requires_character") and context.character is None) or (
                event.payload.get("requires_account") and context.account is None
            ):
                result[event.event_id] = Evaluation("defer", reason="context")
            elif (
                event.payload.get("only_character")
                and getattr(context.character, "pk", None) != event.payload["only_character"]
            ):
                result[event.event_id] = Evaluation("hidden")
            else:
                result[event.event_id] = Evaluation(
                    status,
                    bool(event.action_kind and event.payload.get("pending", True)),
                    "temporary" if status == "defer" else None,
                )
        return result

    def render(self, events, context):
        return RenderedNotice("; ".join(e.payload.get("text", e.event_id) for e in events))


SOURCES = {
    "test": "evennia_notices.tests.test_services.Source",
    "other": "evennia_notices.tests.test_services.Source",
}


@override_settings(LINKS_NOTICE_SOURCES=SOURCES)
class ServicesTests(EvenniaTest):
    """Receipts and current evaluations distinguish real delivery from replay."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account.characters.add(self.char2)
        self.context = NoticeContext(self.account, self.char1)
        self.now = timezone.now()

    def event(self, key="one", **kwargs):
        return NoticeEvent(key, self.now, **kwargs)

    def emit(self, event=None, recipient=None, **kwargs):
        return route(
            recipient or self.account,
            source="test",
            event=event or self.event(),
            context=self.context,
            **kwargs,
        )

    def test_duplicate_after_disabled_and_removed_source(self):
        event = self.event()
        self.assertEqual(self.emit(event).status, "retained")
        with override_settings(NOTICES_ENABLED=False, LINKS_NOTICE_SOURCES={}):
            self.assertEqual(self.emit(event).status, "duplicate")
        self.assertEqual(Stored.objects.count(), 1)

    def test_changed_fingerprint_rejected(self):
        self.emit()
        with self.assertRaises(ValueError):
            self.emit(self.event(payload={"text": "different"}))

    def test_rollback_source_ack_and_receipt_are_atomic(self):
        from django.db import transaction

        with self.assertRaises(RuntimeError), transaction.atomic():
            self.emit()
            raise RuntimeError("Source acknowledgement rollback")
        self.assertFalse(DeliveryReceipt.objects.exists())
        self.assertFalse(Stored.objects.exists())

    def test_off_routine_suppressed_but_sought_decision_retained(self):
        set_preference(self.context, "test", "off")
        self.assertEqual(self.emit().status, "suppressed")
        self.assertEqual(
            self.emit(self.event("offer", action_kind="waitlist_offer")).status, "retained"
        )
        self.assertEqual(len(project(self.context, "pending")), 1)

    def test_read_does_not_resolve_or_clear_decision(self):
        self.emit(self.event(action_kind="lottery_selection"))
        token = Notice.objects.get().public_ref
        mutate(self.context, token, "read")
        self.assertEqual(len(project(self.context, "pending")), 1)
        with self.assertRaises(ValueError):
            mutate(self.context, token, "clear")
        self.assertIsNone(Stored.objects.get().cleared_at)

    def test_replacement_retains_receipt_and_unread_history_clock(self):
        self.emit(self.event(replacement_key="slot"))
        old = Stored.objects.get()
        self.emit(self.event("two", replacement_key="slot"))
        old.refresh_from_db()
        self.assertIsNone(old.read_at)
        self.assertIsNotNone(old.inactive_at)
        self.assertEqual(old.inactive_reason, "replaced")
        self.assertEqual([p.text for p in project(self.context)], ["two"])
        self.assertEqual(self.emit(self.event(replacement_key="slot")).status, "duplicate")

    def test_outstanding_action_blocks_replacement_without_receipt(self):
        self.emit(self.event(replacement_key="slot", action_kind="waitlist_offer"))
        self.assertEqual(self.emit(self.event("two", replacement_key="slot")).status, "retry")
        self.assertEqual(DeliveryReceipt.objects.count(), 1)

    def test_ingestion_context_defer_retains_but_provider_failure_retries(self):
        self.assertEqual(
            route(
                self.account, source="test", event=self.event(payload={"requires_character": True})
            ).status,
            "retained",
        )
        self.assertEqual(project(NoticeContext(self.account)), [])
        self.assertEqual(len(project(self.context)), 1)
        self.assertEqual(
            self.emit(self.event("temporary", payload={"status": "defer"})).status, "retry"
        )
        self.assertEqual(DeliveryReceipt.objects.count(), 1)

    def test_account_and_character_same_event_id_batch_isolation(self):
        self.emit(self.event(payload={"text": "account", "status": "visible"}))
        self.emit(
            self.event(payload={"text": "character", "status": "hidden"}), recipient=self.char1
        )
        self.assertEqual([p.text for p in project(self.context)], ["account"])
        self.assertEqual(DeliveryReceipt.objects.count(), 2)

    def test_no_other_character_or_staff_scope_expansion(self):
        self.emit(recipient=self.char1)
        self.assertEqual(project(NoticeContext(self.account, self.char2)), [])
        self.assertEqual(project(NoticeContext(self.account)), [])
        with self.assertRaises(ValueError):
            mutate(NoticeContext(self.account, self.char2), Notice.objects.get().public_ref, "read")

    def test_transfer_alias_preserves_one_event(self):
        event = self.event()
        result = transfer(
            self.account, source="test", event=event, transfer_id="legacy-one", context=self.context
        )
        self.assertEqual(result.status, "retained")
        self.assertEqual(self.emit(event).status, "duplicate")
        self.assertEqual(
            transfer(
                self.account,
                source="test",
                event=self.event("two"),
                transfer_id="legacy-one",
                context=self.context,
            ).status,
            "retry",
        )

    @override_settings(NOTICES_ROUTINE_LIMIT=2)
    def test_compaction_preserves_individual_read_state_and_provenance(self):
        for index in range(4):
            self.emit(self.event(str(index)))
        self.assertLessEqual(Notice.objects.count(), 2)
        self.assertEqual(Stored.objects.count(), 4)
        self.assertEqual(DeliveryReceipt.objects.count(), 4)
        self.assertEqual(sum(len(p.events) for p in project(self.context)), 4)

    @override_settings(NOTICES_ROUTINE_LIMIT=2)
    def test_unregistered_retained_source_counts_toward_cap_and_restore_is_safe(self):
        self.emit()
        route(self.account, source="other", event=self.event(), context=self.context)
        with override_settings(
            LINKS_NOTICE_SOURCES={"third": SOURCES["test"], "other": SOURCES["test"]}
        ):
            self.assertEqual(
                route(
                    self.account, source="third", event=self.event(), context=self.context
                ).status,
                "retry",
            )
            self.assertEqual([p.label for p in project(self.context)], ["Test source"])
        self.assertEqual(len(project(self.context)), 2)
        self.assertEqual(DeliveryReceipt.objects.count(), 2)

    def test_missing_module_does_not_block_healthy_source(self):
        self.emit()
        with override_settings(
            LINKS_NOTICE_SOURCES={**SOURCES, "missing": "package_does_not_exist.Source"}
        ):
            self.assertEqual(len(project(self.context)), 1)

    def test_retention_boundary_preserves_receipts_and_unread(self):
        self.emit()
        token = Notice.objects.get().public_ref
        mutate(self.context, token, "read")
        Stored.objects.update(read_at=self.now - timedelta(days=29))
        maintain(self.now)
        self.assertEqual(Stored.objects.count(), 1)
        Stored.objects.update(read_at=self.now - timedelta(days=31))
        maintain(self.now)
        self.assertEqual(Stored.objects.count(), 0)
        self.assertEqual(DeliveryReceipt.objects.count(), 1)
        self.assertEqual(self.emit().status, "duplicate")

    def test_retired_unread_history_uses_inactive_clock_without_acknowledgement(self):
        self.emit(self.event(replacement_key="slot"))
        self.emit(self.event("two", replacement_key="slot"))
        Stored.objects.filter(event_id="one").update(inactive_at=self.now - timedelta(days=31))
        maintain(self.now)
        self.assertEqual(list(Stored.objects.values_list("event_id", flat=True)), ["two"])
        self.assertEqual(DeliveryReceipt.objects.count(), 2)

    def test_hidden_or_invalid_payload_is_removed_but_receipt_survives(self):
        self.emit()
        with patch.object(Source, "evaluate", return_value={"one": Evaluation("invalid")}):
            maintain(self.now)
        self.assertFalse(Stored.objects.exists())
        self.assertTrue(DeliveryReceipt.objects.exists())

    def test_summary_dedup_never_renders_and_is_per_session(self):
        self.emit()
        session = Mock()
        session.get_account.return_value = self.account
        session.get_puppet.return_value = self.char1
        session._notice_summaries = {}
        context = NoticeContext(self.account, self.char1, session)
        with patch.object(Source, "render", side_effect=AssertionError("No rendering for counts")):
            self.assertEqual(summarize(context), (1, 0))
            self.assertEqual(summarize(context), (0, 0))
        session.msg.assert_called_once()

    def test_immediate_failure_does_not_fall_back_or_lose_receipt(self):
        set_preference(self.context, "test", "immediate")
        fallback = Mock()
        session = Mock()
        session.get_account.return_value = self.account
        session.get_puppet.return_value = self.char1
        session.msg.side_effect = RuntimeError("socket unavailable")
        context = NoticeContext(self.account, self.char1, session)
        with (
            self.captureOnCommitCallbacks(execute=True),
            patch("evennia_notices.services.connected_contexts", return_value=[context]),
        ):
            result = notify(
                self.account,
                source="test",
                event=self.event(),
                fallback=fallback,
                context=self.context,
            )
            self.assertEqual(result.status, "retained")
        fallback.assert_not_called()
        self.assertIsNotNone(Stored.objects.get().hint_attempted_at)

    def test_offline_character_never_borrows_any_owner_context(self):
        result = route(
            self.char1, source="test", event=self.event(payload={"requires_account": True})
        )
        self.assertEqual(result.status, "retained")
        self.assertEqual(len(project(self.context)), 1)
        with patch.object(Source, "evaluate", wraps=Source().evaluate) as evaluated:
            maintain(self.now)
        self.assertIsNone(evaluated.call_args.args[1].account)
        self.assertTrue(Stored.objects.exists())

    def test_ignore_provider_failure_retries_without_receipt(self):
        def broken(**kwargs):
            raise RuntimeError("unavailable")

        ignore_mode_requested.connect(broken, weak=False)
        try:
            result = self.emit(self.event(actors=(ActorRef("character", self.char2.pk),)))
            self.assertEqual(result.status, "retry")
            self.assertFalse(DeliveryReceipt.objects.exists())
        finally:
            ignore_mode_requested.disconnect(broken)

    def test_clear_and_read_are_idempotent_and_preserve_first_clock(self):
        self.emit()
        token = Notice.objects.get().public_ref
        mutate(self.context, token, "read")
        first = Stored.objects.get().read_at
        mutate(self.context, token, "read")
        self.assertEqual(Stored.objects.get().read_at, first)
        mutate(self.context, token, "clear")
        first_clear = Stored.objects.get().cleared_at
        mutate(self.context, token, "clear")
        self.assertEqual(Stored.objects.get().cleared_at, first_clear)

    def test_actor_policy_queries_are_bounded_after_compaction(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with override_settings(NOTICES_ROUTINE_LIMIT=2):
            for index in range(10):
                self.emit(self.event(str(index), actors=(ActorRef("character", self.char2.pk),)))
        with CaptureQueriesContext(connection) as queries:
            project(self.context, render=False)
        # One actor bulk lookup per owner/source batch, never per constituent.
        actor_queries = [
            q for q in queries if '"objects_objectdb"' in q["sql"] and " IN " in q["sql"]
        ]
        self.assertLessEqual(len(actor_queries), 2)

    def test_unignore_cannot_resurrect_previously_hidden_retained_activity(self):
        from evennia_links.ignoring import notify_ignore_policy_changing

        self.emit(self.event(actors=(ActorRef("character", self.char2.pk),)))

        def hidden(**kwargs):
            return "hide"

        ignore_mode_requested.connect(hidden, weak=False)
        try:
            self.assertEqual(project(self.context), [])
            notify_ignore_policy_changing(self.account)
        finally:
            ignore_mode_requested.disconnect(hidden)
        self.assertEqual(project(self.context), [])
        self.assertFalse(Stored.objects.exists())
        self.assertTrue(DeliveryReceipt.objects.exists())

    def test_atomic_source_transfer_does_not_acknowledge_retry(self):
        from django.db import transaction
        from evennia.server.models import ServerConfig

        event = self.event(payload={"status": "defer"})
        ServerConfig.objects.conf("test_pending_source", {"routed": False, "history": "preserved"})
        with transaction.atomic():
            source_row = ServerConfig.objects.select_for_update().get(db_key="test_pending_source")
            result = transfer(
                self.account,
                source="test",
                event=event,
                transfer_id="pending-source",
                context=self.context,
            )
            if result.status in {"retained", "duplicate", "suppressed"}:
                source_row.value = {"routed": True, "history": "preserved"}
        self.assertEqual(result.status, "retry")
        self.assertEqual(ServerConfig.objects.conf("test_pending_source")["routed"], False)
        self.assertFalse(DeliveryReceipt.objects.exists())
