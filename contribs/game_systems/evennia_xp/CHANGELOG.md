# Changelog — evennia-xp

All notable changes to `evennia-xp` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.4.1] - 2026-10-09

- **Changed:** the XP identity resolver delegates to
  `evennia_links.characters.web_character(user, roster_only=True)`, shared
  with the other web contribs. With no live roster puppet it now prefers the
  account's last puppet before roster order. Requires evennia-links 0.8.

## [0.4.0] - 2026-10-07

- **Added:** projected XP. `evennia_xp.projection.project_for_character()`
  runs the registered `XP_COLLECTORS` now and returns what they would pay one
  character, per source and in total, leaving out anything the ledger already
  records. It writes no XP and runs no anti-gaming sweep.
- **Added:** `+xp` shows a "Projected (not yet awarded)" block, listing every
  registered source and a total, whenever collectors are registered. A failed
  projection is logged and the rest of `+xp` still shows.
- **Added:** `evennia_xp.projection.activity_lines`, a ready-made
  `RPTRACKER_XP_PROJECTION` for evennia-rptracker's `+activity`: the sources
  with something pending and the total, or "nothing pending yet". Both
  outputs are plain text under screen-reader mode.
- Ported from the source project, whose `+xp` and `+activity` both showed a
  projection built from its own hardcoded source names.

## [0.3.0] - 2026-10-07

- **Added:** a first-login XP summary. The first time a character is puppeted
  after a weekly batch paid it, it sees that week's awards grouped by source,
  with a total and a pointer to `+xp`. Shown once per paying batch (tracked in
  the `last_xp_summary_week` Attribute); silent on quiet weeks. Plain-text
  output under `evennia-accessibility`'s screen-reader mode. Wire it with
  `evennia_xp.typeclasses.XPSummaryCharacterMixin` or call
  `evennia_xp.summary.notify_xp_summary(character)` from your own
  `at_post_puppet`. Ported from the source project, which kept it in its
  character typeclass.
- A failure inside the summary is logged and never breaks login; the week is
  not marked seen, so the next login retries.

## [0.2.0] - 2026-10-07

- Added `XPSpend` and atomic `spend_xp`/`refund_xp` services, mirrored from
  the source project after regression testing. Debits use conditional balance
  updates, globally unique references, and a one-time refund audit trail.
- Added post-commit `xp_spent`/`xp_refunded` signals and read-only spend admin.
  Earnings and weekly payout accounting remain in `XPLog`.
- Migration `0002_xpspend` creates the spend ledger.

## [0.1.5] - 2026-10-02

- **Changed:** web templates use the self-contained namespaced stylesheet and
  table, metadata, and empty-state conventions.

- **Changed:** the read-only XP page resolves a persistent account roster,
  keeps its resolver request-scoped, and renders an explanatory no-character
  state; web staff checks use ``evennia_links``.
- **Fixed:** the documentation comments at the top of `_empty_state.html` and
  `_pagination.html` spanned multiple lines. Django's template tag regex is not
  `DOTALL`, so a multi-line `{# ... #}` is not a comment — its text renders into the
  page, and the usage example inside each partial was a live `{% include %}` of the
  partial itself, recursing until the stack blew. Both are now `{% comment %}` blocks.
  Surfaced while building `evennia-maps`' web surface, whose tests render templates
  rather than only inspecting view context.

- **Added:** `TestXPSummaryRenders` — the XP summary page is now rendered for real
  via `response.render()`, in all three of its states: the award table, the empty
  state, and the screen-reader linear-list layout. The suite's existing
  `response.render()` calls are DRF API renders, which compile no HTML template.

## [0.1.4] - 2026-10-02

- Stack labelled table rows below 640px while retaining table semantics and desktop columns.

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
