# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django forms for evennia_lore. Requires the [web] extra (evennia-accessibility)."""

from django import forms

from evennia_accessibility import AccessibleForm, AccessibleModelForm
from evennia_lore.models import LoreEntry

_LEAN_TYPE_CHOICES = [
    ("", "— No lean (clear) —"),
    ("theme", "Theme (major tag)"),
    ("tag", "Tag"),
    ("region", "Region"),
    ("entry", "Entry # (number)"),
    ("plot", "Plot thread (name)"),
]


class LoreEntryCreateForm(AccessibleModelForm):
    """Form for submitting a new lore entry."""

    class Meta:
        model = LoreEntry
        fields = ["title", "body", "summary", "privacy"]  # noqa: RUF012
        widgets = {  # noqa: RUF012
            "body": forms.Textarea(attrs={"rows": "14"}),
            "summary": forms.Textarea(attrs={"rows": "3"}),
        }
        help_texts = {  # noqa: RUF012
            "title": "Entry title (must be unique among published entries).",
            "body": "Full article body.",
            "summary": "Short teaser shown in listings (max 500 chars).",
            "privacy": (
                "Public: visible to all and eligible for passive trickle. "
                "Restricted: stub with summary only; full body requires storyteller +share."
            ),
        }

    def clean_title(self):
        title = self.cleaned_data.get("title", "").strip()
        if not title:
            raise forms.ValidationError("Title cannot be empty.")
        if LoreEntry.objects.filter(
            title__iexact=title, status=LoreEntry.Status.PUBLISHED
        ).exists():
            raise forms.ValidationError("A published entry with this title already exists.")
        return title

    def clean_summary(self):
        return self.cleaned_data.get("summary", "").strip()


class LoreEntryEditForm(AccessibleModelForm):
    """Form for editing an existing lore entry (excludes current instance from title uniqueness)."""

    class Meta:
        model = LoreEntry
        fields = ["title", "body", "summary", "privacy"]  # noqa: RUF012
        widgets = {  # noqa: RUF012
            "body": forms.Textarea(attrs={"rows": "14"}),
            "summary": forms.Textarea(attrs={"rows": "3"}),
        }
        help_texts = {  # noqa: RUF012
            "title": "Entry title.",
            "body": "Full article body.",
            "summary": "Short teaser (max 500 chars).",
            "privacy": "Public or Restricted.",
        }

    def clean_title(self):
        title = self.cleaned_data.get("title", "").strip()
        if not title:
            raise forms.ValidationError("Title cannot be empty.")
        qs = LoreEntry.objects.filter(title__iexact=title, status=LoreEntry.Status.PUBLISHED)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A published entry with this title already exists.")
        return title

    def clean_summary(self):
        return self.cleaned_data.get("summary", "").strip()


class LoreLeanForm(AccessibleForm):
    """Form for setting or clearing a character's lore investigation lean."""

    lean_type = forms.ChoiceField(
        choices=_LEAN_TYPE_CHOICES,
        required=False,
        label="Investigation type",
    )
    lean_value = forms.CharField(
        max_length=255,
        required=False,
        label="Value",
        help_text="Name, ID, or keyword matching the lean type.",
    )

    def clean(self):
        cleaned = super().clean()
        lean_type = cleaned.get("lean_type", "")
        lean_value = cleaned.get("lean_value", "").strip()
        if lean_type and not lean_value:
            raise forms.ValidationError("A value is required when setting a lean type.")
        cleaned["lean_value"] = lean_value
        return cleaned
