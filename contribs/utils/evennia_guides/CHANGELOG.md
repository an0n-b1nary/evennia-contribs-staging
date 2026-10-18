# Changelog — evennia-guides

All notable changes to `evennia-guides` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.2] - 2026-10-18

- **Docs:** `writing-guides` describes the layout for a contrib's staff page:
  key `<contrib>-staff`, `audience: staff`, no `requires:`, and the sections
  what it's for, tasks and commands, what's safe to change, privacy and review
  jobs.

## [0.2.1] - 2026-10-10

- **Docs:** a contrib's pages link and tag only pages that it or its required
  dependencies ship; optional partners are named in prose.

## [0.2.0] - 2026-10-10

- **Added:** every colour in the stylesheet is a shared `--evennia-color-*` theme
  token with its previous colour as the fallback, so a host stylesheet that
  sets the tokens on `:root` rethemes this contrib's pages along with the
  others. Nothing changes until a host sets one. The token list is in
  evennia-accessibility's README.
- **Changed:** the design-insight panel's background is `surface-alt`
  (`rgba(108, 117, 125, .1)`, was `.08`).

## [0.1.1] - 2026-10-10

### Fixed

- `guides_check` and `validate()` now recognise a `requires:` name backed by an
  `evennia_links` runtime setting without reading the database. Before, the
  value was read while checking that the name existed, so validation without
  a database reported a contrib's reveal switch as resolving to nothing.

## [0.1.0] - 2026-10-09

### Added

- Guide pages as Markdown files with YAML front matter, found in every
  installed app's `guides/` directory and in `GUIDES_DIRS`. A later page with
  the same key replaces an earlier one.
- Design insight blocks (`:::insight[Title]{principles}`), links between pages
  (`[[key]]`), tables in scroll regions, and section anchors with an "On this
  page" list. Raw HTML is shown as text.
- Pages hidden from players until a named check passes (`requires:`). Checks
  resolve through `GUIDES_CHECKS`, `register_check`, `evennia-links` runtime
  settings, then Django settings, and fail closed. Links to hidden pages are
  plain text.
- Staff pages (`audience: staff`), and staff reading of hidden pages with the
  reason shown (`GUIDES_STAFF_LOCK`).
- Web views: index by category, page, Design principles (insights gathered by
  tag), and glossary.
- An "Ask about this page" link with a prefilled title and description
  (`GUIDES_ASK_URL`).
- `evennia guides_check`, which reports pages that failed to load, broken
  links and tags, unknown checks and colliding aliases.
- A staff page, `writing-guides`.
