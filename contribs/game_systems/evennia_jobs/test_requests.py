# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Structured requests: consent, revisions, review transactions and surface parity."""

from copy import deepcopy
from importlib import import_module
from unittest.mock import patch

from django.conf import settings
from django.core import signing
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.test import RequestFactory, override_settings
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from evennia_jobs.commands import CmdJobs, CmdRequest, _format_job_detail
from evennia_jobs.models import Job, RequestDecision, RequestOutcome, RequestSubmission
from evennia_jobs.request_views import RequestReviewView, StructuredRequestView
from evennia_jobs.requests import clean_answers, get_request_form, request_forms
from evennia_jobs.review import review_request, submit_request
from evennia_jobs.signals import request_approved
from evennia_jobs.views import JobDetailView, JobListView

FORMS = {
    "build": {
        "label": "Propose a build",
        "description": "Staff review this proposal before construction opens.",
        "questions": [
            {
                "key": "kind",
                "label": "Kind of build",
                "type": "choice",
                "choices": ["interior", "frontier"],
            },
            {"key": "description", "label": "Describe your proposal"},
            {"key": "terrain", "label": "Requested terrain", "required": False},
            {"key": "reuse", "label": "My content may return in a later game.", "type": "boolean"},
        ],
    },
    "pattern": {"label": "Propose a Pattern", "enabled": False, "questions": [("name", "Name")]},
}
ANSWERS = {"kind": "interior", "description": "A quiet library.", "reuse": True}


@override_settings(JOBS_REQUEST_FORMS=FORMS)
class TestRequestServices(EvenniaTest):
    """Real persisted revisions and decisions, with optional listeners on the seam."""

    def submit(self, **kwargs):
        return submit_request(
            author=self.char2, form_key="build", title="Library", answers=ANSWERS, **kwargs
        )

    def review(self, submission, outcome=RequestOutcome.APPROVED, **kwargs):
        return review_request(
            job=submission.job,
            reviewer=self.char1,
            outcome=outcome,
            reason="Fits the setting.",
            expected_revision=submission.revision,
            **kwargs,
        )

    def test_only_enabled_forms_are_available(self):
        self.assertEqual(list(request_forms()), ["build"])
        with self.assertRaises(ValidationError):
            get_request_form("pattern")

    def test_plain_requests_continue_to_work(self):
        job = Job.create_job("request", self.char2, "Question", "Details")
        self.assertFalse(job.submissions.exists())

    def test_structured_answers_and_wording_are_saved(self):
        submission = self.submit()
        self.assertEqual(submission.answers["terrain"], "")
        self.assertEqual(
            submission.schema["questions"][-1]["label"], FORMS["build"]["questions"][-1]["label"]
        )
        changed = deepcopy(FORMS)
        changed["build"]["questions"][-1]["label"] = "New acknowledgement"
        with override_settings(JOBS_REQUEST_FORMS=changed):
            submission.refresh_from_db()
            self.assertIn("later game", submission.answer_rows[-1]["label"])

    def test_required_acknowledgement_refuses_absence_false_and_invalid_values(self):
        for value in (None, False, "no", "perhaps", 1, []):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                submit_request(
                    author=self.char2,
                    form_key="build",
                    title="Library",
                    answers={**ANSWERS, "reuse": value},
                )
        self.assertFalse(Job.objects.exists())

    def test_choice_required_text_unknown_fields_and_length_are_validated(self):
        for answers in (
            {**ANSWERS, "kind": "castle"},
            {**ANSWERS, "description": " "},
            {**ANSWERS, "extra": "injected"},
            {**ANSWERS, "description": "x" * 10001},
        ):
            with self.subTest(answers=answers), self.assertRaises(ValidationError):
                clean_answers(get_request_form("build"), answers)

    def test_invalid_registry_fails_explicitly(self):
        for questions in (
            [{"key": "same"}, {"key": "same"}],
            [{"key": "bad key"}],
            [{"key": "x", "type": "code"}],
            [{"key": "x", "type": "choice", "choices": []}],
        ):
            with (
                override_settings(JOBS_REQUEST_FORMS={"test": {"questions": questions}}),
                self.assertRaises(ImproperlyConfigured),
            ):
                request_forms()

    def test_approval_signal_fires_once_across_repeated_review_close_and_reopen(self):
        submission = self.submit()
        events = []

        def receive(sender, **kwargs):
            events.append(kwargs["submission"].pk)

        request_approved.connect(receive, weak=False)
        try:
            first = self.review(submission)
            self.assertEqual(first.pk, self.review(submission).pk)
            submission.job.close()
            submission.job.reopen()
            self.review(submission)
            self.assertEqual(events, [submission.pk])
        finally:
            request_approved.disconnect(receive)

    def test_receiver_failure_rolls_back_decision_and_partner_database_writes(self):
        submission = self.submit()

        def receive(sender, **kwargs):
            Job.create_job("discuss", self.char1, "Partner work", "Must roll back")
            raise RuntimeError("Partner unavailable")

        request_approved.connect(receive, weak=False)
        try:
            with self.assertRaises(RuntimeError):
                self.review(submission)
            self.assertFalse(RequestDecision.objects.exists())
            self.assertEqual(Job.objects.count(), 1)
            submission.job.refresh_from_db()
            self.assertEqual(submission.job.status, "open")
        finally:
            request_approved.disconnect(receive)
        self.review(submission)
        self.assertEqual(RequestDecision.objects.count(), 1)

    def test_nonstaff_cannot_review_through_service(self):
        submission = self.submit()
        with self.assertRaises(PermissionDenied):
            review_request(
                job=submission.job,
                reviewer=self.char2,
                outcome="approved",
                reason="yes",
                expected_revision=1,
            )

    def test_changes_requested_preserves_history_and_allows_one_new_revision(self):
        first = self.submit()
        self.review(first, RequestOutcome.CHANGES_REQUESTED)
        second = self.submit(job=first.job, expected_revision=1)
        self.assertEqual(second.revision, 2)
        self.assertEqual(first.job.submissions.count(), 2)
        self.assertEqual(first.decision.outcome, "changes_requested")
        with self.assertRaises(ValidationError):
            self.submit(job=first.job, expected_revision=1)
        with self.assertRaises(ValidationError):
            self.review(first)
        self.review(second)
        self.assertEqual(RequestDecision.objects.count(), 2)

    def test_pending_approved_declined_and_closed_requests_cannot_be_revised(self):
        first = self.submit()
        with self.assertRaises(ValidationError):
            self.submit(job=first.job, expected_revision=1)
        self.review(first)
        with self.assertRaises(ValidationError):
            self.submit(job=first.job, expected_revision=1)
        second = self.submit()
        self.review(second, RequestOutcome.DECLINED)
        with self.assertRaises(ValidationError):
            self.submit(job=second.job, expected_revision=1)
        third = self.submit()
        self.review(third, RequestOutcome.CHANGES_REQUESTED)
        third.job.close()
        with self.assertRaises(ValidationError):
            self.submit(job=third.job, expected_revision=1)

    def test_conflicting_review_is_rejected(self):
        first = self.submit()
        self.review(first)
        with self.assertRaises(ValidationError):
            self.review(first, RequestOutcome.DECLINED)

    def test_another_character_cannot_revise(self):
        first = self.submit()
        self.review(first, RequestOutcome.CHANGES_REQUESTED)
        with self.assertRaises(PermissionDenied):
            submit_request(
                author=self.char1,
                form_key="build",
                title="Library",
                answers=ANSWERS,
                job=first.job,
                expected_revision=1,
            )

    def test_saved_request_renders_even_after_registry_removal(self):
        first = self.submit()
        self.review(first)
        with override_settings(JOBS_REQUEST_FORMS={}):
            text = _format_job_detail(first.job, False, sr_mode=True)
        self.assertIn("A quiet library.", text)
        self.assertIn("Approved by", text)
        self.assertIn("revision 1", text)


