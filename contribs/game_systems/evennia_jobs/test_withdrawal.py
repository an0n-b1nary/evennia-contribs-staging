from django.core.exceptions import PermissionDenied, ValidationError
from django.test import override_settings
from evennia.utils.test_resources import EvenniaTest

from evennia_jobs.api.serializers import RequestSubmissionSerializer
from evennia_jobs.models import JobStatus, RequestDecision, RequestWithdrawal
from evennia_jobs.request_commands import format_submissions
from evennia_jobs.requests import get_request_form, request_forms
from evennia_jobs.review import review_request, submit_request, withdraw_request

FORMS = {
    "public": {"questions": [("reason", "Reason")]},
    "owned": {"owner": "evennia_building", "questions": [("pointer", "Pointer")]},
}


@override_settings(JOBS_REQUEST_FORMS=FORMS)
class TestWithdrawal(EvenniaTest):
    def submit(self, **kwargs):
        return submit_request(
            author=self.char2,
            form_key="public",
            title="Proposal",
            answers={"reason": "Details"},
            **kwargs,
        )

    def review(self, submission):
        return review_request(
            job=submission.job,
            reviewer=self.char1,
            outcome="approved",
            reason="Approved",
            expected_revision=submission.revision,
        )

    def test_domain_forms_hidden_and_refused(self):
        self.assertEqual(set(request_forms()), {"public"})
        for owner in (None, "other_domain"):
            with self.assertRaises(ValidationError):
                get_request_form("owned", owner=owner)
        schema = get_request_form("owned", owner="evennia_building")
        self.assertEqual(schema["owner"], "evennia_building")
        with self.assertRaises(ValidationError):
            submit_request(
                author=self.char2, form_key="owned", title="Forged", answers={"pointer": "forged"}
            )

    def test_withdraw_leaves_active_queue_and_all_history_surfaces(self):
        submission = self.submit()
        withdrawal = withdraw_request(
            job=submission.job, author=self.char2, expected_revision=1, reason="Editing"
        )
        submission.job.refresh_from_db()
        submission.refresh_from_db()
        self.assertEqual(submission.job.status, JobStatus.ANSWERED)
        self.assertEqual(submission.effective_state, "withdrawn")
        self.assertFalse(RequestDecision.objects.exists())
        self.assertIn("Withdrawn", format_submissions(submission.job))
        data = RequestSubmissionSerializer(submission).data
        self.assertEqual(data["effective_state"], "withdrawn")
        self.assertEqual(data["withdrawal"]["reason"], "Editing")
        repeat = withdraw_request(job=submission.job, author=self.char2, expected_revision=1)
        self.assertEqual(repeat.pk, withdrawal.pk)
        second = self.submit(job=submission.job, expected_revision=1)
        self.assertEqual(second.revision, 2)
        second.job.refresh_from_db()
        self.assertEqual(second.job.status, JobStatus.OPEN)
        self.assertEqual(RequestWithdrawal.objects.count(), 1)

    def test_withdraw_wins_then_review_is_stale(self):
        submission = self.submit()
        withdraw_request(job=submission.job, author=self.char2, expected_revision=1)
        with self.assertRaisesMessage(ValidationError, "withdrawn"):
            self.review(submission)
        self.assertFalse(RequestDecision.objects.exists())

    def test_review_wins_then_withdraw_is_stale(self):
        submission = self.submit()
        self.review(submission)
        with self.assertRaisesMessage(ValidationError, "reviewed"):
            withdraw_request(job=submission.job, author=self.char2, expected_revision=1)
        self.assertFalse(RequestWithdrawal.objects.exists())

    def test_author_and_revision_are_checked(self):
        submission = self.submit()
        with self.assertRaises(PermissionDenied):
            withdraw_request(job=submission.job, author=self.char1, expected_revision=1)
        with self.assertRaises(ValidationError):
            withdraw_request(job=submission.job, author=self.char2, expected_revision=2)

    def test_generic_web_refuses_owned_form(self):
        from evennia_jobs.request_views import StructuredRequestView

        view = StructuredRequestView()
        view.kwargs = {"form_key": "owned"}
        view.latest = None
        from django.http import Http404

        with self.assertRaises(Http404):
            view.get_schema()
