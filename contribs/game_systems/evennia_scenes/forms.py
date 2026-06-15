# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Forms for evennia_scenes web views.

Requires the [web] extra (evennia-accessibility). Falls back to a plain
Django ModelForm when evennia-accessibility is not installed so that the
models are importable even without the [web] extra.
"""

from django import forms

try:
    from evennia_accessibility.forms import AccessibleModelForm as _BaseModelForm
except ImportError:
    from django.forms import ModelForm as _BaseModelForm

from evennia_scenes.models import LogEntry


class LogEntryEditForm(_BaseModelForm):
    """Edit a log entry's content via the web viewer.

    Only the content field is editable via the web form. author and log_type
    are set by the view and are not exposed here.
    """

    class Meta:
        model = LogEntry
        fields = ["content"]  # noqa: RUF012
        widgets = {  # noqa: RUF012
            "content": forms.Textarea(attrs={"rows": "10"}),
        }

    def clean_content(self):
        content = self.cleaned_data.get("content", "").strip()
        if not content:
            raise forms.ValidationError("Log entry content cannot be empty.")
        return content
