# Migration notes — evennia_accessibility v0.1.0

Audit trail for the initial extraction. Useful for upstream reviewers, downstream adopters reconciling vendored copies, and future drift detection against the source.

## Source inventory

| Source file | Lines taken | What we took |
|---|---|---|
| `world/utils/accessibility.py` | full | `uses_screenreader(caller)`, `plain_list(rows, headers=None)`, `describe_icon(symbol, meaning)`, `describe_priority(level)` |
| `web/website/forms.py` | 34–96 only | `_CoVWidgetMixin`, `CoVBaseForm`, `CoVBaseModelForm` (renamed per below) |
| `web/templates/website/partials/_form_field.html` | full | verbatim, only the `{% include %}` path prefix changed |
| `web/templates/website/partials/_form_errors.html` | full | verbatim, only the `{% include %}` path prefix changed |
| `web/templates/website/partials/_form_actions.html` | full | verbatim, only the `{% include %}` path prefix changed |
| `web/static/website/css/cov.css` | accessibility blocks only | `.sr-only`, `.sr-only-focusable`, `.form-required-marker`, `.form-field-error`, `.has-error`, `.form-actions`, `:focus-visible`, `@media (prefers-reduced-motion: reduce)`, `@media (prefers-color-scheme: dark)` token overrides, fieldset/legend/focus-within block |
| `world/utils/urls.py` | full | `absolute_web_url(path)` |
| `world/utils/tests_accessibility.py` | full | 22 test methods across 4 classes — verbatim port with imports rewired |
| `web/website/tests_forms.py` | widget/attr tests only | Two test classes covering the form base widget injection — view-level tests dropped |

## Rename map

| Source name | Contrib name |
|---|---|
| `_CoVWidgetMixin` | `_AccessibleWidgetMixin` |
| `CoVBaseForm` | `AccessibleForm` |
| `CoVBaseModelForm` | `AccessibleModelForm` |
| `_add_cov_widget_attrs()` method | `_add_widget_attrs()` |
| `cov.css` (subset) | `accessibility.css` |
| CSS variable `--cov-color-danger` | `--evennia-a11y-color-danger` |
| CSS variables `--cov-color-{accent,surface-alt,text,focus-ring}` | `--evennia-a11y-color-{accent,surface-alt,text,focus-ring}` |
| CSS variables `--cov-radius-{sm,md}` | `--evennia-a11y-radius-{sm,md}` |
| CSS classes `.cov-fieldset`, `.cov-legend` | `.evennia-a11y-fieldset`, `.evennia-a11y-legend` |
| Module `world/utils/urls.py` | `mxp.py` |
| Test file `tests_accessibility.py` + widget tests | `tests.py` (single file, per the conventions doc) |

## New code (not in source)

- `mxp.py` gains a `mxp_link(url, label)` constructor. The `|lu<url>|lt<label>|le` MXP pattern was previously only documented in `absolute_web_url`'s docstring; the constructor formalises it. ~5 lines.
- Modernised `isinstance(widget, (forms.HiddenInput, forms.MultipleHiddenInput))` to `isinstance(widget, forms.HiddenInput | forms.MultipleHiddenInput)` (PEP 604, Python 3.10+) — Ruff's `UP` rule group auto-suggested this; the behavior is identical.

## Deliberately omitted

- **21 form subclasses** in the source `forms.py` (`PostForm`, `PlotThreadCreateForm`, `JobCreateForm`, etc.) — they import source-project domain models. The base classes alone are general-purpose; subclasses are application-specific.
- **`CoVAuthoringMixin`** (view-layer) and its tests — lives in the source's views module, not the form module; out of scope for an accessibility-focused contrib.
- **View-level test classes** from `tests_forms.py`: `TestIsStaffUser`, `TestGetCharacterId`, `TestRequireCharacter`, `TestCoVAuthoringMixin*`, `TestClusterRSVPFormValidation` — they test view utilities and source-specific forms.
- **Source-specific CSS blocks** from `cov.css`: font-face declarations for self-hosted Atkinson Hyperlegible, design tokens unrelated to accessibility, typography rules, link affordances, responsive tables, empty-state styling, breadcrumbs, theme hooks, diff viewer, print styles.

## Drift detection

To audit drift between this extracted version and the source as it evolves, run in the source repository:

```bash
git diff extracted/evennia-accessibility/v0.1..HEAD -- <source paths>
```

The source paths are the ones listed in the source-inventory table above (`world/utils/accessibility.py`, `world/utils/urls.py`, `web/website/forms.py`, `web/templates/website/partials/_form_*.html`, the accessibility blocks of `web/static/website/css/<stylesheet>`, `world/utils/tests_accessibility.py`, and the widget-test classes in `web/website/tests_forms.py`). The full command with concrete paths lives in the maintainer's internal planning notes (gitignored).

If the diff shows substantive changes, those changes need to be re-extracted into this contrib via a new sync commit.
