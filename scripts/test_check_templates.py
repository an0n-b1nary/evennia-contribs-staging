"""Focused regression tests for the repository template convention sweep."""

from __future__ import annotations

import unittest
from pathlib import Path

from check_templates import check_list_loops, check_markup_conventions


class TemplateConventionTests(unittest.TestCase):
    """The mechanical checks fail on each convention they own."""

    def setUp(self):
        self.path = (
            Path.cwd()
            / "contribs"
            / "game_systems"
            / "evennia_boards"
            / "templates"
            / "evennia_boards"
            / "fixture.html"
        )

    def test_valid_table_and_namespaced_class_pass(self):
        source = (
            '<div class="evennia-boards-table-scroll" role="region">'
            '<table class="table evennia-boards-example"><tr><td>ok</td></tr></table></div>'
        )
        self.assertEqual(check_markup_conventions(self.path, source), [])

    def test_inline_style_and_unscoped_class_fail(self):
        source = '<div class="custom" style="color:red"><table class="table"></table></div>'
        errors = check_markup_conventions(self.path, source)
        self.assertTrue(any("inline style" in error for error in errors))
        self.assertTrue(any("class 'custom'" in error for error in errors))
        self.assertTrue(any("table-scroll" in error for error in errors))

    def test_content_loop_requires_empty_branch(self):
        source = "{% for board in boards %}{{ board.name }}{% endfor %}"
        errors = check_list_loops(self.path, source)
        self.assertTrue(any("needs an" in error for error in errors))

    def test_outer_empty_state_satisfies_a_content_loop(self):
        source = "{% if boards %}{% for board in boards %}{{ board.name }}{% endfor %}{% else %}No boards{% endif %}"
        self.assertEqual(check_list_loops(self.path, source), [])

    def test_empty_state_include_satisfies_a_content_loop(self):
        source = (
            "{% for board in boards %}{{ board.name }}"
            '{% empty %}{% include "evennia_boards/_empty_state.html" %}{% endfor %}'
        )
        self.assertEqual(check_list_loops(self.path, source), [])

    def test_unrelated_inner_else_does_not_hide_a_missing_empty_branch(self):
        source = (
            "{% if boards %}{% for board in boards %}"
            "{% if board.is_new %}new{% else %}old{% endif %}"
            "{% endfor %}{% endif %}"
        )
        errors = check_list_loops(self.path, source)
        self.assertTrue(any("needs an" in error for error in errors))

    def test_bootstrap_prefix_is_not_an_allowlist(self):
        for name in ("btn-xs", "text-host-color", "bg-host", "col-md-99"):
            with self.subTest(name=name):
                self.assertTrue(check_markup_conventions(self.path, f'<p class="{name}">x</p>'))

    def test_multiline_conditional_classes_are_checked(self):
        source = '<p class="{% if state == "new" %}\ncustom{% else %}text-muted{% endif %}">x</p>'
        self.assertTrue(
            any("class 'custom'" in e for e in check_markup_conventions(self.path, source))
        )

    def test_comments_are_not_live_markup(self):
        source = '{% comment %}<p style="color:red" class="custom">{% for x in boards %}{% endfor %}{% endcomment %}'
        self.assertEqual(check_markup_conventions(self.path, source), [])
        self.assertEqual(check_list_loops(self.path, source), [])

    def test_all_content_contexts_require_empty_states(self):
        for expression in (
            "entry.tags.all",
            "new_collection",
            "boards reversed",
            "boards|slice:':5'",
        ):
            with self.subTest(expression=expression):
                source = f"{{% for item in {expression} %}}{{{{ item }}}}{{% endfor %}}"
                self.assertTrue(check_list_loops(self.path, source))

    def test_outer_else_must_guard_the_same_collection(self):
        for condition in ("entry.is_public", "entry.tags.all and is_staff", "not entry.tags.all"):
            with self.subTest(condition=condition):
                source = f"{{% if {condition} %}}{{% for tag in entry.tags.all %}}x{{% endfor %}}{{% else %}}empty{{% endif %}}"
                self.assertTrue(check_list_loops(self.path, source))

    def test_structural_exemption_depends_on_collection_not_variable_name(self):
        self.assertTrue(check_list_loops(self.path, "{% for field in boards %}x{% endfor %}"))
        self.assertEqual(check_list_loops(self.path, "{% for item in form %}x{% endfor %}"), [])

    def test_a_loop_in_an_else_branch_still_needs_an_empty_state(self):
        source = (
            "{% if boards %}Has boards{% else %}{% for board in boards %}x{% endfor %}{% endif %}"
        )
        self.assertTrue(check_list_loops(self.path, source))

    def test_embedded_styles_are_rejected(self):
        self.assertTrue(check_markup_conventions(self.path, "<style>p { color: red; }</style>"))

    def test_void_elements_cannot_serve_as_table_wrappers(self):
        source = '<input class="evennia-boards-table-scroll"><table></table>'
        self.assertTrue(check_markup_conventions(self.path, source))

    def test_malformed_loop_is_left_for_the_compilation_check(self):
        self.assertEqual(check_list_loops(self.path, "{% for item in %}x{% endfor %}"), [])


if __name__ == "__main__":
    unittest.main()
