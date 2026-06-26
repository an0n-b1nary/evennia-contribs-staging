# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Forms for evennia_calendar web views. Requires [web] extra.

Base classes apply Bootstrap 4 widget classes and ARIA attributes
automatically. All forms are safe to instantiate from templates.
"""

from django import forms
from django.utils import timezone as tz

from evennia_calendar.models import (
    CalendarEvent,
    ClusterRSVP,
    EventCluster,
    EventTag,
)


class _CalendarWidgetMixin:
    """Add Bootstrap widget attrs and aria-describedby after __init__."""

    def _add_widget_attrs(self):
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.HiddenInput | forms.MultipleHiddenInput):
                continue
            html_name = f"{self.prefix}-{name}" if self.prefix else name
            error_id = f"id_{html_name}_errors"
            help_id = f"id_{html_name}_help"
            described_parts = [error_id]
            if field.help_text:
                described_parts.append(help_id)
            widget.attrs["aria-describedby"] = " ".join(described_parts)
            existing_cls = widget.attrs.get("class", "")
            if isinstance(widget, forms.CheckboxInput):
                if "form-check-input" not in existing_cls:
                    widget.attrs["class"] = f"{existing_cls} form-check-input".strip()
            elif isinstance(widget, forms.Select):
                if "form-control" not in existing_cls:
                    widget.attrs["class"] = f"{existing_cls} form-control".strip()
            elif isinstance(widget, forms.Textarea):
                if "form-control" not in existing_cls:
                    widget.attrs["class"] = f"{existing_cls} form-control".strip()
                widget.attrs.setdefault("rows", "6")
            else:
                if "form-control" not in existing_cls:
                    widget.attrs["class"] = f"{existing_cls} form-control".strip()


class AccessibleForm(_CalendarWidgetMixin, forms.Form):
    """Base non-model form with Bootstrap widgets and ARIA annotations."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_widget_attrs()


