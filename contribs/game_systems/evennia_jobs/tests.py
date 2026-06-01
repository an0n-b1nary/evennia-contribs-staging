# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_jobs.

Covers models, commands (via EvenniaCommandTest), and API privacy logic
(via rest_framework.test.APIRequestFactory).

Run:
    evennia test --settings test_jobs_settings.py evennia_jobs
"""

from unittest.mock import MagicMock, patch

from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest

from evennia_jobs.commands import (
    CmdBug,
    CmdDiscuss,
    CmdIssue,
    CmdJobs,
    CmdRequest,
    _format_job_detail,
)
from evennia_jobs.models import Job, JobComment, JobPriority, JobStatus, JobType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(author, job_type=JobType.REQUEST, title="Test Ticket", desc="Details."):
    return Job.create_job(job_type=job_type, author=author, title=title, description=desc)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestJobModel(EvenniaTest):
    def test_create_job_starts_at_one(self):
        job = _make_job(self.char1)
        self.assertEqual(job.job_number, 1)

    def test_job_number_increments_globally(self):
        j1 = _make_job(self.char1, job_type=JobType.REQUEST)
        j2 = _make_job(self.char1, job_type=JobType.BUG)
        j3 = _make_job(self.char1, job_type=JobType.DISCUSS)
        self.assertEqual(j1.job_number, 1)
        self.assertEqual(j2.job_number, 2)
        self.assertEqual(j3.job_number, 3)

    def test_defaults(self):
        job = _make_job(self.char1)
        self.assertEqual(job.status, JobStatus.OPEN)
        self.assertEqual(job.priority, JobPriority.NORMAL)
        self.assertIsNone(job.closed_at)

    def test_author_name_denormalized(self):
        job = _make_job(self.char1)
        self.assertEqual(job.author_name, self.char1.key)

    def test_null_author_uses_unknown(self):
        job = Job.create_job(job_type=JobType.BUG, author=None, title="Anon", description="x")
        self.assertIsNone(job.author)
        self.assertEqual(job.author_name, "Unknown")

    def test_status_transitions(self):
        job = _make_job(self.char1)
        job.mark_in_review()
        self.assertEqual(job.status, JobStatus.IN_REVIEW)
        job.mark_answered()
        self.assertEqual(job.status, JobStatus.ANSWERED)
        job.close()
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CLOSED)
        self.assertIsNotNone(job.closed_at)
        job.reopen()
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.OPEN)
        self.assertIsNone(job.closed_at)

    def test_by_priority_order(self):
        _make_job(self.char1, title="Normal")
        j_high = _make_job(self.char1, title="High")
        j_high.priority = JobPriority.HIGH
        j_high.save(update_fields=["priority"])
        j_urgent = _make_job(self.char1, title="Urgent")
        j_urgent.priority = JobPriority.URGENT
        j_urgent.save(update_fields=["priority"])

        ordered = list(Job.objects.by_priority())
        self.assertEqual(ordered[0].title, "Urgent")
        self.assertEqual(ordered[1].title, "High")
        self.assertEqual(ordered[2].title, "Normal")


class TestJobCommentModel(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.job = _make_job(self.char1)

    def test_create_comment_factory(self):
        c = JobComment.create_comment(job=self.job, author=self.char2, content="A reply.")
        self.assertEqual(c.job, self.job)
        self.assertFalse(c.is_staff_only)
        self.assertEqual(c.author_name, self.char2.key)

    def test_staff_only_flag(self):
        c = JobComment.create_comment(
            job=self.job, author=self.char1, content="Internal.", is_staff_only=True
        )
        self.assertTrue(c.is_staff_only)

    def test_cascade_delete(self):
        JobComment.create_comment(job=self.job, author=self.char1, content="x")
        self.assertEqual(JobComment.objects.count(), 1)
        self.job.delete()
        self.assertEqual(JobComment.objects.count(), 0)


# ---------------------------------------------------------------------------
# Command tests
# ---------------------------------------------------------------------------


class TestCmdRequestCreate(EvenniaCommandTest):
    def test_inline_create(self):
        result = self.call(CmdRequest(), "My Proposal=Please add this feature.", caller=self.char1)
        self.assertIn("submitted", result)
        job = Job.objects.get(job_number=1)
        self.assertEqual(job.job_type, JobType.REQUEST)
        self.assertEqual(job.title, "My Proposal")

    def test_empty_desc_rejected(self):
        result = self.call(CmdRequest(), "My Title=", caller=self.char1)
        self.assertIn("empty", result)
        self.assertEqual(Job.objects.count(), 0)

    def test_no_args_shows_empty_message(self):
        result = self.call(CmdRequest(), "", caller=self.char1)
        self.assertIn("no open tickets", result.lower())

    def test_editor_path_sets_ndb_context(self):
        with patch("evennia_jobs.commands.EvEditor"):
            self.call(CmdRequest(), "My Proposal", caller=self.char1)
        ctx = self.char1.ndb._jobs_context
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["mode"], "create")
        self.assertEqual(ctx["job_type"], "request")


class TestCmdIssueAnonymity(EvenniaCommandTest):
    def test_reporter_hidden_from_nonstaff(self):
        job = _make_job(self.char2, job_type=JobType.ISSUE)
        output = _format_job_detail(job, viewer_is_staff=False)
        self.assertIn("[Reporter hidden]", output)
        self.assertNotIn(self.char2.key, output)

    def test_reporter_visible_to_staff(self):
        job = _make_job(self.char2, job_type=JobType.ISSUE)
        output = _format_job_detail(job, viewer_is_staff=True)
        self.assertNotIn("[Reporter hidden]", output)
        self.assertIn(self.char2.key, output)


class TestCmdJobsStaffLock(EvenniaCommandTest):
    def test_default_lock_blocks_nonstaff(self):
        self.assertFalse(CmdJobs().access(self.char2, "cmd"))
        self.assertFalse(CmdDiscuss().access(self.char2, "cmd"))

    def test_default_lock_allows_staff(self):
        self.assertTrue(CmdJobs().access(self.char1, "cmd"))
        self.assertTrue(CmdDiscuss().access(self.char1, "cmd"))


class TestCmdJobsManagement(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.job = _make_job(self.char2)

    def test_close_and_reopen(self):
        result = self.call(CmdJobs(), f"/close {self.job.job_number}", caller=self.char1)
        self.assertIn("closed", result)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "closed")

        result = self.call(CmdJobs(), f"/reopen {self.job.job_number}", caller=self.char1)
        self.assertIn("reopened", result)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "open")

    def test_staffonly_comment_not_visible_to_submitter(self):
        JobComment.objects.create(
            job=self.job,
            author=self.char1,
            author_name=self.char1.key,
            content="Hidden note.",
            is_staff_only=True,
        )
        result = self.call(CmdRequest(), str(self.job.job_number), caller=self.char2)
        self.assertNotIn("Hidden note.", result)


class TestUsesScreenreaderFallback(EvenniaCommandTest):
    """uses_screenreader falls back to a no-op when evennia-accessibility is absent."""

    def test_sr_fallback_returns_false(self):
        import importlib

        import evennia_jobs.commands as cmd_module

        # Setting the module to None in sys.modules makes ``import
        # evennia_accessibility`` raise ImportError, exercising the fallback.
        with patch.dict("sys.modules", {"evennia_accessibility": None}):
            try:
                importlib.reload(cmd_module)
                self.assertFalse(cmd_module.uses_screenreader(self.char1))
            finally:
                # Reload again WITHOUT the patch so the real accessibility-backed
                # module is restored — otherwise the fallback would leak into
                # every later test sharing this process.
                importlib.reload(cmd_module)


# ---------------------------------------------------------------------------
# API privacy tests
# ---------------------------------------------------------------------------


class TestJobAPIPrivacy(EvenniaTest):
    """Test the serializer privacy logic via direct calls (no HTTP layer needed)."""

    def setUp(self):
        super().setUp()
        self.issue_job = _make_job(self.char2, job_type=JobType.ISSUE, title="Complaint")
        self.comment = JobComment.objects.create(
            job=self.issue_job,
            author=self.char1,
            author_name=self.char1.key,
            content="Staff note.",
            is_staff_only=True,
        )

    def _make_request(self, is_staff=False):
        """Build a minimal fake request."""
        req = MagicMock()
        req.user.is_authenticated = True
        if is_staff:
            req.user.locks.check_lockstring.return_value = True
        else:
            req.user.locks.check_lockstring.return_value = False
        return req

    def test_issue_reporter_masked_for_nonstaff(self):
        from evennia_jobs.api.serializers import JobSerializer

        req = self._make_request(is_staff=False)
        serializer = JobSerializer(self.issue_job, context={"request": req})
        self.assertIsNone(serializer.data["author_name"])

    def test_issue_reporter_visible_to_staff(self):
        from evennia_jobs.api.serializers import JobSerializer

        req = self._make_request(is_staff=True)
        serializer = JobSerializer(self.issue_job, context={"request": req})
        self.assertEqual(serializer.data["author_name"], self.char2.key)

    def test_staff_only_comment_hidden_from_nonstaff(self):
        from evennia_jobs.api.serializers import JobSerializer

        req = self._make_request(is_staff=False)
        serializer = JobSerializer(self.issue_job, context={"request": req})
        self.assertEqual(serializer.data["comments"], [])

    def test_staff_only_comment_visible_to_staff(self):
        from evennia_jobs.api.serializers import JobSerializer

        req = self._make_request(is_staff=True)
        serializer = JobSerializer(self.issue_job, context={"request": req})
        self.assertEqual(len(serializer.data["comments"]), 1)
        self.assertEqual(serializer.data["comments"][0]["content"], "Staff note.")

    def test_get_queryset_nonstaff_excludes_discuss(self):
        from evennia_jobs.api.views import JobViewSet

        discuss_job = _make_job(self.char1, job_type=JobType.DISCUSS)
        request = self._make_request(is_staff=False)
        # Give the request user a character id matching char2
        request.user.get_all_puppets.return_value = [self.char2]
        request.user.account = request.user

        viewset = JobViewSet()
        viewset.request = request
        viewset.kwargs = {}

        qs = viewset.get_queryset()
        pks = list(qs.values_list("pk", flat=True))
        # char2's issue_job should be visible; discuss_job should not
        self.assertIn(self.issue_job.pk, pks)
        self.assertNotIn(discuss_job.pk, pks)
