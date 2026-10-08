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
| `commands.py` | Adapted from `commands/xp.py` (generic sources list; projection block since 0.4.0) |
| `permissions.py` | New — copy of `web/website/permissions.py` keyed to `XP_STAFF_LOCK` |
| `views.py` | Adapted from `web/website/views/xp.py` (gating seam, no arc object) |
| `api/` | Adapted from `web/api/` XP fragments |
| `management/` | Copy of `world/xp/management/` (source validation removed) |
| `migrations/0001_initial.py` | Derived from `world/xp/migrations/0001_initial.py` |
| `templates/evennia_xp/` | Adapted from `web/templates/website/xp_summary.html` |

## What stayed game-local (future-ownership map)

These pieces were deliberately not included in the contrib because they
depend on other game-specific domain apps. Items marked **shipped** have
since landed in the indicated contrib package.

| Game-local piece | Source domain | Status |
|---|---|---|
| `world/xp/collectors.py` — `collect_rp_sessions` + session flag-flip | RPSession | **Shipped** — `evennia-rptracker` 0.1.1 (`integrations/xp.py`) |
| `world/xp/collectors.py` — `collect_lore_authored`, `collect_lore_inspiration` + `LoreInspirationCredit` | LoreEntry, LoreSceneLink | **Shipped** — `evennia-lore` 0.1.2 (`integrations/xp.py` + `LoreInspirationCredit` model) |
| `world/xp/collectors.py` — `collect_cutscene_posts` + `_flag_cutscene_spam` | Post | **Shipped** — `evennia-boards` 0.1.0 (`integrations/xp.py`) |
| `world/xp/collectors.py` — `collect_thread_bonuses` + `PlotBonusCredit` + `_flag_thread_gaming`, `sweep()` | PlotThread, PlotParticipant | **Shipped** — `evennia-plots` 0.2.0 (`integrations/xp.py` + `integrations/antigaming.py`; `PlotBonusCredit` intra-domain FK is fine) |
| `world/utils/xp_gating.py` — `resolve_xp_multiplier`, `resolve_active_arc` | PlotArc | **Shipped** — `evennia-plots` 0.2.0 (`integrations/gating.py`), registered via `XP_MULTIPLIER_RESOLVER` |
| `world/xp/hooks.py` — `_flip_session_flags` | RPSession | **Shipped** — `evennia-rptracker` 0.1.1 (`integrations/xp.flip_session_flags`) |
| `world/xp/collectors.py` — `project_for_character` (balance projection), `world/xp/projection_adapter.py` | RPSession, LoreEntry, Post, PlotThread | **Shipped** — `evennia-xp` 0.4.0 (`projection.py`): generic over `XP_COLLECTORS`, so it reads no other domain directly |
| `+spend`/`+upgrade` commands | Combat stats | Not yet shipped — requires Phase 6 combat-stats system |

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

- **Projection (0.4.0).** The source `+xp` and `+activity` showed projected
  XP using hardcoded source keys (`rp_session`, `lore_authored`, …); 0.1–0.3
  left it out. `projection.py` now builds it from whatever `XP_COLLECTORS`
  holds, labelled from `XPLog.SourceType`. It differs from the source in two
  ways. Awards already in the ledger are left out, because the source relied
  on each collector filtering them. `+activity` lists only the sources with
  something pending.

- **Spending (0.2.0).** `XPSpend`, `spend_xp`/`refund_xp`, and their post-commit
  signals were implemented and regression-tested in the source project first,
  then mirrored here. Migration `0002_xpspend` adds the debit ledger, using
  integer character/staff references. `XPLog` remains earn-only. Commands
  `+spend`/`+upgrade` belong to the consuming ability system; rp-chargen ships
  those commands and an optional adapter for this ledger.

- **First-login summary (0.3.0).** The source kept `_notify_xp_summary()` on
  its Character typeclass, and the posing extraction left it behind as "the
  consuming game's own". Nothing in it is game-specific, so it now ships as
  `summary.notify_xp_summary()` plus `typeclasses.XPSummaryCharacterMixin`.
  Same Attribute key (`last_xp_summary_week`, default category), so a game
  adopting the contrib keeps its state. Changes: the aggregate lookup is a
  single `values_list` read; errors go through Evennia's `logger.log_trace`;
  the function returns whether it showed anything. The source's 13 tests are
  ported (some merged), plus a failure-path test and a mixin MRO test.

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
