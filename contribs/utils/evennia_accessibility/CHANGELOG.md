# Changelog

All notable changes to `evennia_accessibility` are documented here.

## [Unreleased]

- Reject unknown, ambiguous and stacked switches before command lookups or changes, including stock command replacements.
- Require evennia-links for the shared command switch validator.

## [0.3.3] - 2026-10-10

- **Added:** a player guide page for evennia-guides, `accessibility`
  (screen-reader mode, ambient muting and the website), in `guides/` and the
  package data. It describes the system in general terms, without exact numbers,
  and links only to pages this contrib or its required dependencies ship.
  Without evennia-guides it's ignored.

## [0.3.2] - 2026-10-10

- **Added:** the shared `--evennia-color-*` theme tokens, documented in the
  README with their defaults. The web contribs' stylesheets read them, and this
  stylesheet's `--evennia-a11y-*` text, accent, danger and border colours now
  default to them, so one host stylesheet rethemes every contrib page. Unset,
  every colour is as before, in both colour schemes.

## [0.3.1] - 2026-10-10

- **Added:** `_acting_as.html`, which names the character a form writes as
  ("Posting as **Name**", id `form-acting-as`) when the context has
  `acting_character`. `_form_actions.html` includes it and points the submit
  button's `aria-describedby` at it, so a screen reader names the character when
  focus reaches the button. Without `acting_character` both render as before.

## [0.3.0] - 2026-10-10

- Added: per-account ambient mute helper and `+ambient` command, shared across
  characters and logins. Remote effects fail closed when the option is missing;
  in-room scene effects are unaffected. Hosts explicitly register the option.

## [0.2.0] - 2026-10-07

- **Added:** `+screenreader` (alias `+sr`) in `evennia_accessibility.commands` — a
  shortcut for toggling the `screenreader_mode` option this contrib already reads.
  Bare invocation reports the current state; `/on` and `/off` set it. Works from a
  character or out of character from the account. Ported from the source project,
  where it lived among the social commands even though the option it toggles is
  owned here.
- **Added:** a game that never registered `screenreader_mode` in
  `OPTIONS_ACCOUNT_DEFAULT` now gets a plain message for the player and a warning in
  the server log naming the fix, instead of the `ValueError("Option not found!")`
  Evennia's `OptionHandler.set` raises. The source command raised.

## [0.1.1] - 2026-10-02

- **Fixed:** the documentation comments at the top of `_form_actions.html`,
  `_form_errors.html` and `_form_field.html` spanned multiple lines. Django's template
  tag regex is not `DOTALL`, so a multi-line `{# ... #}` is not a comment — its text
  renders into the page. All three are now `{% comment %}` blocks. Surfaced while
  building `evennia-maps`' web surface, whose tests render templates rather than only
  inspecting view context.

- **Added:** `TestFormPartialsRender` — all three shipped partials are now rendered
  for real via `render_to_string`. They belong to no page of this contrib's own, but
  `evennia_jobs`, `evennia_lore` and `evennia_plots` all `{% include %}` them, so a
  change here breaks four packages at once and only at render time; the existing
  tests assert on `widget.attrs` and never touch the templates. The aria contract is
  asserted directly: the error region is always present so `aria-describedby` has a
  stable target, and only becomes `role="alert"` when there is something to announce.

## 0.1.0 — 2026-05-17

Initial extraction from a source MUSH project at commit `7091d1e`.

- Screen-reader helpers: `uses_screenreader`, `plain_list`, `describe_icon`, `describe_priority`
- Accessible form base classes: `AccessibleForm`, `AccessibleModelForm`
- Form template partials: `_form_field.html`, `_form_errors.html`, `_form_actions.html`
- Accessibility CSS: `.sr-only` utility, form field/error styling, focus-visible rings, prefers-reduced-motion + prefers-color-scheme support
- MXP helpers: `absolute_web_url`, `mxp_link`
