# Migration Notes — evennia-xp 0.1.0

## Source inventory

Extracted from a MUSH project's `world/xp/` domain app and related web
layer. The models (`XPLog`, `CharacterXP`) were already integer-keyed by
design — the source code comment called it "a standalone contrib." The
batch engine was refactored from a hardcoded collector list into the
settings-driven registry that ships here.

## What shipped in the contrib (complete)

| File | Origin |
|---|---|
| `models.py` | Direct copy of `world/xp/models.py` (integer FK, no ObjectDB dep) |
| `signals.py` | Copy of `world/xp/signals.py` |
| `awards.py` | Copy of `world/xp/awards.py` (import paths updated) |
| `batch.py` | Refactored from `world/xp/batch.py` (registry-driven; `Award` namedtuple added) |
| `gating.py` | New — `XP_MULTIPLIER_RESOLVER` seam wrapping `world/utils/xp_gating.py`'s role |
| `antigaming.py` | `_find_burst`/`_item_time` only (extracted from `world/xp/antigaming.py`) |
| `scripts.py` | Copy of `world/xp/scripts.py` (import paths updated) |
| `commands.py` | Adapted from `commands/xp.py` (no projection section; generic sources list) |
| `permissions.py` | New — copy of `web/website/permissions.py` keyed to `XP_STAFF_LOCK` |
| `views.py` | Adapted from `web/website/views/xp.py` (gating seam, no arc object) |
| `api/` | Adapted from `web/api/` XP fragments |
| `management/` | Copy of `world/xp/management/` (source validation removed) |
| `migrations/0001_initial.py` | Derived from `world/xp/migrations/0001_initial.py` |
| `templates/evennia_xp/` | Adapted from `web/templates/website/xp_summary.html` |

## What stayed game-local (future-ownership map)

These pieces were deliberately not included in the contrib because they
depend on other game-specific domain apps. Each has a clear future owner.

| Game-local piece | Source domain | Eventual contrib owner |
|---|---|---|
| `world/xp/collectors.py` — `collect_rp_sessions` + session flag-flip | RPSession | `evennia-rptracker` (optional xp-integration submodule) |
| `world/xp/collectors.py` — `collect_lore_authored`, `collect_lore_inspiration` + `LoreInspirationCredit` | LoreEntry, LoreSceneLink | `evennia-lore` |
| `world/xp/collectors.py` — `collect_cutscene_posts` | Post | `evennia-boards` (#7) |
| `world/xp/collectors.py` — `collect_thread_bonuses` + `PlotBonusCredit` + thread flag-flip | PlotThread, PlotParticipant | `evennia-plots` (#10) |
| `world/xp/antigaming.py` — `_flag_cutscene_spam`, `_flag_thread_gaming`, `sweep()` | Post, PlotThread, Job | `evennia-boards` / `evennia-plots` |
| `world/xp/hooks.py` — `_flip_session_flags`, `_flip_thread_flags` | RPSession, PlotThread | `evennia-rptracker` / `evennia-plots` |
| `world/utils/xp_gating.py` — `resolve_xp_multiplier`, `resolve_active_arc` | PlotArc | `evennia-plots` (#10) — registered via `XP_MULTIPLIER_RESOLVER` |
| `world/xp/collectors.py` — `project_for_character` (balance projection) | RPSession, LoreEntry, Post, PlotThread | `evennia-plots` / `evennia-rptracker` |
| `LoreInspirationCredit.link` FK → LoreSceneLink | — | Converts to soft-ref when `evennia-lore` absorbs it |
| `PlotBonusCredit.thread` FK → PlotThread | — | Converts to soft-ref when `evennia-plots` absorbs it |

## Divergences from the source

- **Registry-driven engine.** The source had 6 hardcoded collectors called
  directly. The contrib replaces them with `XP_COLLECTORS`,
  `XP_ANTIGAMING_SWEEPS`, and `XP_POST_BATCH_HOOKS` settings so consumers
  supply their own domain-specific logic.

- **`Award` namedtuple moved to `batch.py`.** In the source it lived in
  `collectors.py`. The contrib defines it in `batch.py` so it's accessible
  without importing collector code.

- **`gating.py` is a seam, not an implementation.** The source had a full
  `resolve_xp_multiplier` that read `PlotArc` directly. The contrib ships
  only the delegation wrapper; the actual resolver is consumer-supplied via
  `XP_MULTIPLIER_RESOLVER`.

- **`antigaming.py` ships only the generic helpers.** The source had two
  game-specific sweep rules (`_flag_cutscene_spam`, `_flag_thread_gaming`)
  that read `Post` and `PlotThread`. These are omitted; only `_find_burst`
  and `_item_time` ship as reusable building blocks.

- **`+xp/sources` is generic.** The source listed game-specific sources with
  hardcoded rates. The contrib lists registered `XP_COLLECTORS` keys.

- **No balance projection.** The source `+xp` balance showed "projected XP"
  for the current week using game-specific collectors. The contrib omits this;
  games can implement it via a custom command or subclass.

- **`+spend`/`+upgrade` omitted.** These are stubs in the source that
  require a combat stats system (Phase 6). Document as consumer-implemented.

- **No `evennia-links` dependency.** The source XP app had no bridge models
  and no `AbstractLink`/`Archived` usage. The contrib correctly has zero
  `evennia-links` dependency.

- **No `objects` migration dependency.** Because `XPLog`/`CharacterXP` use
  plain integer fields instead of `ObjectDB` FKs, `0001_initial` has no
  `("objects", "__first__")` dependency and is fully self-contained.

- **Web view uses `downtime_active` bool, not arc object.** The source
  passed a `PlotArc` instance to the template for the downtime banner.
  The contrib passes `downtime_active: bool` and `xp_mult: Decimal` so the
  template has no arc model dependency.
