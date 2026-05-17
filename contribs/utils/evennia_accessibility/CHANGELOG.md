# Changelog

All notable changes to `evennia_accessibility` are documented here.

## 0.1.0 — 2026-05-17

Initial extraction from a source MUSH project at commit `7091d1e`.

- Screen-reader helpers: `uses_screenreader`, `plain_list`, `describe_icon`, `describe_priority`
- Accessible form base classes: `AccessibleForm`, `AccessibleModelForm`
- Form template partials: `_form_field.html`, `_form_errors.html`, `_form_actions.html`
- Accessibility CSS: `.sr-only` utility, form field/error styling, focus-visible rings, prefers-reduced-motion + prefers-color-scheme support
- MXP helpers: `absolute_web_url`, `mxp_link`
