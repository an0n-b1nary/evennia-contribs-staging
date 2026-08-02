# Changelog — evennia-links

## Unreleased

- Test-only fix: the probe tables are now created by a `post_migrate` receiver during
  test-database setup instead of by the first `ProbeTablesTest` to run. Importing this
  contrib's test module registers probe models holding CASCADE FKs to `ObjectDB`, so every
  later `ObjectDB` hard-delete in a combined run queries those tables — which made
  `evennia test evennia_maps evennia_links` fail an unrelated maps test with
  `no such table: evennia_links_plainlinkprobe` while the reverse label order passed.
  No packaged code changed.

## 0.4.0 — collector-signal helper

- `collect_dicts(signal, **kwargs)`: `send_robust()` a collector signal and merge every
  receiver's dict response into one. Lets an "asking" app (e.g. `evennia-maps`) read data
  owned by several "answering" apps without importing any of them — each provider connects
  itself in its own gated `ready()`. A raising or non-dict receiver is logged and skipped
  rather than taking the request down. Lifted from the source game's `world.utils.collect`.
- `resolve_dotted(path)`: import and return the object at a dotted `"pkg.mod.attr"` path;
  None/empty input returns None, a bad *or dotless* path raises `ImportError`, and a missing
  attribute raises `AttributeError`. Deduplicates a helper that had been hand-rolled three times
  (`evennia_rptracker.commands`, `evennia_xp.batch`, `evennia_xp.gating`) — migrated
  `evennia_rptracker` to it, since it already depends on `evennia-links`. Left `evennia_xp`'s
  copies alone: it deliberately declares no `evennia-links` dependency, and adding one to
  dedupe a 10-line helper is a bad trade.

## 0.3.0 — shared editing framework

- `EditingMixin`: EvEditor + difflib mixin for version-tracked text editing of model
  text fields. Mix into `MuxCommand` subclasses that need `/edit`, `/history`,
  `/rollback`, and `/diff` switches. Pairs with `AbstractVersion` — the version model
  class is passed at call-time, so the mixin is not coupled to any particular domain.
  Hoisted from `evennia-lore` (where it shipped as a local copy flagged for future
  extraction). `evennia-lore>=0.1.1` now imports it from here.
- Lazy export: importing `evennia_links` does not import `EvEditor` until `EditingMixin`
  is first accessed — model-only consumers pay no extra import cost.

## 0.2.0 — soft-ref cleanup helper

- `connect_soft_ref_cleanup(target_model, bridge_model, field_name)`: registers
  a `post_delete` receiver that deletes bridge rows whose integer
  soft-reference field held the deleted pk. Compensates for the missing DB
  cascade when a bridge uses a `PositiveBigIntegerField` instead of a FK to
  an optional partner app. Hard-delete only; soft-archived records keep their
  links.

## 0.1.0 — initial extraction

- `AbstractLink`: minimal two-entity bridge base with `created_at` and generic
  idempotent `create_link()` classmethod driven by `link_fields`.
- `AbstractAuthoredLink(AbstractLink)`: adds `created_by` / `created_by_name`
  audit block for human-created bridges.
- `AbstractVersion`: append-only version-history base with `create_version()`
  and `rollback_to()` classmethods.
- `AbstractArchived` + `ArchivedManager` + `ArchivedQuerySet`: soft-archive
  mixin with default-manager filtering.
- `connect_on_ready`: import-order-safe signal-registration helper for
  `AppConfig.ready()`.

**Deferred to a future release:** `NotificationDispatcher` (multi-backend
notification delivery — in-game, email, Discord). Not yet implemented in the
source game; will be extracted once it exists.
