# Changelog — evennia-regions

All notable changes to `evennia-regions` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