class AccessibleModelForm(_CalendarWidgetMixin, forms.ModelForm):
    """Base model form with Bootstrap widgets and ARIA annotations."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_widget_attrs()


# ---------------------------------------------------------------------------
# Calendar forms
# ---------------------------------------------------------------------------


class ClusterRSVPForm(AccessibleForm):
    """Ranked-choice RSVP preference form for an EventCluster.

    Pass ``cluster`` (required) and optionally ``character_id`` so the form
    can validate the character's current RSVP eligibility.

    The ``preferences`` field is a TypedMultipleChoiceField whose choices are
    built from the cluster's non-cancelled member events. Checkboxes are
    rendered manually in the template so each row can show event metadata.
    """

    preferences = forms.TypedMultipleChoiceField(
        choices=[],
        coerce=int,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Event preferences",
        help_text=(
            "Check the events you want to attend. "
            "The order you submit them is treated as rank 1, 2, 3, …"
        ),
    )

    def __init__(self, *args, cluster, character_id=None, **kwargs):
        self.cluster = cluster
        self.character_id = character_id
        super().__init__(*args, **kwargs)
        member_events = cluster.events.filter(is_cancelled=False).order_by("scheduled_time")
        self.fields["preferences"].choices = [(ev.pk, ev.title) for ev in member_events]

    def clean_preferences(self):
        preferences = self.cleaned_data.get("preferences") or []
        if not preferences:
            raise forms.ValidationError("Please select at least one event preference.")
        return preferences

    def clean(self):
        cleaned = super().clean()
        if not self.cluster.is_locked:
            raise forms.ValidationError("This cluster is not yet open for RSVPs.")
        if self.cluster.has_run:
            raise forms.ValidationError("The draw for this cluster has already run.")
        preferences = cleaned.get("preferences") or []
        if preferences and self.character_id:
            try:
                crsvp = ClusterRSVP.objects.get(
                    cluster=self.cluster, character_id=self.character_id
                )
                if crsvp.status != ClusterRSVP.Status.PENDING:
                    raise forms.ValidationError("Your RSVP status can no longer be changed.")
            except ClusterRSVP.DoesNotExist:
                pass
        return cleaned


class CalendarEventForm(AccessibleModelForm):
    """Form for creating or editing a CalendarEvent.

    Pass ``is_staff=True`` when the requesting user has Builder+ permissions.
    Non-staff callers have the ``is_staff_event`` field removed entirely;
    ``clean_is_staff_event`` provides a defence-in-depth server rejection if
    the field is smuggled in via a crafted POST.
    """

    class Meta:
        model = CalendarEvent
        fields = [  # noqa: RUF012
            "title",
            "description",
            "scheduled_time",
            "participant_cap",
            "emphasis",
            "is_staff_event",
        ]
        widgets = {  # noqa: RUF012
            "description": forms.Textarea(attrs={"rows": "6"}),
            "scheduled_time": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }
        help_texts = {  # noqa: RUF012
            "scheduled_time": "All times are UTC. Your browser will display local time on the event page.",
            "participant_cap": "Leave blank for an unlimited open event.",
            "is_staff_event": (
                "Staff events use lottery RSVP mode. Pre-inviting participants "
                "is disabled on staff events (anti-favouritism)."
            ),
        }

    def __init__(self, *args, is_staff=False, **kwargs):
        self._is_staff = is_staff
        super().__init__(*args, **kwargs)
        if not is_staff:
            self.fields.pop("is_staff_event", None)
        self.fields["scheduled_time"].input_formats = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
        ]

    def clean_is_staff_event(self):
        value = self.cleaned_data.get("is_staff_event", False)
        if value and not self._is_staff:
            raise forms.ValidationError("Only Builder+ accounts may set the staff event flag.")
        return value

    def clean_scheduled_time(self):
        dt = self.cleaned_data.get("scheduled_time")
        if dt is None:
            return dt
        if tz.is_naive(dt):
            dt = tz.make_aware(dt, tz.utc)
        return dt


class CalendarEventEditForm(CalendarEventForm):
    """Edit form for an existing CalendarEvent. Identical to the create form."""

    pass


class EventInviteForm(AccessibleForm):
    """Invite a character to a non-staff CalendarEvent by name."""

    character_name = forms.CharField(
        max_length=255,
        label="Character name",
        help_text="Enter the exact character name to invite.",
    )


class EventTagForm(AccessibleForm):
    """Add or remove a thematic tag on an existing CalendarEvent."""

    tag_name = forms.CharField(
        max_length=60,
        label="Tag name",
        help_text="Enter the exact tag name to add or remove.",
    )
    action = forms.ChoiceField(
        choices=[("add", "Add tag"), ("remove", "Remove tag")],
        label="Action",
        widget=forms.RadioSelect,
    )


class EventTagCreateForm(AccessibleModelForm):
    """Staff-only: create a new canonical EventTag.

    Tag creation is intentionally staff-gated to prevent freeform name drift
    (e.g. "Arcane" / "arcane" / "Magic" / "magical"). Case-insensitive
    uniqueness is enforced in ``clean_name``.
    """

    class Meta:
        model = EventTag
        fields = ["name", "description"]  # noqa: RUF012
        widgets = {"description": forms.Textarea(attrs={"rows": "3"})}  # noqa: RUF012
        help_texts = {  # noqa: RUF012
            "name": "Canonical tag name. Must be unique (case-insensitive).",
            "description": "Optional explanation of when to apply this tag.",
        }

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Tag name cannot be empty.")
        if EventTag.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError(f"A tag named '{name}' already exists (case-insensitive).")
        return name


class EventClusterForm(AccessibleModelForm):
    """Form for creating or editing an EventCluster."""

    class Meta:
        model = EventCluster
        fields = ["title", "description", "is_locked"]  # noqa: RUF012
        widgets = {"description": forms.Textarea(attrs={"rows": "4"})}  # noqa: RUF012
        help_texts = {  # noqa: RUF012
            "is_locked": (
                "Once locked, no events can be added or removed. "
                "The lottery draw arms automatically."
            ),
        }

    def clean_is_locked(self):
        value = self.cleaned_data.get("is_locked", False)
        if self.instance and self.instance.pk and not value and self.instance.has_run:
            raise forms.ValidationError("Cannot unlock a cluster whose lottery has already run.")
        return value


class EventClusterMembershipForm(AccessibleForm):
    """Add or remove a CalendarEvent from an EventCluster by event ID."""

    event_id = forms.IntegerField(
        label="Event ID",
        help_text="Enter the numeric ID of the event to add or remove.",
        widget=forms.NumberInput(attrs={"min": "1"}),
    )
    action = forms.ChoiceField(
        choices=[("add", "Add event"), ("remove", "Remove event")],
        label="Action",
        widget=forms.RadioSelect,
    )


class ExclusionForm(AccessibleForm):
    """Add or remove a mutual-exclusion pair between two CalendarEvents."""

    other_event_id = forms.IntegerField(
        label="Other event ID",
        help_text="Enter the numeric ID of the event to link as mutually exclusive.",
        widget=forms.NumberInput(attrs={"min": "1"}),
    )
    action = forms.ChoiceField(
        choices=[("add", "Add exclusion"), ("remove", "Remove exclusion")],
        label="Action",
        widget=forms.RadioSelect,
    )
