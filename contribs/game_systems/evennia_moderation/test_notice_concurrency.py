# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Committed file-backed source claims, duplicate recording and socket boundaries."""

from unittest.mock import Mock, patch

from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from evennia.accounts.models import AccountDB
from evennia.utils.test_resources import EvenniaTestMixin

from evennia_links.notices import NoticeContext
from evennia_links.test_transactions import committed_race
from evennia_moderation import notices
from evennia_moderation.models import Notice
from evennia_moderation.tests import FORMS, AdmissionFixture


@override_settings(LINKS_NOTICE_SOURCES={}, NOTICES_ENABLED=False)
class OutcomeRaces(EvenniaTestMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        if connection.vendor == "sqlite" and "mode=memory" in connection.settings_dict["NAME"]:
            self.skipTest("Run separately with file-backed TEST database")

    def record(self):
        return notices.record_outcome(
            AccountDB.objects.get(pk=self.account.pk),
            kind="lapsed",
            submission_id=7,
            applicant_name="Committed fixture",
        )

    def test_competing_record_calls_create_one_source_event(self):
        committed_race(self.record, self.record)
        self.assertEqual(Notice.objects.count(), 1)

    def test_two_source_deliveries_send_only_after_one_committed_claim(self):
        with patch.object(notices, "_safe_route", return_value="retry"):
            row = self.record()
        session = Mock()
        session.get_account.return_value = self.account
        session.get_puppet.return_value = None
        context = NoticeContext(self.account, None, session)
        observations = []

        def sent(text):
            observations.append(
                (connection.in_atomic_block, Notice.objects.get(pk=row.pk).route_state)
            )

        session.msg.side_effect = sent
        with patch.object(notices, "connected_contexts", return_value=[context]):
            committed_race(
                lambda: notices.route_notice(row.pk), lambda: notices.route_notice(row.pk)
            )
        self.assertEqual(observations, [(False, "attempting")])
        self.assertEqual(session.msg.call_count, 1)
        row.refresh_from_db()
        self.assertEqual(row.route_state, "fallback")

    def test_detached_session_is_not_messaged_after_claim(self):
        with patch.object(notices, "_safe_route", return_value="retry"):
            row = self.record()
        session = Mock()
        session.get_account.return_value = self.account
        session.get_puppet.return_value = None
        context = NoticeContext(self.account, None, session)
        with patch.object(notices, "connected_contexts", side_effect=[[context], []]):
            # Nothing reached a socket, so the committed claim returns to pending.
            self.assertEqual(notices.route_notice(row.pk), "pending")
        session.msg.assert_not_called()
        row.refresh_from_db()
        self.assertIsNone(row.acknowledged_at)
        with patch.object(notices, "connected_contexts", return_value=[context]):
            self.assertEqual(notices.route_notice(row.pk), "fallback")
        session.msg.assert_called_once()

    def test_failed_acknowledgement_does_not_interrupt_commit_callbacks(self):
        with patch.object(notices, "_safe_route", return_value="retry"):
            row = self.record()
        session = Mock()
        session.get_account.return_value = self.account
        session.get_puppet.return_value = None
        context = NoticeContext(self.account, None, session)
        later_callback = Mock()

        with (
            patch.object(notices, "connected_contexts", return_value=[context]),
            patch.object(notices, "_ack", side_effect=RuntimeError("Database unavailable")),
            self.assertLogs("evennia", level="WARNING"),
            transaction.atomic(),
        ):
            self.assertEqual(notices.route_notice(row.pk), "attempting")
            transaction.on_commit(later_callback)
            session.msg.assert_not_called()

        later_callback.assert_called_once_with()
        row.refresh_from_db()
        self.assertEqual(row.route_state, "attempting")
        self.assertIsNone(row.delivered_at)
        self.assertEqual(notices.route_notice(row.pk), "attempting")
        session.msg.assert_called_once()


@override_settings(
    JOBS_REQUEST_FORMS=FORMS,
    MODERATION_REFERRAL_ALLOWANCE=1,
    LINKS_NOTICE_SOURCES={},
    NOTICES_ENABLED=False,
)
class ReferralOutcomeRaces(AdmissionFixture, EvenniaTestMixin, TransactionTestCase):
    """Two actual staff reviews retain one outcome and one domain decision."""

    def setUp(self):
        super().setUp()
        if connection.vendor == "sqlite" and "mode=memory" in connection.settings_dict["NAME"]:
            self.skipTest("Run separately with file-backed TEST database")

    def test_two_reviews_of_one_referral_emit_one_outcome(self):
        from evennia_jobs.models import RequestDecision
        from evennia_moderation import admissions
        from evennia_moderation.models import Referral

        code = admissions.issue_code(self.account2)
        application = self.apply(code=code.code)
        committed_race(lambda: self.review(application), lambda: self.review(application))
        self.assertEqual(Notice.objects.count(), 1)
        self.assertEqual(Referral.objects.count(), 1)
        self.assertEqual(RequestDecision.objects.count(), 1)