@override_settings(JOBS_REQUEST_FORMS=FORMS)
class TestRequestCommands(EvenniaCommandTest):
    """Complete questionnaire and staff review via real command parsing."""

    def test_questionnaire_submits_with_shared_validation(self):
        self.call(CmdRequest(), "/forms", "Request forms:")
        self.call(CmdRequest(), "/form build=Library")
        self.call(CmdRequest(), "/answer kind=interior")
        self.call(CmdRequest(), "/answer description=A quiet library.")
        self.call(CmdRequest(), "/answer terrain=")
        self.call(CmdRequest(), "/answer reuse=no", "This acknowledgement is required.")
        self.call(CmdRequest(), "/answer reuse=yes")
        self.call(CmdRequest(), "/preview", "Library")
        self.call(CmdRequest(), "/submit", "Ticket #1, revision 1, submitted.")
        self.assertEqual(
            RequestSubmission.objects.get().answers["description"], ANSWERS["description"]
        )
        self.call(CmdJobs(), "/approve 1 1=Fits the setting.", "Ticket #1: Approved (revision 1).")

    def test_cancel_does_not_create_a_ticket(self):
        self.call(CmdRequest(), "/form build=Library")
        self.call(CmdRequest(), "/cancel")
        self.assertFalse(Job.objects.exists())

    def test_multiline_editor_saves_the_answer_without_submitting(self):
        from evennia_jobs.request_commands import _answer_load, _answer_save

        self.call(CmdRequest(), "/form build=Library")
        self.call(CmdRequest(), "/edit description")
        self.assertEqual(_answer_load(self.char1), "")
        self.assertFalse(_answer_save(self.char1, " "))
        self.assertTrue(_answer_save(self.char1, "A reading room.\n\nA staircase leads upstairs."))
        self.assertIn("\n\n", _answer_load(self.char1))
        self.assertFalse(Job.objects.exists())
        self.char1.ndb._eveditor.quit()
        self.assertFalse(self.char1.attributes.has("jobs_request_editor"))

    def test_old_editor_cannot_change_a_replacement_questionnaire(self):
        from evennia_jobs.request_commands import _answer_save

        self.call(CmdRequest(), "/form build=Library")
        self.call(CmdRequest(), "/edit description")
        context = dict(self.char1.attributes.get("jobs_request_editor"))
        self.char1.ndb._eveditor.quit()
        self.call(CmdRequest(), "/cancel")
        self.call(CmdRequest(), "/form build=Library")
        self.char1.attributes.add("jobs_request_editor", context)
        self.assertFalse(_answer_save(self.char1, "Stale answer"))
        self.assertNotIn("description", self.char1.attributes.get("jobs_request_draft")["answers"])

    def test_questionnaire_refuses_changed_schema(self):
        self.call(CmdRequest(), "/form build=Library")
        changed = deepcopy(FORMS)
        changed["build"]["questions"][-1]["label"] = "Different consent"
        with override_settings(JOBS_REQUEST_FORMS=changed):
            self.call(CmdRequest(), "/submit", "This form has changed.")
        self.assertFalse(Job.objects.exists())

    def test_command_revision_renews_consent_and_keeps_both_versions(self):
        first = submit_request(
            author=self.char2, form_key="build", title="Library", answers=ANSWERS
        )
        self.call(CmdJobs(), "/revise 1 1=Describe the entrance.")
        self.call(CmdRequest(), "/revise 1", caller=self.char2)
        self.call(
            CmdRequest(), "/answer description=A library with an entrance.", caller=self.char2
        )
        self.call(CmdRequest(), "/submit", caller=self.char2)
        self.assertEqual(first.job.submissions.count(), 1)
        self.call(CmdRequest(), "/answer reuse=yes", caller=self.char2)
        self.call(CmdRequest(), "/submit", "Ticket #1, revision 2, submitted.", caller=self.char2)
        self.call(CmdJobs(), "/approve 1 2=Ready.")
        self.assertEqual(first.job.submissions.count(), 2)
        self.assertEqual(first.answers["description"], "A quiet library.")


