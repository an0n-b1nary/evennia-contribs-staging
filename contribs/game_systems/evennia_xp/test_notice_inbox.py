# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Exercise the real Links and Inbox route, preferences, and projection."""

from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from evennia.utils import create

from .awards import record_xp
from .batch import Award, run_weekly_batch
from .models import CharacterXP, XPLog, XPNoticeReceipt
from .summary import SUMMARY_WEEK_ATTRIBUTE
from .test_notice_standalone import NoticeFixture

HAS_INBOX = apps.is_installed("evennia_notices")
REGISTRY = {"xp": "evennia_xp.integrations.notices.XPNoticeSource"}
State = XPNoticeReceipt.State


@skipUnless(HAS_INBOX, "Inbox physically absent")
@override_settings(LINKS_NOTICE_SOURCES=REGISTRY, NOTICES_ENABLED=True)
class InboxNoticeTests(NoticeFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        from evennia_links.notices import NoticeContext

        self.context = NoticeContext(self.account, self.character, self.sessions[0])
        connected = patch(
            "evennia.server.sessionhandler.SESSIONS.get_sessions", lambda: self.sessions
        )
        connected.start()
        self.addCleanup(connected.stop)

    def project(self, **kwargs):
        from evennia_notices.services import project

        return project(self.context, source="xp", **kwargs)

    def legacy(self, week):
        row = XPLog.objects.create(
            character_id=self.character.pk,
            source_type=XPLog.SourceType.LORE_AUTHORED,
            source_ref_id=XPLog.objects.count() + 999,
            week=week,
            amount=Decimal("0.50"),
        )
        CharacterXP.objects.update_or_create(
            character_id=self.character.pk,
            defaults={"last_payout_week": week},
        )
        return row

    def test_fresh_committed_week_routes_once_before_puppet(self):
        from evennia_notices.models import DeliveryReceipt

        with transaction.atomic():
            self.award()
            self.assertEqual(DeliveryReceipt.objects.count(), 0)
        [item] = self.project()
        self.assertIn("RP Session: +1.25", item.text)
        self.assertEqual(self.character.attributes.get(SUMMARY_WEEK_ATTRIBUTE), "2026-W09")
        self.assertFalse(self.show())
        self.assertIsNone(self.award())
        self.assertEqual(DeliveryReceipt.objects.filter(source="xp").count(), 1)
        self.sessions[0].msg.assert_not_called()

    @override_settings(
        XP_COLLECTORS=[("xp-test", "test.collector")],
        XP_ANTIGAMING_SWEEPS=[],
        XP_POST_BATCH_HOOKS=[],
    )
    def test_batch_commit_aggregates_all_awards_and_rollback_creates_no_receipt(self):
        awards = [
            Award(self.character.pk, Decimal("1.25"), XPLog.SourceType.RP_SESSION, 4, 1, ""),
            Award(self.character.pk, Decimal("0.50"), XPLog.SourceType.CUTSCENE, 5, 1, ""),
        ]
        with patch("evennia_xp.batch._resolve_dotted", return_value=lambda _: awards):
            with transaction.atomic():
                run_weekly_batch("2026-W08", dry_run=True)
                self.assertFalse(XPNoticeReceipt.objects.exists())
                self.assertFalse(run_weekly_batch("2026-W08").errors)
                self.assertEqual(self.project(), [])
                transaction.set_rollback(True)
            self.assertFalse(XPNoticeReceipt.objects.exists())
            self.assertFalse(XPLog.objects.exists())
            self.assertFalse(run_weekly_batch("2026-W08").errors)
            self.assertFalse(run_weekly_batch("2026-W08").errors)
        [item] = self.project()
        self.assertIn("1.75 XP total", item.text)
        self.assertEqual(XPLog.objects.count(), 2)

    def test_history_backfill_does_not_reopen_but_first_older_payment_routes(self):
        self.legacy("2025-W52")
        self.legacy("2026-W07")
        self.character.attributes.add(SUMMARY_WEEK_ATTRIBUTE, "2026-W07")
        self.award(1, "2025-W52")
        self.assertEqual(self.project(), [])
        self.assertFalse(self.show())
        self.award(2, "2025-W50")
        [item] = self.project()
        self.assertIn("2025-W50", item.text)
        self.assertEqual(self.character.attributes.get(SUMMARY_WEEK_ATTRIBUTE), "2025-W50")

    def test_first_new_award_preserves_unsummarized_legacy_pointer(self):
        self.legacy("2025-W52")
        self.character.attributes.add(SUMMARY_WEEK_ATTRIBUTE, "2026-01-05")
        self.award(1, "2026-W02")
        self.assertEqual(len(self.project()), 1)
        self.assertFalse(self.show())
        self.assertEqual(XPNoticeReceipt.objects.filter(state=State.TRANSFERRED).count(), 2)
        self.assertEqual(len(self.project()), 2)

    def test_same_week_credit_changes_only_totals_after_read_or_clear(self):
        from evennia_notices.models import DeliveryReceipt
        from evennia_notices.services import mutate

        self.award()
        [first] = self.project()
        mutate(self.context, first.notice.public_ref, "read")
        self.award(2)
        self.assertEqual(self.project(status="unread"), [])
        [read] = self.project(status="all")
        self.assertIn("2.50 XP total", read.text)
        mutate(self.context, first.notice.public_ref, "clear")
        self.award(3)
        self.show()
        self.assertEqual(self.project(status="unread"), [])
        [cleared] = self.project(status="history")
        self.assertIsNotNone(cleared.events[0].cleared_at)
        self.assertEqual(DeliveryReceipt.objects.filter(source="xp").count(), 1)
        self.assertEqual(CharacterXP.objects.get().current_balance, Decimal("3.75"))

    def test_summary_immediate_off_and_retry_keep_one_route(self):
        from evennia_notices.models import DeliveryReceipt
        from evennia_notices.services import set_preference

        set_preference(self.context, "xp", "immediate")
        self.award(1, "2026-W07")
        self.sessions[0].msg.assert_called_once()
        self.sessions[0].msg.reset_mock()
        set_preference(self.context, "xp", "off")
        self.award(2, "2026-W08")
        set_preference(self.context, "xp", "immediate")
        with patch("evennia_notices.services.route", side_effect=RuntimeError("temporarily down")):
            self.award(3)
            self.show()
        with override_settings(LINKS_NOTICE_SOURCES={"xp": "invalid.path.Provider"}):
            self.show()
            self.character.msg.assert_not_called()
        self.show()
        self.sessions[0].msg.assert_not_called()
        self.assertEqual(DeliveryReceipt.objects.filter(source="xp").count(), 3)
        self.assertEqual(XPNoticeReceipt.objects.get(week="2026-W08").state, State.SUPPRESSED)

    def test_maintenance_keeps_eligible_unread_and_removes_invalid_subject(self):
        from evennia_notices.services import maintain, summarize

        self.award(1, "2026-W08")
        self.award(2)
        self.assertEqual(maintain()["removed"], 0)
        self.assertEqual(summarize(self.context), (2, 0))
        XPLog.objects.filter(week="2026-W08").delete()
        self.assertEqual(summarize(self.context), (1, 0))
        self.assertEqual(maintain()["removed"], 1)
        self.assertEqual(len(self.project()), 1)

    @override_settings(NOTICES_ROUTINE_LIMIT=1)
    def test_compacted_projection_only_counts_and_renders_valid_constituents(self):
        from evennia_notices.services import maintain, summarize

        self.award(1, "2026-W08")
        self.award(2)
        [compacted] = self.project()
        self.assertTrue(compacted.notice.is_compacted)
        self.assertIn("multiple weeks", compacted.text)
        self.assertEqual(len(compacted.events), 2)
        self.assertEqual(summarize(self.context), (1, 0))
        XPLog.objects.filter(week="2026-W08").delete()
        [remaining] = self.project()
        self.assertEqual(len(remaining.events), 1)
        self.assertIn("2026-W09", remaining.text)
        self.assertNotIn("2026-W08", remaining.text)
        self.assertEqual(maintain()["removed"], 1)
        XPLog.objects.filter(week="2026-W09").delete()
        self.assertEqual(self.project(), [])
        self.assertEqual(summarize(self.context), (0, 0))

    def test_safe_projection_excludes_manual_reason_granter_and_alt(self):
        from evennia_links.notices import NoticeContext
        from evennia_notices.services import project

        alt = create.create_object("evennia.DefaultCharacter", key="Private Alt", nohome=True)
        self.account.characters.add(alt)
        record_xp(
            self.character.pk,
            "2.50",
            XPLog.SourceType.MANUAL_GRANT,
            0,
            reason="Private reason",
            granted_by=alt,
            week="2026-W09",
        )
        record_xp(alt.pk, 41, XPLog.SourceType.CUTSCENE, 19, week="2026-W09")
        [item] = self.project()
        self.assertIn("Manual Grant: +2.50", item.text)
        for text in ("Private reason", "Private Alt", "41.00", "|w"):
            self.assertNotIn(text, item.text)
        self.assertEqual(project(NoticeContext(self.account), source="xp"), [])
        with self.assertRaises(ValueError):
            project(NoticeContext(self.other, self.character), source="xp")

        from evennia_links.notices import StoredEvent
        from evennia_xp.integrations.notices import XPNoticeSource, event_for

        receipt = XPNoticeReceipt.objects.get(summary__character_id=self.character.pk)
        event = StoredEvent(
            **vars(event_for(receipt, self.character.pk)),
            recipient_kind="character",
            recipient_id=self.character.pk,
        )
        source = XPNoticeSource()
        denied = NoticeContext(self.other, self.character)
        self.assertEqual(source.evaluate([event], denied)[event.event_id].status, "invalid")
        with self.assertRaises(ValueError):
            source.render([event], denied)
