# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Django forms for evennia_jobs.

Requires the [web] optional-dependency set (evennia-accessibility).
"""

from django import forms

from evennia_accessibility import AccessibleForm, AccessibleModelForm
from evennia_jobs.models import Job, RequestOutcome
from evennia_jobs.requests import clean_answer, clean_answers


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


class AcknowledgementWidget(forms.CheckboxInput):
    """Preserve the submitted value for shared yes/no validation."""

    def value_from_datadict(self, data, files, name):
        return data.get(name, False)


class RequestAnswerField(forms.Field):
    """Django field adapter for the core answer validator."""

    def __init__(self, question):
        self.question = question
        kind = question["type"]
        if kind == "boolean":
            widget = AcknowledgementWidget()
        elif kind == "choice":
            widget = forms.Select(
                choices=[("", "Choose an answer"), *[(v, v) for v in question["choices"]]]
            )
        elif kind == "longtext":
            widget = forms.Textarea(attrs={"rows": 4, "maxlength": question["max_length"]})
        else:
            widget = forms.TextInput(attrs={"maxlength": question["max_length"]})
        super().__init__(
            label=question["label"],
            help_text=question["help_text"],
            required=question["required"],
            widget=widget,
        )

    def to_python(self, value):
        return clean_answer(self.question, value)


class StructuredRequestForm(AccessibleForm):
    """Accessible fields built from the same schema used by the command questionnaire."""

    title = forms.CharField(max_length=255)
    schema_token = forms.CharField(widget=forms.HiddenInput)
    revision = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, schema, locked_title=None, **kwargs):
        self.schema = schema
        super().__init__(*args, **kwargs)
        if locked_title is not None:
            self.fields["title"].disabled = True
            self.fields["title"].initial = locked_title
        for question in schema["questions"]:
            self.fields[f"answer_{question['key']}"] = RequestAnswerField(question)
        # The base form ran before these dynamic fields existed.
        self._add_widget_attrs()

    def clean(self):
        """Use the shared validator after field-level HTML form validation."""
        data = super().clean()
        if not self.errors:
            answers = {q["key"]: data[f"answer_{q['key']}"] for q in self.schema["questions"]}
            data["answers"] = clean_answers(self.schema, answers)
        return data


class RequestReviewForm(AccessibleForm):
    """An explicit staff decision with a stale-review guard."""

    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    outcome = forms.ChoiceField(choices=RequestOutcome.choices)
    reason = forms.CharField(label="Explanation", max_length=10000, widget=forms.Textarea)
