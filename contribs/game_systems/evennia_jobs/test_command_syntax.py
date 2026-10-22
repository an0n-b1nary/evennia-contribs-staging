# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Dotted revision addresses, trailing comments and strict switch selection."""

from django.test import SimpleTestCase, override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_jobs.commands import CmdDiscuss, CmdJobs, CmdRequest
from evennia_jobs.models import Job, RequestDecision, RequestWithdrawal
from evennia_jobs.review import review_request, submit_request
from evennia_jobs.test_requests import ANSWERS, FORMS


@override_settings(JOBS_REQUEST_FORMS=FORMS)
class TestRevisionCommands(EvenniaCommandTest):
    def submit(self, **kwargs):
        return submit_request(
            author=self.char2, form_key="build", title="Library", answers=ANSWERS, **kwargs
        )

    def test_each_outcome_uses_the_addressed_revision_and_keeps_comment_text(self):
        for switch, outcome in (
            ("approve", "approved"),
            ("decline", "declined"),
            ("revise", "changes_requested"),
        ):
            with self.subTest(switch=switch):
                submission = self.submit()
                reason = "Keep #12 and #12.3; price=0 # extra context"
                self.call(CmdJobs(), f"/{switch} #{submission.job.job_number}.1 # {reason}")
                decision = RequestDecision.objects.get(submission=submission)
                self.assertEqual((decision.outcome, decision.reason), (outcome, reason))

    def test_withdrawal_reason_is_optional_and_preserves_hash_references(self):
        for suffix, reason in (("", ""), (" # Revisit #12.3 # later", "Revisit #12.3 # later")):
            with self.subTest(suffix=suffix):
                submission = self.submit()
                self.call(
                    CmdRequest(),
                    f"/withdraw #{submission.job.job_number}.1{suffix}",
                    caller=self.char2,
                )
                withdrawal = RequestWithdrawal.objects.get(submission=submission)
                self.assertEqual(withdrawal.reason, reason)

    def test_old_and_malformed_review_forms_do_not_decide(self):
        submission = self.submit()
        number = submission.job.job_number
        for args in (
            f"/approve {number} 1=Old form",
            f"/approve {number}.1=Old separator",
            f"/approve {number}.1",
            f"/approve {number}.1 # ",
            f"/approve {number}.0 # Invalid",
            f"/approve {number}.1.2 # Invalid",
            f"/approve {number}.1#missing space",
            f"/approve/unknown {number}.1 # No",
            f"/approve/decline {number}.1 # No",
            f"/decline/share {number}.1 # No",
            f"/unknown {number}.1 # No",
        ):
            with self.subTest(args=args):
                self.call(CmdJobs(), args)
                self.assertFalse(RequestDecision.objects.filter(submission=submission).exists())

    def test_old_withdrawal_and_stacked_switches_do_not_withdraw(self):
        submission = self.submit()
        number = submission.job.job_number
        for args in (
            f"/withdraw {number} 1=Old form",
            f"/withdraw {number}.1=Old separator",
            f"/withdraw/cancel {number}.1 # No",
            f"/withdraw/unknown {number}.1 # No",
        ):
            with self.subTest(args=args):
                self.call(CmdRequest(), args, caller=self.char2)
                self.assertFalse(RequestWithdrawal.objects.filter(submission=submission).exists())

    def test_stale_revision_and_wrong_author_are_refused(self):
        first = self.submit()
        review_request(
            job=first.job,
            reviewer=self.char1,
            outcome="changes_requested",
            reason="Revise",
            expected_revision=1,
        )
        second = self.submit(job=first.job, expected_revision=1)
        number = first.job.job_number
        self.call(CmdJobs(), f"/approve {number}.1 # Stale")
        self.call(CmdRequest(), f"/withdraw {number}.1 # Stale", caller=self.char2)
        self.call(CmdRequest(), f"/withdraw {number}.2 # Wrong author", caller=self.char1)
        self.assertFalse(RequestDecision.objects.filter(submission=second).exists())
        self.assertFalse(RequestWithdrawal.objects.exists())
        self.call(CmdJobs(), f"/app #{number}.2 # Current")
        self.assertEqual(RequestDecision.objects.get(submission=second).reason, "Current")

    def test_invalid_switch_cannot_create_plain_ticket_or_discussion(self):
        for command in (CmdRequest, CmdDiscuss):
            for switch in ("unknown", "comment/unknown", "comment/comment"):
                with self.subTest(command=command, switch=switch):
                    self.call(command(), f"/{switch} Accidental title=Accidental body")
        self.assertFalse(Job.objects.exists())

    def test_unique_prefix_and_case_preserve_reason(self):
        submission = self.submit()
        self.call(CmdJobs(), f"/APP #{submission.job.job_number}.1 # Mixed CASE")
        self.assertEqual(RequestDecision.objects.get(submission=submission).reason, "Mixed CASE")


class TestTrailingComments(SimpleTestCase):
    def test_only_first_whitespace_delimited_hash_starts_comment(self):
        from evennia_jobs.command_syntax import split_comment

        for text, expected in (
            ("#12.3 # reason # more", ("#12.3", "reason # more")),
            ("12.3\t#\treason", ("12.3", "reason")),
            ("12.3 # uses #entry and #4.2", ("12.3", "uses #entry and #4.2")),
            ("#12.3", ("#12.3", "")),
            ("12.3 #entry", ("12.3 #entry", "")),
            ("12.3# reason", ("12.3# reason", "")),
        ):
            with self.subTest(text=text):
                self.assertEqual(split_comment(text), expected)
