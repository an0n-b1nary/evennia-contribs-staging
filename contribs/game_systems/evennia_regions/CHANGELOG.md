# Changelog — evennia-regions

All notable changes to `evennia-regions` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

- **Fixed:** the documentation comments at the top of `_empty_state.html` and
  `_pagination.html` spanned multiple lines. Django's template tag regex is not
  `DOTALL`, so a multi-line `{# ... #}` is not a comment — its text renders into the
  page, and the usage example inside each partial was a live `{% include %}` of the
  partial itself, recursing until the stack blew. Both are now `{% comment %}` blocks.
  Surfaced while building `evennia-maps`' web surface, whose tests render templates
  rather than only inspecting view context.

- **Added:** `TestWebPagesRender` — both region pages are now rendered for real via
  `response.render()`. The existing view tests stop at `response.context_data`, which
  compiles no template: a `ListView` returns a lazy `TemplateResponse`, so a missing
  partial or an unreversable URL surfaces only on render. The privacy rules — member
  counts withheld from non-staff, hidden rooms absent from the member list — are now
  asserted against the rendered HTML as well as the context.

- **Fixed:** `_pagination.html` documented `extra_params` as needing a trailing
  `&` that the partial itself adds.

---

## [0.1.1] — 2026-08-02 — room-visibility hardening, unique memberships

Review pass on the initial extraction. Both fixes are behaviour changes to the
privacy path; neither affects the models' public API.

- **`is_room_web_visible()` now reads room flags from a plain Evennia Attribute
  as well as a typeclass attribute.** It previously used `getattr` alone, which
  never consults the AttributeHandler — so a game that set
  `room.db.room_type = "staff"` (the ordinary idiom) had every such room
  published on the region page. Both sources are consulted and the *hidden*
  answer wins, so a permissive class default cannot shadow an Attribute that
  hides the room.
- **`REGIONS_ROOM_VISIBILITY` now fails closed.** A path that cannot be
  imported, resolves to `None`, or raises when called hides every room and logs
  the failure, instead of silently reverting to the looser built-in rule. It
  also catches `Exception` rather than `ImportError` alone — a valid module with
  a mistyped attribute name previously raised `AttributeError` straight out of
  the region detail view (HTTP 500), and a hook module that raised at import did
  the same.
- **`RegionMembership` gained `unique_together = [("region", "room")]`**
  (migration `0002`). Nothing previously stopped a room joining the same region
  twice, which made `member_count()` double-count it and left
  `create_link()`'s `get_or_create` open to a race.
- README: corrected the `REGIONS_ROOM_VISIBILITY` example, which was named and
  written as an *is-hidden* predicate while the setting expects **True = visible**
  — copying it would have inverted a game's room privacy. Also corrected the
  programmatic membership example to `create_link(..., linked_by=...)`.

---

## [0.1.0] — 2026-08-02 — initial extraction

- `Region(AbstractArchived)` model: named geographic area, soft-archivable.
  `Region.create_region()` atomically creates and fires `region_created`.
- `RegionMembership(AbstractAuthoredLink)` model: many-to-many bridge from
  Room (ObjectDB) to Region, with an `is_primary` flag enforced by a partial
  unique constraint (`evennia_regions_one_primary_per_room`) — at most one
  primary membership per room. `RegionMembership.primary_for(room_id)`
  resolves the single deterministic region for a room, falling back to the
  earliest membership when none is flagged primary.
- `region_created` signal: fires on `Region.create_region()`; ships with
  zero receivers.
- `CmdRegion` (`+region`): list/`/view`/`/here` for all players;
  `/create`, `/edit`, `/add-room`, `/remove-room`, `/here-add`, `/primary`
  gated on `REGIONS_STAFF_LOCK` (default `"cmd:perm(Builder)"`).
- Website surface (`[web]` extra): `RegionListView`, `RegionDetailView`.
  Member-room lists filtered through `REGIONS_ROOM_VISIBILITY` for
  non-staff visitors; member counts are staff-only.
- DRF API (`[web]` extra): `RegionViewSet` — self-contained (explicit
  auth/pagination/filter classes). `member_count` is `null` for non-staff.
- Zero model-level dependency on any other contrib. `evennia-lore>=0.1.3`
  gates a `connect_soft_ref_cleanup` on `LORE_REGIONS_APP_LABEL` (default
  `"evennia_regions"`) that goes live automatically once this contrib is
  installed — no configuration needed on the regions side.
