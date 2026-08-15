# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_jobs.

Covers models, commands (via EvenniaCommandTest), the web pages (rendered
for real), and API privacy logic (via rest_framework.test.APIRequestFactory).

This module doubles as a **test URLconf** (see ``urlpatterns`` below). Cases
that reverse a URL or render a template opt in with
``@override_settings(ROOT_URLCONF=__name__)``.

Run:
    evennia test --settings test_jobs_settings.py evennia_jobs
"""

from importlib import import_module
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError
from django.test import RequestFactory, override_settings
from django.urls import include, path
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from evennia.web.urls import urlpatterns as evennia_default_urlpatterns

from evennia_jobs.commands import (
    CmdBug,
    CmdDiscuss,
    CmdIssue,
    CmdJobs,
    CmdRequest,
    _format_job_detail,
)
from evennia_jobs.models import Job, JobComment, JobPriority, JobStatus, JobType
from evennia_jobs.views import (
    JobAllView,
    JobCommentCreateView,
    JobCreateView,
    JobDetailView,
    JobListView,
)

# ---------------------------------------------------------------------------
# Test URLconf (see the module docstring)
# ---------------------------------------------------------------------------

# evennia_jobs mounts its routes without a namespace, exactly as its urls.py
# documents. Evennia's own routes come along because website/base.html — which
# every jobs template extends — reverses "index" and the account routes.
urlpatterns = [
    path("jobs/", include("evennia_jobs.urls")),
    *evennia_default_urlpatterns,
]

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

    def test_create_job_recovers_from_number_collision(self):
        """A lost race on job_number is retried, not surfaced as an error.

        Force the first ``objects.create`` to raise IntegrityError (as the DB
        would on a duplicate job_number), then delegate to the real create. The
        retry loop should re-read Max() and succeed on the next attempt.
        """
        real_create = Job.objects.create
        state = {"raised": False}

        def flaky_create(*args, **kwargs):
            if not state["raised"]:
                state["raised"] = True
                raise IntegrityError("simulated duplicate job_number")
            return real_create(*args, **kwargs)

        with patch.object(Job.objects, "create", side_effect=flaky_create):
            job = Job.create_job(
                job_type=JobType.REQUEST,
                author=self.char1,
                title="Racy",
                description="x",
            )

        self.assertTrue(state["raised"])  # the collision path executed
        self.assertEqual(job.job_number, 1)
        self.assertEqual(Job.objects.count(), 1)

    def test_create_job_raises_after_exhausting_retries(self):
        """If every attempt collides, the IntegrityError propagates and no row lands."""
        with (
            patch.object(Job.objects, "create", side_effect=IntegrityError("always collides")),
            self.assertRaises(IntegrityError),
        ):
            Job.create_job(
                job_type=JobType.REQUEST,
                author=self.char1,
                title="Doomed",
                description="x",
            )
        self.assertEqual(Job.objects.count(), 0)


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


# ---------------------------------------------------------------------------
# Web pages: render for real
# ---------------------------------------------------------------------------


@override_settings(ROOT_URLCONF=__name__)
class TestWebPagesRender(EvenniaTest):
    """
    Render every jobs page for real.

    A CBV returns a lazy TemplateResponse, so a test that only inspects
    context_data never compiles the template — which is how both authoring
    forms shipped as guaranteed TemplateSyntaxErrors under a green suite.
    Each case here calls response.render().

    RequestFactory + direct view invocation rather than Django's TestClient,
    because the TestClient triggers an Evennia template-context RecursionError
    on authenticated HTML pages.

    EvenniaTest defaults: account/char1 = Developer (staff); account2/char2 =
    non-staff. Bare test accounts have no sessions, so get_all_puppets()
    returns [] — every case that needs a character patches it.
    """

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.job = _make_job(self.char2, title="Door is stuck", desc="It will not open.")
        self.issue = _make_job(self.char2, job_type=JobType.ISSUE, title="Player conduct")

    def _render(self, view, user=None, puppet=None, method="get", **kwargs):
        request = getattr(self.factory, method)("/jobs/")
        request.user = AnonymousUser() if user is None else user
        # Evennia's general_context processor reads request.session["puppet"]
        # for any authenticated user, and RequestFactory attaches no session.
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        if puppet is None:
            response = view.as_view()(request, **kwargs)
        else:
            with patch.object(user, "get_all_puppets", return_value=[puppet]):
                response = view.as_view()(request, **kwargs)
        response.render()
        return response.content.decode()

    # -- ticket lists -------------------------------------------------------

    def test_my_tickets_renders_the_submitters_own_tickets(self):
        html = self._render(JobListView, user=self.account2, puppet=self.char2)
        self.assertIn("My Tickets", html)
        self.assertIn("Door is stuck", html)
        # ISSUE tickets mask the reporter from non-staff, even their own.
        self.assertIn("[anonymous]", html)
        # Non-staff get no route into the full queue.
        self.assertNotIn("All Open Tickets", html)

    def test_queue_renders_for_staff_with_the_assignee_column(self):
        html = self._render(JobAllView, user=self.account, puppet=self.char1)
        self.assertIn("Ticket Queue", html)
        self.assertIn("Assignee", html)
        # Staff see the real reporter on an ISSUE.
        self.assertIn(self.char2.key, html)

    def test_empty_ticket_list_renders_its_empty_state(self):
        Job.objects.all().delete()
        html = self._render(JobListView, user=self.account2, puppet=self.char2)
        self.assertIn("You have no open tickets.", html)
        self.assertIn("+request", html)

    # -- ticket detail ------------------------------------------------------

    def test_ticket_detail_renders_description_and_comments(self):
        JobComment.create_comment(job=self.job, author=self.char1, content="Looking into it.")
        html = self._render(JobDetailView, user=self.account, puppet=self.char1, pk=self.job.pk)
        self.assertIn(f"Ticket #{self.job.job_number}", html)
        self.assertIn("It will not open.", html)
        self.assertIn("Looking into it.", html)

    def test_ticket_detail_marks_staff_only_notes(self):
        JobComment.create_comment(
            job=self.job, author=self.char1, content="Internal note.", is_staff_only=True
        )
        html = self._render(JobDetailView, user=self.account, puppet=self.char1, pk=self.job.pk)
        self.assertIn("Internal note.", html)
        self.assertIn("Staff-only", html)

    def test_ticket_detail_renders_without_comments(self):
        html = self._render(JobDetailView, user=self.account, puppet=self.char1, pk=self.job.pk)
        self.assertIn("No comments yet.", html)

    # -- authoring forms ----------------------------------------------------

    def test_request_form_renders_with_a_working_cancel_link(self):
        html = self._render(
            JobCreateView, user=self.account2, puppet=self.char2, job_type="request"
        )
        self.assertIn("New Request", html)
        self.assertIn("Request details", html)
        # {% url 'job-list' as cancel_url %} — the Cancel link only appears
        # once the route actually reverses.
        self.assertIn('href="/jobs/"', html)
        self.assertIn('name="csrfmiddlewaretoken"', html)

    def test_issue_form_warns_that_the_submission_is_anonymous(self):
        html = self._render(JobCreateView, user=self.account2, puppet=self.char2, job_type="issue")
        self.assertIn("Anonymous submission:", html)
        self.assertIn("Issue details", html)

    def test_bug_form_renders(self):
        html = self._render(JobCreateView, user=self.account2, puppet=self.char2, job_type="bug")
        self.assertIn("Bug details", html)

    def test_comment_form_hides_the_staff_only_toggle_from_players(self):
        html = self._render(
            JobCommentCreateView, user=self.account2, puppet=self.char2, pk=self.job.pk
        )
        self.assertIn("Door is stuck", html)
        self.assertIn(f'href="/jobs/{self.job.pk}/"', html)
        self.assertNotIn("id_is_staff_only", html)

    def test_comment_form_offers_the_staff_only_toggle_to_staff(self):
        html = self._render(
            JobCommentCreateView, user=self.account, puppet=self.char1, pk=self.job.pk
        )
        self.assertIn("id_is_staff_only", html)
