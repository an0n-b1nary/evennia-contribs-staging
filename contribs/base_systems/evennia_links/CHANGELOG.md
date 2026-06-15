# Changelog — evennia-links

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
