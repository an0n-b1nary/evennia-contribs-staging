# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Web submission, revision and explicit staff review of structured requests."""

from django import forms
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import FormView
from evennia.objects.models import ObjectDB

from evennia_jobs.authoring import AuthoringMixin
from evennia_jobs.forms import RequestReviewForm, StructuredRequestForm
from evennia_jobs.models import Job, JobStatus
from evennia_jobs.permissions import is_staff_user
from evennia_jobs.requests import get_request_form
from evennia_jobs.review import review_request, submit_request, withdraw_request


class StructuredRequestView(AuthoringMixin, FormView):
    """Submit an enabled form, or revise one's own request after staff ask for changes."""

    form_class = StructuredRequestForm
    template_name = "evennia_jobs/structured_request_form.html"

    def get_permission_target(self):
        """Resolve a revision's ticket without accepting a form key from the client."""
        if not hasattr(self, "job"):
            self.job = get_object_or_404(Job, pk=self.kwargs["pk"]) if "pk" in self.kwargs else None
        return self.job

    def check_permission(self, character_id, target):
        """Only the original submitter may revise an existing ticket."""
        self.latest = target.submissions.last() if target else None
        if target and target.author_id != character_id:
            raise PermissionDenied
        if target and (
            not self.latest or target.status == JobStatus.CLOSED or not self.latest.can_revise
        ):
            raise PermissionDenied("This request is not awaiting revision.")

    def get_schema(self):
        """Resolve current enabled configuration, keeping disabled forms inaccessible."""
        key = self.latest.form_key if self.latest else self.kwargs["form_key"]
        try:
            return key, get_request_form(key)
        except ValidationError as exc:
            raise Http404("That request form is unavailable.") from exc

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["schema"] = self.get_schema()[1]
        kwargs["locked_title"] = self.job.title if self.job else None
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        key, schema = self.get_schema()
        initial["schema_token"] = signing.dumps({"key": key, "schema": schema}, salt="jobs-request")
        if self.latest:
            initial["title"] = self.job.title
            initial["revision"] = self.latest.revision
            for question in schema["questions"]:
                if question["type"] != "boolean":
                    initial[f"answer_{question['key']}"] = self.latest.answers.get(
                        question["key"], ""
                    )
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        schema = self.get_schema()[1]
        context.update(
            page_title=schema["label"],
            description=schema["description"],
            form_action=self.request.path,
            job=self.job,
        )
        return context

    def form_valid(self, form):
        key, schema = self.get_schema()
        try:
            saved = signing.loads(form.cleaned_data["schema_token"], salt="jobs-request")
            if saved != {"key": key, "schema": schema}:
                raise ValidationError("This form has changed. Reload it before submitting.")
            submission = submit_request(
                author=get_object_or_404(ObjectDB, pk=self.get_character()),
                form_key=key,
                title=form.cleaned_data["title"],
                answers=form.cleaned_data["answers"],
                job=self.job,
                expected_revision=form.cleaned_data.get("revision"),
            )
        except signing.BadSignature:
            form.add_error(None, "This form has changed. Reload it before submitting.")
            return self.form_invalid(form)
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
            return self.form_invalid(form)
        return HttpResponseRedirect(reverse("job-detail", kwargs={"pk": submission.job_id}))


class RequestReviewView(AuthoringMixin, FormView):
    """Review the current revision through the same service as +jobs."""

    form_class = RequestReviewForm
    template_name = "evennia_jobs/request_review_form.html"

    def get_permission_target(self):
        self.job = get_object_or_404(Job, pk=self.kwargs["pk"])
        return self.job

    def check_permission(self, character_id, target):
        if not is_staff_user(self.request):
            raise PermissionDenied
        self.latest = target.submissions.last()
        if not self.latest:
            raise Http404("This ticket has no structured submission.")

    def get_initial(self):
        return {"revision": self.latest.revision}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["schema"] = self.latest.schema
        kwargs["viewer"] = get_object_or_404(ObjectDB, pk=self.get_character())
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            page_title=f"Review ticket #{self.job.job_number}",
            job=self.job,
            submission=self.latest,
            form_action=self.request.path,
        )
        from evennia_jobs.review import review_fields

        context["review_fields"] = review_fields(
            self.latest, get_object_or_404(ObjectDB, pk=self.get_character())
        )
        return context

    def form_valid(self, form):
        try:
            review_request(
                job=self.job,
                reviewer=get_object_or_404(ObjectDB, pk=self.get_character()),
                outcome=form.cleaned_data["outcome"],
                reason=form.cleaned_data["reason"],
                expected_revision=form.cleaned_data["revision"],
                review_options={
                    key: value
                    for key, value in form.cleaned_data.items()
                    if key not in {"revision", "outcome", "reason"}
                },
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
            return self.form_invalid(form)
        return HttpResponseRedirect(reverse("job-detail", kwargs={"pk": self.job.pk}))


class WithdrawalForm(forms.Form):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    reason = forms.CharField(required=False, max_length=10000, widget=forms.Textarea)


class RequestWithdrawView(AuthoringMixin, FormView):
    form_class = WithdrawalForm
    template_name = "evennia_jobs/request_withdraw_form.html"

    def get_permission_target(self):
        self.job = get_object_or_404(Job, pk=self.kwargs["pk"])
        return self.job

    def check_permission(self, character_id, target):
        if target.author_id != character_id:
            raise PermissionDenied
        self.latest = target.submissions.last()
        if not self.latest:
            raise Http404

    def get_initial(self):
        return {"revision": self.latest.revision}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            page_title="Withdraw request",
            job=self.job,
            submission=self.latest,
            form_action=self.request.path,
        )
        return context

    def form_valid(self, form):
        try:
            withdraw_request(
                job=self.job,
                author=get_object_or_404(ObjectDB, pk=self.get_character()),
                expected_revision=form.cleaned_data["revision"],
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            form.add_error(None, "; ".join(exc.messages))
            return self.form_invalid(form)
        return HttpResponseRedirect(reverse("job-detail", kwargs={"pk": self.job.pk}))
