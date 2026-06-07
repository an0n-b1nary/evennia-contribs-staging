# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Forms for evennia_boards web views.

Requires the [web] extra (evennia-accessibility). Falls back to a plain
Django ModelForm when evennia-accessibility is not installed so that the
models are importable even without the [web] extra.
"""

from django import forms

try:
    from evennia_accessibility.forms import AccessibleModelForm as _BaseModelForm
except ImportError:
    from django.forms import ModelForm as _BaseModelForm

from evennia_boards.models import Post


class PostForm(_BaseModelForm):
    """Create a new board post or reply.

    parent_post (for replies) is set by the view from the URL kwargs, not
    by this form.
    """

    class Meta:
        model = Post
        fields = ["title", "content"]  # noqa: RUF012
        widgets = {  # noqa: RUF012
            "content": forms.Textarea(attrs={"rows": "10"}),
        }

    def clean_content(self):
        content = self.cleaned_data.get("content", "").strip()
        if not content:
            raise forms.ValidationError("Post content cannot be empty.")
        return content


class PostEditForm(PostForm):
    """Edit an existing board post.

    Identical field set to PostForm; kept separate for future extensibility.
    Requires ``instance=<post>`` to pre-populate on GET.
    """
