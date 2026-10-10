# Changelog — evennia-guides

All notable changes to `evennia-guides` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
