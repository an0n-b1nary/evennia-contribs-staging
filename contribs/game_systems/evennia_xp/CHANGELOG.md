# Changelog — evennia-xp

All notable changes to `evennia-xp` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.1] — 2026-07-05 — update future-ownership map in MIGRATION_NOTES

- `MIGRATION_NOTES.md` future-ownership table updated to reflect items that
  have shipped in other contribs: rptracker 0.1.1 (`collect_rp_sessions` +
  `flip_session_flags`), lore 0.1.2 (`collect_lore_authored`,
  `collect_lore_inspiration`, `LoreInspirationCredit`), boards 0.1.0
  (`collect_cutscene_posts`), and plots 0.2.0 (`collect_thread_bonuses`,
  `sweep`, `resolve_xp_multiplier`). Doc-only; no code change.

---

## [0.1.0] — 2026-06-02 — initial extraction

Initial extraction from source MUSH project.

### Added
- `XPLog` and `CharacterXP` models (integer-keyed; no `ObjectDB` FK).
- `record_xp()` service function with idempotency guarantee and
  `CharacterXP` F()-expression aggregation.
- Registry-driven weekly batch engine (`run_weekly_batch`) with four
  settings seams: `XP_COLLECTORS`, `XP_ANTIGAMING_SWEEPS`,
  `XP_POST_BATCH_HOOKS`, `XP_MULTIPLIER_RESOLVER`.
- `Award` and `BatchSummary` namedtuples for type-safe collector contracts.
- `gating.resolve_xp_multiplier()` — delegates to `XP_MULTIPLIER_RESOLVER`;
  degrades to `Decimal("1.0")` when unset or raising.
- `antigaming._find_burst()` / `_item_time()` — generic sliding-window
  helpers for consumer sweep authors.
- `XPBatchScript` + `ensure_xp_batch_script_running()` (lazy-Script pattern).
- `CmdXp` — balance/log/sources/+xp/grant with `XP_STAFF_LOCK` and
  optional `evennia-accessibility` screen-reader fallback.
- `XPSummaryView` — self-only web balance + log (paginated).
- `XPLogViewSet` — DRF self-only read-only API.
- `run_xp_batch` management command.
- `xp_awarded` and `xp_batch_completed` signals.
- Django admin for `XPLog` (read-only) and `CharacterXP`.
