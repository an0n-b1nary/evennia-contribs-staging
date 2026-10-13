# Changelog — evennia-links

## 0.8.4 — 2026-10-12

- Added disposable guest identification, movement and inventory boundaries, seeded arrival and restricted account lifecycle. Shared playable-character and web-character helpers exclude guests.
- Supply stock exit traversal to restricted guests without enabling other local object commands.
- Offline guest identity reads only guest accounts' rosters, so playable-character sweeps stay a single pass. `playable_accounts()` accepts an optional account queryset.
- The guest welcome is the overridable `GuestAccountMixin.guest_welcome`; exits are supplied only when the guest's cmdset sets `no_objs`, avoiding duplicate exit commands.

## 0.8.3 ? 2026-10-11

- Add three-way travel/visibility providers and rollback-safe Evennia object transactions.

## [0.8.2] - 2026-10-10

- Added `evennia_links.rooms.can(actor, room, action)` and `owner_of(room)`.
  Configured providers are authoritative and fail closed; without providers,
  rights use control access and ownership is unknown.
- Added signature-aware dispatch for legacy and viewer-aware room visibility
  callbacks. A callback is invoked once; exceptions never trigger a retry.

## [0.8.1] - 2026-10-10

- Added: `evennia_links.web.WebCharacterMiddleware`. Evennia's website already
  lets an account pick a character (the `character-puppet` link, stored in the
  session as `"puppet"`), but contribs resolve their character from
  `request.user` alone and ignored it, so the menu could name one character
  while a post went out as another. The middleware passes the choice to
  `web_character` for one request; a chosen character on the account's playable
  list now wins over live and last puppets. Without the middleware nothing
  changes.
- Added: `evennia_links.web.web_character_context`, a context processor giving
  templates `web_character` and `web_roster`, and
  `evennia_links.characters.web_roster(user)`.

## [0.8.0] - 2026-10-09

- Added: `evennia_links.characters.web_character(user, roster_only=False)`, the
  character a web request acts as. A live puppet is preferred but not required:
  live roster puppet, then any live puppet (unless `roster_only`), then the last
  puppet if it is on the roster, then roster order. Replaces seven per-contrib
  copies, six of which saw no character for a visitor not connected in-game.

## [0.7.0] - 2026-10-09

- Added: `evennia_links.characters`, the shared playable-character membership
  (`account_ids`, `same_account`, `playable_characters`, `is_playable`), so every
  package that pays or restricts players agrees on who counts.
- Added: `evennia_links.periodic`, Monday-anchored period labels and a retrying
  queue for idempotent period batches: only failed characters retry, with
  backoff, and periods missed while paused run once unpaused.

## [0.6.0] - 2026-10-09

- Added: Registered runtime controls, staff `+runtime` and the cap-contribution collector.

## [0.5.1] - 2026-10-02

- Validate complete web staff lock strings before evaluation, and deny access
  when staff policy settings cannot be read. Malformed multi-lock strings must
  not grant staff access through Evennia's partial lock parsing.
- Add the shared ``is_staff_user(request)`` web predicate with an optional
  ``EVENNIA_WEB_STAFF_PREDICATE`` hook and fail-closed
  ``EVENNIA_WEB_STAFF_LOCK`` fallback. This replaces nine drifting HTTP
  permission mirrors while leaving per-contrib command locks unchanged.
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
