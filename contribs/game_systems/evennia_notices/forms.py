# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Closed source preference choices."""

from django import forms

from evennia_links.notices import source_registry


class PreferenceForm(forms.Form):
    """Account-wide routine choice; decisions survive off in summaries."""

    source = forms.ChoiceField(label="Source")
    mode = forms.ChoiceField(
        label="Routine alerts", choices=[(x, x.title()) for x in ("immediate", "summary", "off")]
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source"].choices = [
            (slug, source.label) for slug, source in source_registry().items()
        ]