@override_settings(JOBS_REQUEST_FORMS=FORMS, ROOT_URLCONF="evennia_jobs.tests")
class TestRequestWeb(EvenniaTest):
    """Render every new page and exercise actual HTTP submissions and decisions."""

    def request(self, view, *, user=None, data=None, **kwargs):
        factory = RequestFactory()
        request = factory.get("/jobs/") if data is None else factory.post("/jobs/", data)
        request.user = user or self.account2
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        character = self.char1 if request.user == self.account else self.char2
        with (
            patch("evennia_jobs.authoring.require_character", return_value=character.pk),
            patch.object(request.user, "get_all_puppets", return_value=[character]),
        ):
            response = view.as_view()(request, **kwargs)
        if hasattr(response, "render"):
            response.render()
        return response

    def payload(self):
        token = signing.dumps(
            {"key": "build", "schema": get_request_form("build")}, salt="jobs-request"
        )
        return {
            "title": "Library",
            "answer_kind": "interior",
            "answer_description": "A quiet library.",
            "answer_reuse": "on",
            "schema_token": token,
        }

    def test_form_and_list_render_with_accessible_controls(self):
        response = self.request(StructuredRequestView, form_key="build")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('for="id_answer_reuse"', html)
        self.assertIn('aria-describedby="id_answer_reuse_errors"', html)
        self.assertIn('class="form-check-input"', html)
        self.assertIn('name="csrfmiddlewaretoken"', html)
        self.assertIn("Staff review", html)
        self.assertEqual(response.context_data["acting_character"], self.char2)
        self.assertIn('aria-describedby="form-acting-as"', html)
        self.assertIn(self.char2.key, html)
        response = self.request(JobListView)
        self.assertIn('href="/jobs/forms/build/"', response.content.decode())

    def test_web_submit_and_staff_review_match_command_answers(self):
        response = self.request(StructuredRequestView, form_key="build", data=self.payload())
        self.assertEqual(response.status_code, 302)
        submission = RequestSubmission.objects.get()
        self.assertEqual(submission.answers, clean_answers(get_request_form("build"), ANSWERS))
        response = self.request(RequestReviewView, user=self.account, pk=submission.job_id)
        self.assertIn("A quiet library.", response.content.decode())
        self.assertEqual(response.context_data["acting_character"], self.char1)
        self.assertIn('aria-describedby="form-acting-as"', response.content.decode())
        response = self.request(
            RequestReviewView,
            user=self.account,
            pk=submission.job_id,
            data={"revision": 1, "outcome": "approved", "reason": "Fits the setting."},
        )
        self.assertEqual(response.status_code, 302)
        response = self.request(JobDetailView, pk=submission.job_id)
        self.assertIn("Approved", response.content.decode())

    def test_missing_acknowledgement_and_forged_schema_are_refused(self):
        for payload in (
            {**self.payload(), "answer_reuse": ""},
            {**self.payload(), "answer_reuse": "no"},
            {**self.payload(), "answer_reuse": "perhaps"},
            {**self.payload(), "schema_token": "forged"},
        ):
            response = self.request(StructuredRequestView, form_key="build", data=payload)
            self.assertEqual(response.status_code, 200)
        self.assertFalse(Job.objects.exists())

    def test_disabled_form_is_not_submittable(self):
        from django.http import Http404

        with self.assertRaises(Http404):
            self.request(StructuredRequestView, form_key="pattern")

    def test_registry_change_invalidates_an_open_web_form(self):
        payload = self.payload()
        changed = deepcopy(FORMS)
        changed["build"]["questions"][-1]["label"] = "Changed acknowledgement"
        with override_settings(JOBS_REQUEST_FORMS=changed):
            response = self.request(StructuredRequestView, form_key="build", data=payload)
        self.assertIn("This form has changed", response.content.decode())
        self.assertFalse(Job.objects.exists())

    def test_stale_web_review_cannot_approve_a_new_revision(self):
        first = submit_request(
            author=self.char2, form_key="build", title="Library", answers=ANSWERS
        )
        review_request(
            job=first.job,
            reviewer=self.char1,
            outcome="changes_requested",
            reason="An entrance?",
            expected_revision=1,
        )
        submit_request(
            author=self.char2,
            form_key="build",
            title="Library",
            answers=ANSWERS,
            job=first.job,
            expected_revision=1,
        )
        response = self.request(
            RequestReviewView,
            user=self.account,
            pk=first.job_id,
            data={"revision": 1, "outcome": "approved", "reason": "Ready."},
        )
        self.assertIn("This request has changed", response.content.decode())
        self.assertEqual(RequestDecision.objects.count(), 1)

    def test_nonstaff_cannot_review_and_other_player_cannot_read(self):
        first = submit_request(
            author=self.char2, form_key="build", title="Library", answers=ANSWERS
        )
        with self.assertRaises(PermissionDenied):
            self.request(RequestReviewView, pk=first.job_id)
        stranger = self.account
        with (
            patch("evennia_jobs.views.is_staff_user", return_value=False),
            patch("evennia_jobs.views.get_character_id", return_value=self.char1.pk),
            self.assertRaises(PermissionDenied),
        ):
            self.request(JobDetailView, user=stranger, pk=first.job_id)

    def test_web_revision_requires_new_acknowledgement_and_preserves_old_answers(self):
        first = submit_request(
            author=self.char2, form_key="build", title="Library", answers=ANSWERS
        )
        review_request(
            job=first.job,
            reviewer=self.char1,
            outcome="changes_requested",
            reason="Add an entrance.",
            expected_revision=1,
        )
        response = self.request(StructuredRequestView, pk=first.job_id)
        html = response.content.decode()
        self.assertIn("A quiet library.", html)
        self.assertNotIn("checked", html)
        response = self.request(
            StructuredRequestView,
            pk=first.job_id,
            data={
                **self.payload(),
                "revision": 1,
                "answer_description": "A library with an entrance.",
            },
        )
        self.assertEqual(response.status_code, 302)
        response = self.request(JobDetailView, pk=first.job_id)
        self.assertIn("revision 1", response.content.decode())
        self.assertIn("revision 2", response.content.decode())

    def test_api_history_retains_existing_privacy_and_is_read_only(self):
        from rest_framework.test import APIRequestFactory, force_authenticate

        from evennia_jobs.api.views import JobViewSet

        first = submit_request(
            author=self.char2, form_key="build", title="Library", answers=ANSWERS
        )
        request = APIRequestFactory().get("/jobs/")
        force_authenticate(request, user=self.account2)
        with patch("evennia_jobs.api.views.get_character_id", return_value=self.char2.pk):
            response = JobViewSet.as_view({"get": "retrieve"})(request, pk=first.job_id)
        self.assertEqual(response.data["submissions"][0]["answers"]["reuse"], True)
        self.assertNotIn("create", JobViewSet.__dict__)
