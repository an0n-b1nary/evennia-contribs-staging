# SPDX-License-Identifier: BSD-3-Clause
"""Optional website form extension; no Jobs web extra is imported at startup."""

from django.core.exceptions import PermissionDenied

from evennia_moderation.policy import require_staff


def add_review_fields(sender, *, form, schema, viewer, **kwargs):
    if schema.get("owner") != "moderation":
        return
    try:
        require_staff(viewer)
    except PermissionDenied:
        return
    from django import forms

    form.fields["share_decline_reason"] = forms.BooleanField(
        required=False,
        label="Share the decline reason with the referrer",
        help_text="Only used for a declined application. Leave unchecked to keep the reason private.",
    )
