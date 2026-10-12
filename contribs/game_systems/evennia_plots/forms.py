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
    """Create a new plot."""

    class Meta:
        model = PlotThread
        fields = ["name", "description", "privacy", "thread_policy"]  # noqa: RUF012
        labels = {"thread_policy": "Who may add threads"}  # noqa: RUF012


class PlotThreadEditForm(AccessibleModelForm):
    """Edit the name, description, privacy or thread policy of a plot."""

    class Meta:
        model = PlotThread
        fields = ["name", "description", "privacy", "thread_policy"]  # noqa: RUF012
        labels = {"thread_policy": "Who may add threads"}  # noqa: RUF012


class StoryThreadForm(AccessibleForm):
    """Add a thread to a plot, or request one."""

    title = forms.CharField(
        max_length=200,
        label="Thread",
        help_text='A question, problem or lead, e.g. "Why do the wells run red?"',
    )
    detail = forms.CharField(
        max_length=500,
        required=False,
        label="Detail (OOC, optional)",
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class StoryThreadResolveForm(AccessibleForm):
    """Resolve a thread, optionally revealing its sealed answer."""

    summary = forms.CharField(
        max_length=1000,
        label="How it resolved (OOC)",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    reveal = forms.BooleanField(
        required=False,
        label="Reveal the planned answer",
        help_text="Shows the sealed answer, and its earlier wordings, to everyone who can see the plot.",
    )


class SealedAnswerForm(AccessibleForm):
    """Write, replace or clear a thread's sealed answer."""

    answer = forms.CharField(
        required=False,
        label="Sealed answer",
        help_text="Only the plot's owners and staff can read it until it is revealed. "
        "Leave empty to clear it.",
        widget=forms.Textarea(attrs={"rows": 5}),
    )


class StoryThreadCarryForm(AccessibleForm):
    """Carry a loose end into a sequel plot."""

    target = forms.TypedChoiceField(coerce=int, label="Sequel plot")

    def __init__(self, *args, targets=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target"].choices = [(p.pk, f"#{p.plot_number} {p.name}") for p in targets]


class PlotOwnerForm(AccessibleForm):
    """Add or remove one of a plot's owners."""

    ACTION_ADD = "add"
    ACTION_REMOVE = "remove"
    ACTION_CHOICES = [  # noqa: RUF012
        (ACTION_ADD, "Add owner"),
        (ACTION_REMOVE, "Remove owner"),
    ]

    character_name = forms.CharField(
        max_length=255,
        label="Character name",
        widget=forms.TextInput(attrs={"placeholder": "Character name"}),
    )
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.RadioSelect,
        initial=ACTION_ADD,
    )


class PlotInviteForm(AccessibleForm):
    """Invite or remove a character from an invite-only plot."""

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
