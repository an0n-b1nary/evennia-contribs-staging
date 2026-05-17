# evennia-accessibility

Screen-reader helpers, accessible Django form base classes, and MXP URL utilities for [Evennia](https://www.evennia.com/).

> ⚠️ This is a preview contrib in active development. APIs may change. Pin to specific commits if you depend on it.

## What it ships

- **Four screen-reader helpers** that gate on a per-account `screenreader_mode` option:
  - `uses_screenreader(caller)` — boolean test, tolerates None and account-less callers
  - `plain_list(rows, headers=None)` — em-dash or "Label: value" rendering for tabular data
  - `describe_icon(symbol, meaning)` — swap a decorative icon for its description
  - `describe_priority(level)` — readable priority labels alongside color cues
- **Two accessible Django form base classes** that auto-apply Bootstrap widget classes and `aria-describedby` wiring:
  - `AccessibleForm` — for non-model forms
  - `AccessibleModelForm` — for ModelForms
- **Three form template partials** for accessible rendering:
  - `_form_field.html` — label + widget + always-present error region + help text
  - `_form_errors.html` — non-field errors in an `aria-live="assertive"` summary
  - `_form_actions.html` — submit + optional cancel with sensible defaults
- **An accessibility-focused stylesheet** (`accessibility.css`) with `.sr-only` utilities, focus-visible rings, `prefers-reduced-motion` + `prefers-color-scheme: dark` overrides, and the form rules that pair with the partials
- **Two MXP URL helpers**:
  - `absolute_web_url(path)` — promote site-relative paths to absolute URLs via `SITE_URL`
  - `mxp_link(url, label)` — build `|lu<url>|lt<label>|le` for clickable in-game links

## Install

Install directly from this repo with pip:

```bash
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/utils/evennia_accessibility&egg=evennia-accessibility"
```

If pip-from-subdirectory hits friction in your environment, fall back to copying the `evennia_accessibility/` directory directly into your game's local `contrib/` tree.

## Wiring

In your game's `server/conf/settings.py`:

```python
INSTALLED_APPS += ["evennia_accessibility"]

OPTIONS_ACCOUNT_DEFAULT["screenreader_mode"] = {
    "default": False,
    "category": "Accessibility",
    "description": "Enable plain-text screen-reader output",
}

# Optional — only needed if you use `absolute_web_url()` in email/Discord/external contexts.
SITE_URL = "https://your-game-domain.example"
```

Players can then toggle the option with the standard `@option` command:

```
@option screenreader_mode = True
```

## Usage

### Screen-reader helpers

```python
from evennia_accessibility import uses_screenreader, plain_list, describe_icon, describe_priority

if uses_screenreader(self.caller):
    self.caller.msg(plain_list(rows, headers=["Name", "Time", "Status"]))
else:
    # normal EvTable rendering
    self.caller.msg(table.render())

# Swap decorative icons for their meaning
indicator = describe_icon("★", "Staff event") if uses_screenreader(caller) else "★"

# Pair priority colors with readable labels
label = describe_priority("urgent")  # "Urgent priority"
```

### Accessible form bases

```python
from django import forms
from evennia_accessibility import AccessibleForm

class FeedbackForm(AccessibleForm):
    subject = forms.CharField(label="Subject", max_length=200)
    body = forms.CharField(label="Body", widget=forms.Textarea, help_text="Optional context.")
```

Render in a template:

```django
{% load static %}
<link rel="stylesheet" href="{% static 'evennia_accessibility/css/accessibility.css' %}">

<form method="post">
  {% csrf_token %}
  {% include "evennia_accessibility/_form_errors.html" with form=form %}
  {% include "evennia_accessibility/_form_field.html" with field=form.subject %}
  {% include "evennia_accessibility/_form_field.html" with field=form.body %}
  {% include "evennia_accessibility/_form_actions.html" with submit_label="Send feedback" cancel_url=cancel_url %}
</form>
```

### MXP links

```python
from evennia_accessibility import absolute_web_url, mxp_link

href = absolute_web_url(f"/scenes/{scene.pk}/")
self.caller.msg(f"View scene: {mxp_link(href, '[↗]')}")
```

## Configurability

| Hook | Type | Purpose |
|---|---|---|
| `SITE_URL` | Django setting | Base for `absolute_web_url`. Unset → returns the relative path unchanged (works for webclient MXP, fails for external clients/email). |
| `screenreader_mode` | Account option | Read by `uses_screenreader(caller)`. Add to `OPTIONS_ACCOUNT_DEFAULT` as shown above. |
| `--evennia-a11y-color-danger` | CSS custom property | Default `#c0392b`. Override in your stylesheet to retheme error messaging. Other `--evennia-a11y-*` tokens follow the same pattern. |

## License

[BSD 3-Clause](../../../LICENSE) — matches Evennia upstream.

---

*Extracted from a source MUSH project at commit `7091d1e` on 2026-05-17.*
