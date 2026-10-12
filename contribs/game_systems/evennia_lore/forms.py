# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django forms for evennia_lore. Requires the [web] extra (evennia-accessibility)."""

from django import forms

from evennia_accessibility import AccessibleForm, AccessibleModelForm
from evennia_lore import layers
from evennia_lore.layers import LoreLayerError
from evennia_lore.models import LoreEntry

_KIND_HELP = (
    "How the world treats the content. A Fact is so, as far as anyone can tell. "
    "A Rumor is a claim going around now. A Legend is an old story nobody living can check."
)
_ACCURACY_HELP = (
    "Whether the IC content is true. Facts are always accurate. Inaccurate and partly "
    "accurate entries need OOC notes saying what's true. Open means not decided yet."
)
_OOC_HELP = (
    "What players should know about the IC content: where a rumor came from, what's "
    "actually true. OOC notes must never be false."
)


def _kind_choices():
    return list(layers.kinds().items())


def _new_accuracy_choices():
    return [("", "Default: accurate for a Fact, open otherwise"), *layers.ACCURACY_CHOICES]


class _LayerFieldsMixin:
    """Validates kind, accuracy and OOC notes together (see evennia_lore.layers)."""

    def clean(self):
        cleaned = super().clean()
        instance = self.instance if self.instance and self.instance.pk else None
        kind = cleaned.get("kind") or (instance.kind if instance else layers.default_kind())
        accuracy = cleaned.get("accuracy") or layers.default_accuracy(kind)
        notes = cleaned.get("ooc_notes", "") or ""
        try:
            layers.validate(
                kind,
                accuracy,
                notes,
                instance.sealed_notes if instance else "",
                check_kind=instance is None or kind != instance.kind,
            )
        except LoreLayerError as err:
            raise forms.ValidationError(str(err)) from err
        cleaned["kind"] = kind
        cleaned["accuracy"] = accuracy
        cleaned["ooc_notes"] = notes.strip()
        return cleaned


_LEAN_TYPE_CHOICES = [
    ("", "— No lean (clear) —"),
    ("theme", "Theme (major tag)"),
    ("tag", "Tag"),
    ("region", "Region"),
    ("entry", "Entry # (number)"),
    ("plot", "Plot (number or name)"),
]


class LoreEntryCreateForm(_LayerFieldsMixin, AccessibleModelForm):
    """Form for submitting a new lore entry."""

    kind = forms.ChoiceField(choices=_kind_choices, label="Kind", help_text=_KIND_HELP)
    accuracy = forms.ChoiceField(
        choices=_new_accuracy_choices, required=False, label="Accuracy", help_text=_ACCURACY_HELP
    )

    class Meta:
        model = LoreEntry
        fields = ["title", "kind", "body", "accuracy", "ooc_notes", "summary", "privacy"]  # noqa: RUF012
        widgets = {  # noqa: RUF012
            "body": forms.Textarea(attrs={"rows": "14"}),
            "ooc_notes": forms.Textarea(attrs={"rows": "6"}),
            "summary": forms.Textarea(attrs={"rows": "3"}),
        }
        labels = {"body": "IC content", "ooc_notes": "OOC notes"}  # noqa: RUF012
        help_texts = {  # noqa: RUF012
            "title": "Entry title (must be unique among published entries).",
            "body": "What characters can know, read and repeat. It may be false.",
            "ooc_notes": _OOC_HELP,
            "summary": "Short teaser shown in listings (max 500 chars).",
            "privacy": (
                "Public: visible to all and eligible for passive trickle. "
                "Restricted: stub with summary only; full body requires storyteller +share."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault("kind", layers.default_kind())

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


class LoreEntryEditForm(_LayerFieldsMixin, AccessibleModelForm):
    """Form for editing an existing lore entry (excludes current instance from title uniqueness)."""

    kind = forms.ChoiceField(choices=_kind_choices, label="Kind", help_text=_KIND_HELP)
    accuracy = forms.ChoiceField(
        choices=layers.ACCURACY_CHOICES, label="Accuracy", help_text=_ACCURACY_HELP
    )

    class Meta:
        model = LoreEntry
        fields = ["title", "kind", "body", "accuracy", "ooc_notes", "summary", "privacy"]  # noqa: RUF012
        widgets = {  # noqa: RUF012
            "body": forms.Textarea(attrs={"rows": "14"}),
            "ooc_notes": forms.Textarea(attrs={"rows": "6"}),
            "summary": forms.Textarea(attrs={"rows": "3"}),
        }
        labels = {"body": "IC content", "ooc_notes": "OOC notes"}  # noqa: RUF012
        help_texts = {  # noqa: RUF012
            "title": "Entry title.",
            "body": "What characters can know, read and repeat. It may be false.",
            "ooc_notes": _OOC_HELP,
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # An entry may keep a kind the game has since removed; offer it so the
        # form can be saved without changing it.
        current = getattr(self.instance, "kind", None)
        if current and current not in layers.kinds():
            self.fields["kind"].choices = [
                *_kind_choices(),
                (current, f"{layers.kind_label(current)} (no longer offered)"),
            ]


class LoreAffirmationDeclineForm(AccessibleForm):
    """Staff note to the author when declining to affirm an entry."""

    note = forms.CharField(
        max_length=500,
        label="Note to the author",
        help_text="Only the author and staff see this. Say what would change your mind.",
        widget=forms.Textarea(attrs={"rows": "3"}),
    )

    def clean_note(self):
        note = self.cleaned_data.get("note", "").strip()
        if not note:
            raise forms.ValidationError("Say why, so the author knows what to change.")
        return note


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
