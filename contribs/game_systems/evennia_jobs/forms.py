# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Django forms for evennia_jobs.

Requires the [web] optional-dependency set (evennia-accessibility).
"""

from django import forms

from evennia_accessibility import AccessibleForm, AccessibleModelForm
from evennia_jobs.models import Job


class JobCreateForm(AccessibleModelForm):
    """Form for submitting a new staff ticket (request, bug, or issue).

    The ``job_type`` is supplied by the URL, not the form.
    """

    class Meta:
        model = Job
        fields = ["title", "description"]  # noqa: RUF012
        widgets = {  # noqa: RUF012
            "description": forms.Textarea(attrs={"rows": "8"}),
        }
        help_texts = {  # noqa: RUF012
            "title": "Brief summary of your request (max 255 characters).",
            "description": "Full details. Be as specific as possible.",
        }

    def clean_title(self):
        title = self.cleaned_data.get("title", "").strip()
        if not title:
            raise forms.ValidationError("Title cannot be empty.")
        return title

    def clean_description(self):
        desc = self.cleaned_data.get("description", "").strip()
        if not desc:
            raise forms.ValidationError("Description cannot be empty.")
        return desc


class JobCommentForm(AccessibleForm):
    """Form for appending a comment to a ticket.

    Pass ``is_staff=True`` to show the ``is_staff_only`` checkbox; non-staff
    callers have the field removed entirely so it cannot be smuggled via POST.
    """

    content = forms.CharField(
        widget=forms.Textarea(attrs={"rows": "5"}),
        label="Comment",
    )
    is_staff_only = forms.BooleanField(
        required=False,
        label="Staff-only note",
        help_text="Hide this comment from the ticket submitter.",
    )

    def __init__(self, *args, is_staff=False, **kwargs):
        self._is_staff = is_staff
        super().__init__(*args, **kwargs)
        if not is_staff:
            self.fields.pop("is_staff_only", None)

    def clean_content(self):
        content = self.cleaned_data.get("content", "").strip()
        if not content:
            raise forms.ValidationError("Comment cannot be empty.")
        return content
