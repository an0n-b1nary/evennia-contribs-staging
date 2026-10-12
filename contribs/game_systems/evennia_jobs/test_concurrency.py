"""Run with a file-backed TEST database to exercise SQLite writer serialization."""

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TransactionTestCase, override_settings
from evennia.utils.test_resources import EvenniaTestMixin

from evennia_links.test_transactions import committed_race

from .models import RequestDecision, RequestWithdrawal
from .review import review_request, submit_request, withdraw_request


@override_settings(JOBS_REQUEST_FORMS={"proposal": {"questions": [("reason", "Reason")]}})
class TestReviewWithdrawalRace(EvenniaTestMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        if connection.vendor == "sqlite" and "mode=memory" in connection.settings_dict["NAME"]:
            self.skipTest("Race gate runs separately with a file-backed SQLite TEST database")
        self.submission = submit_request(
            author=self.char2,
            form_key="proposal",
            title="Concurrent proposal",
            answers={"reason": "Details"},
        )

    def approve(self):
        return review_request(
            job=self.submission.job,
            reviewer=self.char1,
            outcome="approved",
            reason="Reviewed",
            expected_revision=1,
        )

    def withdraw(self):
        return withdraw_request(job=self.submission.job, author=self.char2, expected_revision=1)

    def test_withdrawal_commits_first(self):
        with self.assertRaisesMessage(ValidationError, "withdrawn"):
            committed_race(self.withdraw, self.approve)
        self.assertEqual(RequestWithdrawal.objects.count(), 1)
        self.assertEqual(RequestDecision.objects.count(), 0)

    def test_review_commits_first(self):
        with self.assertRaisesMessage(ValidationError, "reviewed"):
            committed_race(self.approve, self.withdraw)
        self.assertEqual(RequestDecision.objects.count(), 1)
        self.assertEqual(RequestWithdrawal.objects.count(), 0)
