# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Tests for evennia_accessibility — screen-reader helpers and accessible form bases.

Uses EvenniaTest which wires up the project settings (including
OPTIONS_ACCOUNT_DEFAULT) so account.options.set/get work correctly.

Objects available from EvenniaTest:
    self.char1 (key="Char"), self.char2 (key="Char2") — both in self.room1
    self.account, self.account2 — linked to char1/char2 respectively
"""

from unittest import mock

from django import forms
from evennia.utils.test_resources import EvenniaTest

from evennia_accessibility.accessibility import (
    describe_icon,
    describe_priority,
    plain_list,
    uses_screenreader,
)
from evennia_accessibility.forms import AccessibleForm, AccessibleModelForm


class TestUsesScreenreader(EvenniaTest):
    """Tests for uses_screenreader().

    These tests patch ``account.options.get`` rather than calling
    ``account.options.set`` so they don't require ``screenreader_mode`` to be
    pre-registered in the host game's ``OPTIONS_ACCOUNT_DEFAULT``. Adopting
    games still need to register the option for runtime ``.set()`` calls
    (see README) — but the contrib's own tests stay self-contained.
    """

    def test_default_is_false(self):
        """Screenreader mode is off by default."""
        self.assertFalse(uses_screenreader(self.char1))

    def test_enabled_via_account_option(self):
        """Returns True when the option resolves to True."""
        with mock.patch.object(self.account.options, "get", return_value=True):
            self.assertTrue(uses_screenreader(self.char1))

    def test_disabled_via_account_option(self):
        """Returns False when the option resolves to False."""
        with mock.patch.object(self.account.options, "get", return_value=False):
            self.assertFalse(uses_screenreader(self.char1))

    def test_with_account_directly(self):
        """Works when passed an Account instead of a Character."""
        with mock.patch.object(self.account.options, "get", return_value=True):
            self.assertTrue(uses_screenreader(self.account))

    def test_none_caller_returns_false(self):
        """Tolerates None caller gracefully."""
        self.assertFalse(uses_screenreader(None))

    def test_char_without_account_returns_false(self):
        """Returns False for objects with no account (e.g. NPCs)."""
        self.char1.account = None
        self.assertFalse(uses_screenreader(self.char1))


class TestPlainList(EvenniaTest):
    """Tests for plain_list()."""

    def test_single_row_no_headers(self):
        """Single row without headers joins with em-dash."""
        result = plain_list([["Char", "2m", "IC"]])
        self.assertEqual(result, "Char — 2m — IC")

    def test_multiple_rows_no_headers(self):
        """Multiple rows separated by newlines."""
        result = plain_list([["Char", "2m"], ["Char2", "5m"]])
        self.assertIn("Char", result)
        self.assertIn("Char2", result)
        lines = result.split("\n")
        self.assertEqual(len(lines), 2)

    def test_with_headers(self):
        """Headers prefix each value with 'Label: '."""
        result = plain_list([["Char", "2m"]], headers=["Name", "Time"])
        self.assertIn("Name: Char", result)
        self.assertIn("Time: 2m", result)

    def test_headers_joined_by_comma(self):
        """Header-mode rows are comma-joined."""
        result = plain_list([["a", "b"]], headers=["X", "Y"])
        self.assertIn(", ", result)
        self.assertNotIn(" — ", result)

    def test_empty_rows(self):
        """Empty input returns empty string."""
        self.assertEqual(plain_list([]), "")

    def test_more_values_than_headers(self):
        """Extra values beyond headers use index as label."""
        result = plain_list([["a", "b", "c"]], headers=["X"])
        self.assertIn("X: a", result)
        self.assertIn("1: b", result)
        self.assertIn("2: c", result)

    def test_non_string_values_coerced(self):
        """Integer values are coerced to strings."""
        result = plain_list([[42, True]])
        self.assertIn("42", result)
        self.assertIn("True", result)


class TestDescribeIcon(EvenniaTest):
    """Tests for describe_icon()."""

    def test_returns_meaning(self):
        """Returns the human-readable meaning string."""
        self.assertEqual(describe_icon("★", "Staff event"), "Staff event")

    def test_any_symbol(self):
        """Works with any symbol."""
        self.assertEqual(describe_icon("⚠", "Warning"), "Warning")


class TestDescribePriority(EvenniaTest):
    """Tests for describe_priority()."""

    def test_normal(self):
        self.assertEqual(describe_priority("normal"), "Normal priority")

    def test_high(self):
        self.assertEqual(describe_priority("high"), "High priority")

    def test_urgent(self):
        self.assertEqual(describe_priority("urgent"), "Urgent priority")

    def test_low(self):
        self.assertEqual(describe_priority("low"), "Low priority")

    def test_case_insensitive(self):
        self.assertEqual(describe_priority("HIGH"), "High priority")

    def test_unknown_level_falls_back(self):
        """Unrecognised levels return the input capitalised."""
        self.assertEqual(describe_priority("critical"), "Critical")


# ---------------------------------------------------------------------------
# AccessibleForm widget attrs
# ---------------------------------------------------------------------------


class _SimpleForm(AccessibleForm):
    """Test fixture: a small form exercising every widget branch."""

    name = forms.CharField(label="Name", max_length=100)
    note = forms.CharField(
        label="Note",
        widget=forms.Textarea,
        help_text="Optional context.",
        required=False,
    )
    agree = forms.BooleanField(label="I agree", required=False)
    hidden = forms.CharField(widget=forms.HiddenInput, required=False)


class TestAccessibleFormWidgetAttrs(EvenniaTest):
    """AccessibleForm automatically applies Bootstrap classes and aria attrs."""

    def setUp(self):
        super().setUp()
        self.form = _SimpleForm()

    def test_text_field_gets_form_control(self):
        widget = self.form.fields["name"].widget
        self.assertIn("form-control", widget.attrs.get("class", ""))

    def test_textarea_gets_form_control_and_rows(self):
        widget = self.form.fields["note"].widget
        self.assertIn("form-control", widget.attrs.get("class", ""))
        self.assertIn("rows", widget.attrs)

    def test_checkbox_gets_form_check_input(self):
        widget = self.form.fields["agree"].widget
        self.assertIn("form-check-input", widget.attrs.get("class", ""))
        # Checkbox should NOT get form-control
        self.assertNotIn("form-control", widget.attrs.get("class", ""))

    def test_hidden_input_not_modified(self):
        widget = self.form.fields["hidden"].widget
        # HiddenInput should not get Bootstrap classes or aria-describedby
        self.assertNotIn("aria-describedby", widget.attrs)
        self.assertNotIn("form-control", widget.attrs.get("class", ""))

    def test_aria_describedby_includes_error_id(self):
        widget = self.form.fields["name"].widget
        described = widget.attrs.get("aria-describedby", "")
        self.assertIn("id_name_errors", described)

    def test_aria_describedby_includes_help_id_when_help_text_present(self):
        widget = self.form.fields["note"].widget
        described = widget.attrs.get("aria-describedby", "")
        self.assertIn("id_note_errors", described)
        self.assertIn("id_note_help", described)

    def test_aria_describedby_no_help_id_when_no_help_text(self):
        widget = self.form.fields["name"].widget
        described = widget.attrs.get("aria-describedby", "")
        # name has no help_text, so _help id should not appear
        self.assertNotIn("id_name_help", described)

    def test_prefixed_form_uses_prefix_in_ids(self):
        prefixed = _SimpleForm(prefix="myprefix")
        widget = prefixed.fields["name"].widget
        described = widget.attrs.get("aria-describedby", "")
        self.assertIn("id_myprefix-name_errors", described)


# ---------------------------------------------------------------------------
# AccessibleModelForm
# ---------------------------------------------------------------------------


class _SimpleModelForm(AccessibleModelForm):
    """Minimal ModelForm fixture: bypasses real-model introspection for unit tests."""

    title = forms.CharField(label="Title", max_length=200)
    body = forms.CharField(label="Body", widget=forms.Textarea)

    class Meta:
        # No real model — bypass Meta model requirement for unit tests.
        model = None
        fields = ("title", "body")

    def __init__(self, *args, **kwargs):
        # Skip ModelForm's model introspection for this unit test.
        forms.Form.__init__(self, *args, **kwargs)
        self._add_widget_attrs()


class TestAccessibleModelFormWidgetAttrs(EvenniaTest):
    """AccessibleModelForm exposes the same widget attrs as AccessibleForm."""

    def setUp(self):
        super().setUp()
        self.form = _SimpleModelForm()

    def test_title_gets_form_control(self):
        widget = self.form.fields["title"].widget
        self.assertIn("form-control", widget.attrs.get("class", ""))

    def test_body_gets_form_control(self):
        widget = self.form.fields["body"].widget
        self.assertIn("form-control", widget.attrs.get("class", ""))

    def test_aria_describedby_on_title(self):
        widget = self.form.fields["title"].widget
        described = widget.attrs.get("aria-describedby", "")
        self.assertIn("id_title_errors", described)
