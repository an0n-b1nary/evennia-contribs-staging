"""Focused regression tests for the repository template convention sweep."""

from __future__ import annotations

import unittest
from pathlib import Path

from check_templates import (
    REPO_ROOT,
    SHARED_COLOR_TOKENS,
    check_list_loops,
    check_markup_conventions,
    check_stylesheet,
    iter_stylesheets,
)


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


class StylesheetTokenTests(unittest.TestCase):
    """Every colour in a web contrib's stylesheet is a themeable token."""

    def setUp(self):
        self.path = (
            Path.cwd()
            / "contribs"
            / "game_systems"
            / "evennia_boards"
            / "static"
            / "evennia_boards"
            / "css"
            / "evennia_boards.css"
        )

    def check(self, source):
        return check_stylesheet(self.path, source)

    def test_shared_tokens_with_their_defaults_pass(self):
        source = (
            ".evennia-boards-empty { color: var(--evennia-color-muted, #6c757d); }\n"
            ".evennia-boards-x { background: var(--evennia-color-surface-alt, rgba(108,117,125,.1)); }"
        )
        self.assertEqual(self.check(source), [])

    def test_bare_colours_fail(self):
        for value in ("#6c757d", "#fff", "rgba(0, 0, 0, .5)", "hsl(0 0% 50%)", "white"):
            with self.subTest(value=value):
                errors = self.check(f".evennia-boards-x {{ color: {value}; }}")
                self.assertTrue(any("hard-coded colour" in error for error in errors))

    def test_a_shared_token_needs_its_one_default(self):
        self.assertTrue(self.check(".x { color: var(--evennia-color-muted, #777777); }"))
        self.assertTrue(self.check(".x { color: var(--evennia-color-muted); }"))

    def test_unknown_shared_tokens_fail(self):
        errors = self.check(".x { color: var(--evennia-color-brand, #123456); }")
        self.assertTrue(any("not a shared colour token" in error for error in errors))

    def test_own_tokens_take_any_fallback_but_need_one(self):
        self.assertEqual(self.check(".x { color: var(--evennia-boards-pin, #ffd54f); }"), [])
        self.assertTrue(self.check(".x { color: var(--evennia-boards-pin); }"))

    def test_another_namespace_cannot_be_read(self):
        self.assertTrue(self.check(".x { color: var(--primary, #007bff); }"))
        self.assertTrue(self.check(".x { color: var(--evennia-maps-tile, #3a3a3a); }"))

    def test_a_contrib_never_sets_a_shared_token(self):
        self.assertTrue(self.check(":root { --evennia-color-text: #000; }"))
        self.assertEqual(self.check(":root { --evennia-boards-pin: #ffd54f; }"), [])

    def test_comments_selectors_and_keywords_are_not_colours(self):
        source = (
            "/* was #6c757d */\n"
            ".evennia-boards-x:focus-visible { white-space: nowrap; background: none; }\n"
            ".evennia-boards-y { color: inherit; border-color: currentColor; }"
        )
        self.assertEqual(self.check(source), [])

    def test_errors_carry_the_line_number(self):
        errors = self.check("/* one\n   two */\n.x {\n  color: #fff;\n}")
        self.assertIn(f"{self.path}:4:", errors[0])

    def test_other_stylesheets_are_not_checked(self):
        path = Path.cwd() / "example_game" / "web" / "static" / "website" / "css" / "custom.css"
        self.assertEqual(check_stylesheet(path, ".x { color: #fff; }"), [])

    def test_the_sweep_finds_every_web_contrib_stylesheet(self):
        names = {path.stem for path in iter_stylesheets([])}
        self.assertIn("evennia_boards", names)
        self.assertIn("evennia_maps", names)
        self.assertNotIn("accessibility", names)

    def test_the_token_table_is_documented_where_hosts_and_contributors_look(self):
        documents = [
            REPO_ROOT / "UI_CONVENTIONS.md",
            REPO_ROOT / "contribs" / "utils" / "evennia_accessibility" / "README.md",
        ]
        for document in documents:
            text = document.read_text(encoding="utf-8")
            for token, default in SHARED_COLOR_TOKENS.items():
                with self.subTest(document=document.name, token=token):
                    self.assertIn(f"| `--evennia-color-{token}` | `{default}` |", text)


if __name__ == "__main__":
    unittest.main()
