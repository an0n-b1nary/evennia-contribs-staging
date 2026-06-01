# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Website views for evennia_jobs.

Read-only views (login required):
    /jobs/          JobListView   — submitter's own + assigned-to-me
    /jobs/all/      JobAllView    — full queue (staff only, 403 otherwise)
    /jobs/<pk>/     JobDetailView — single ticket with comment thread

Authoring views (login + active puppet required):
    /jobs/new/<job_type>/  JobCreateView         — submit request / bug / issue
    /jobs/<pk>/comment/    JobCommentCreateView   — append a comment

Visibility rules:
- Submitter sees their own non-discuss tickets.
- Assignee sees tickets assigned to them.
- Staff (JOBS_STAFF_LOCK permission) sees all tickets, including +discuss.
- ISSUE tickets hide the reporter name for non-staff viewers.

Wire into your URL config::

    from django.urls import include, path
    urlpatterns += [path("jobs/", include("evennia_jobs.urls"))]

Requires the [web] optional-dependency set (evennia-accessibility).
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import DetailView, FormView, ListView
from evennia.objects.models import ObjectDB

from evennia_jobs.authoring import AuthoringMixin
from evennia_jobs.forms import JobCommentForm, JobCreateForm
from evennia_jobs.models import Job, JobComment, JobStatus, JobType
from evennia_jobs.permissions import get_character_id, is_staff_user

_VALID_JOB_TYPES = frozenset({JobType.REQUEST.value, JobType.BUG.value, JobType.ISSUE.value})


class JobListView(LoginRequiredMixin, ListView):
    """A player's own open tickets plus any tickets assigned to them."""

    model = Job
    template_name = "evennia_jobs/job_list.html"
    context_object_name = "jobs"
    paginate_by = 25
    login_url = "/accounts/login/"

    def get_queryset(self):
        user = self.request.user
        staff = is_staff_user(self.request)
        character_id = get_character_id(user)

        if staff:
            qs = Job.objects.exclude(status=JobStatus.CLOSED)
        else:
            if character_id:
                qs = (
                    Job.objects.filter(Q(author_id=character_id) | Q(assignee_id=character_id))
                    .exclude(status=JobStatus.CLOSED)
                    .exclude(job_type=JobType.DISCUSS)
                )
            else:
                qs = Job.objects.none()

        pks = qs.values_list("pk", flat=True)
        return Job.objects.by_priority().filter(pk__in=pks).select_related()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "My Tickets"
        context["is_staff"] = is_staff_user(self.request)
        context["show_all"] = False
        return context


class JobAllView(LoginRequiredMixin, ListView):
    """Full ticket queue — staff only."""

    model = Job
    template_name = "evennia_jobs/job_list.html"
    context_object_name = "jobs"
    paginate_by = 25
    login_url = "/accounts/login/"

    def get(self, request, *args, **kwargs):
        if not is_staff_user(request):
            raise PermissionDenied
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return Job.objects.by_priority().exclude(status=JobStatus.CLOSED)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Ticket Queue"
        context["is_staff"] = True
        context["show_all"] = True
        return context


class JobDetailView(LoginRequiredMixin, DetailView):
    """Single ticket with comment thread."""

    model = Job
    template_name = "evennia_jobs/job_detail.html"
    context_object_name = "job"
    login_url = "/accounts/login/"

    def get_object(self, queryset=None):
        job = super().get_object(queryset)
        staff = is_staff_user(self.request)

        if staff:
            return job

        character_id = get_character_id(self.request.user)
        if not character_id:
            raise PermissionDenied

        if job.job_type == JobType.DISCUSS:
            raise PermissionDenied

        if job.author_id != character_id and job.assignee_id != character_id:
            raise PermissionDenied

        return job

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        job = self.object
        staff = is_staff_user(self.request)
        character_id = get_character_id(self.request.user)

        context["page_title"] = f"Ticket #{job.job_number}: {job.title}"
        context["is_staff"] = staff

        comments_qs = JobComment.objects.filter(job=job).order_by("created_at")
        if not staff:
            comments_qs = comments_qs.filter(is_staff_only=False)
        context["comments"] = comments_qs
        context["hide_reporter"] = job.job_type == JobType.ISSUE and not staff
        context["is_submitter"] = character_id is not None and job.author_id == character_id

        return context


_JOB_TYPE_LABELS = {
    JobType.REQUEST: "New Request",
    JobType.BUG: "Report Bug",
    JobType.ISSUE: "Report Issue",
}


class JobCreateView(AuthoringMixin, FormView):
    """Submit a new ticket. Any logged-in puppeted character may submit."""

    form_class = JobCreateForm
    template_name = "evennia_jobs/job_form.html"

    def _get_job_type(self):
        jt = self.kwargs.get("job_type", "")
        if jt not in _VALID_JOB_TYPES:
            raise Http404(f"Unknown job type: {jt!r}")
        return jt

    def check_permission(self, character_id, target):
        pass  # any puppet holder can submit

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        job_type = self._get_job_type()
        context["page_title"] = _JOB_TYPE_LABELS[job_type]
        context["job_type"] = job_type
        context["is_issue"] = job_type == JobType.ISSUE
        context["form_action"] = reverse("job-create", kwargs={"job_type": job_type})
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        character = get_object_or_404(ObjectDB, pk=character_id)
        job = Job.create_job(
            job_type=self._get_job_type(),
            author=character,
            title=form.cleaned_data["title"],
            description=form.cleaned_data["description"],
        )
        return HttpResponseRedirect(reverse("job-detail", kwargs={"pk": job.pk}))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class JobCommentCreateView(AuthoringMixin, FormView):
    """Append a comment to a ticket."""

    form_class = JobCommentForm
    template_name = "evennia_jobs/job_comment_form.html"

    def _get_job(self):
        if not hasattr(self, "_job"):
            self._job = get_object_or_404(Job, pk=self.kwargs["pk"])
        return self._job

    def get_permission_target(self):
        return self._get_job()

    def check_permission(self, character_id, target):
        job = target
        if is_staff_user(self.request):
            return
        if job.author_id == character_id:
            return
        if job.assignee_id and job.assignee_id == character_id:
            return
        raise PermissionDenied

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["is_staff"] = is_staff_user(self.request)
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        job = self._get_job()
        context["page_title"] = f"Add Comment — Ticket #{job.job_number}"
        context["job"] = job
        context["form_action"] = reverse("job-comment", kwargs={"pk": job.pk})
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        character = get_object_or_404(ObjectDB, pk=character_id)
        job = self._get_job()
        is_staff_only = form.cleaned_data.get("is_staff_only", False)
        if is_staff_only and not is_staff_user(self.request):
            is_staff_only = False
        JobComment.create_comment(
            job=job,
            author=character,
            content=form.cleaned_data["content"],
            is_staff_only=is_staff_only,
        )
        return HttpResponseRedirect(reverse("job-detail", kwargs={"pk": job.pk}))

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))
