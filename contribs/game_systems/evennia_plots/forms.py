# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Forms for the evennia_plots web layer.

Requires the ``[web]`` optional dependency group::

    pip install evennia-plots[web]

which includes ``evennia-accessibility``.  If ``evennia_accessibility`` is not
installed a plain Django base form is used as a fallback so that the module
still imports (useful for core-only testing).
"""

from django import forms

try:
    from evennia_accessibility import AccessibleForm, AccessibleModelForm
except ImportError:
    AccessibleForm = forms.Form
    AccessibleModelForm = forms.ModelForm

from evennia_plots.models import PlotArc, PlotTag, PlotThread, PlotUpdate


class PlotThreadCreateForm(AccessibleModelForm):
    """Create a new plot thread."""

    class Meta:
        model = PlotThread
        fields = ["name", "description", "privacy"]  # noqa: RUF012


class PlotThreadEditForm(AccessibleModelForm):
    """Edit the name, description, or privacy of a plot thread."""

    class Meta:
        model = PlotThread
        fields = ["name", "description", "privacy"]  # noqa: RUF012


class PlotInviteForm(AccessibleForm):
    """Invite or remove a character from a private plot thread."""

    ACTION_INVITE = "invite"
    ACTION_REMOVE = "remove"
    ACTION_CHOICES = [  # noqa: RUF012
        (ACTION_INVITE, "Invite"),
        (ACTION_REMOVE, "Remove"),
    ]

    character_name = forms.CharField(
        max_length=255,
        label="Character name",
        widget=forms.TextInput(attrs={"placeholder": "Character name"}),
    )
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.RadioSelect,
        initial=ACTION_INVITE,
    )


class PlotTagCreateForm(AccessibleModelForm):
    """Create a new major plot tag (staff only).

    Enforces case-insensitive uniqueness at the form level.
    """

    class Meta:
        model = PlotTag
        fields = ["name"]  # noqa: RUF012

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if (
            PlotTag.objects.filter(name__iexact=name)
            .exclude(pk=self.instance.pk if self.instance else None)
            .exists()
        ):
            raise forms.ValidationError("A tag with this name already exists.")
        return name


class PlotUpdateForm(AccessibleModelForm):
    """Append a new update (IC journal or OOC note) to a plot thread."""

    class Meta:
        model = PlotUpdate
        fields = ["content", "update_type"]  # noqa: RUF012


class PlotUpdateEditForm(AccessibleModelForm):
    """Edit an existing plot update (creates a PlotUpdateVersion snapshot)."""

    class Meta:
        model = PlotUpdate
        fields = ["content", "update_type"]  # noqa: RUF012


class PlotArcCreateForm(AccessibleModelForm):
    """Create a new plot arc (staff only)."""

    class Meta:
        model = PlotArc
        fields = ["name", "description", "arc_type"]  # noqa: RUF012


class PlotArcEditForm(AccessibleModelForm):
    """Edit an existing arc including XP multiplier overrides (staff only)."""

    class Meta:
        model = PlotArc
        fields = [  # noqa: RUF012
            "name",
            "description",
            "arc_type",
            "xp_mult_rp_session",
            "xp_mult_cutscene",
            "xp_mult_lore",
            "xp_mult_thread_bonus",
        ]
