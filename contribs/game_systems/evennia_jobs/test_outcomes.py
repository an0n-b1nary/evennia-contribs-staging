# SPDX-License-Identifier: BSD-3-Clause
"""Per-form decisions are enforced by the service and reflected in review UI."""

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_jobs.commands import CmdJobs
from evennia_jobs.forms import RequestReviewForm
from evennia_jobs.requests import request_forms
from evennia_jobs.review import review_request, submit_request

FORMS = {"short": {"outcomes": ["approved", "declined"], "questions": [("text", "Details")]}}


@override_settings(JOBS_REQUEST_FORMS=FORMS)
class TestReviewOutcomes(EvenniaCommandTest):
    def submit(self):
        return submit_request(
            author=self.char2, form_key="short", title="Chosen form", answers={"text": "Details"}
        )

    def test_service_refuses_disallowed_outcome_and_snapshot_survives_configuration_change(self):
        submission = self.submit()
        with override_settings(JOBS_REQUEST_FORMS={}):
            with self.assertRaisesMessage(ValidationError, "unavailable for this form"):
                review_request(
                    job=submission.job,
                    reviewer=self.char1,
                    outcome="changes_requested",
                    reason="Change",
                    expected_revision=1,
                )
            review_request(
                job=submission.job,
                reviewer=self.char1,
                outcome="approved",
                reason="Accepted",
                expected_revision=1,
            )

    def test_review_form_omits_disallowed_outcome(self):
        form = RequestReviewForm(schema=self.submit().schema)
        self.assertEqual(
            [value for value, _ in form.fields["outcome"].choices], ["approved", "declined"]
        )

    def test_schema_rejects_invalid_empty_and_duplicate_outcomes(self):
        for outcomes in ([], ["unknown"], ["approved", "approved"], "approved"):
            with (
                override_settings(
                    JOBS_REQUEST_FORMS={"short": {**FORMS["short"], "outcomes": outcomes}}
                ),
                self.assertRaises(ImproperlyConfigured),
            ):
                request_forms()

    def test_command_filters_by_latest_form_key(self):
        self.submit()
        with override_settings(JOBS_REQUEST_FORMS={"other": {"questions": [("text", "Details")]}}):
            submit_request(
                author=self.char2,
                form_key="other",
                title="Different form",
                answers={"text": "Other"},
            )
        result = self.call(CmdJobs(), "/form short", "Requests: short")
        self.assertIn("Chosen form", result)
        self.assertNotIn("Different form", result)
