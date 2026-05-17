# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Accessible base form classes for Django web authoring.

Every web form subclassing ``AccessibleModelForm`` (for Django model forms)
or ``AccessibleForm`` (for non-model forms) automatically:

- Applies Bootstrap 4 widget classes (``form-control``, ``form-check-input``).
- Sets ``aria-describedby`` on each widget to its error-region id and (if
  present) its help-text id, so the partial template at
  ``templates/evennia_accessibility/_form_field.html`` can always reference a
  stable, pre-existing error element — no JavaScript required.
- Leaves ``HiddenInput`` and ``MultipleHiddenInput`` widgets untouched.

Convention for stable ids (mirrors Django's default ``auto_id="id_%s"``)::

    field name: ``content``
    widget id:  ``id_content``
    error div:  ``id_content_errors``
    help div:   ``id_content_help``

For forms with a prefix (e.g. formsets), ids become ``id_{prefix}-{name}_*``.
"""

from django import forms


class _AccessibleWidgetMixin:
    """Internal mixin that adds Bootstrap widget attrs after __init__."""

    def _add_widget_attrs(self):
        for name, field in self.fields.items():
            widget = field.widget

            # Skip hidden inputs — they render no visible element.
            if isinstance(widget, forms.HiddenInput | forms.MultipleHiddenInput):
                continue

            # Stable ids matching Django's default auto_id pattern.
            html_name = f"{self.prefix}-{name}" if self.prefix else name
            error_id = f"id_{html_name}_errors"
            help_id = f"id_{html_name}_help"

            # aria-describedby: always include the error region; add help if present.
            described_parts = [error_id]
            if field.help_text:
                described_parts.append(help_id)
            widget.attrs["aria-describedby"] = " ".join(described_parts)

            # Bootstrap widget classes.
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
                # Reasonable default height; individual forms can override.
                widget.attrs.setdefault("rows", "6")
            else:
                if "form-control" not in existing_cls:
                    widget.attrs["class"] = f"{existing_cls} form-control".strip()


class AccessibleForm(_AccessibleWidgetMixin, forms.Form):
    """Base class for non-model accessible forms.

    Subclass this for forms that don't map 1:1 to a Django model (e.g.,
    search filters, preference lists).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_widget_attrs()


class AccessibleModelForm(_AccessibleWidgetMixin, forms.ModelForm):
    """Base class for model-backed accessible forms.

    Subclass this for forms that create or edit a Django model instance.
    Adopting games should consider routing saves through a model factory
    classmethod (rather than calling ``form.save()`` directly in views) so
    domain signals fire consistently.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_widget_attrs()
