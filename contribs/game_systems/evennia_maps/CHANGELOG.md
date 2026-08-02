# Changelog — evennia-maps

All notable changes to `evennia-maps` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] — 2026-08-02 — core extraction (no web)

- `MapPlane(AbstractArchived)` model: a 2D coordinate space. Planes sharing a non-blank
  `zstack` are vertically stacked layers at different `elevation`s (`evennia_maps_one_plane_per_elevation`
  constraint); a blank `zstack` marks a standalone/interior plane.
- `RoomTile` model: places a room at `(x, y)` on a plane. One tile per room, one room per
  cell (`unique_together`), plus a `pinned` flag and a denormalized `terrain` snapshot.
- `direction.resolve()`: canonical direction vocabulary (n/s/e/w/ne/nw/se/sw/u/d, both
  abbreviation and full name), settings-overridable via `DIRECTION_OFFSETS`.
- `terrain.resolve_terrain()`: resolves a room's `terrain_tags` to a single base terrain
  key via ordered `TERRAIN_PRECEDENCE`.
- `placement` module: the single tile-write path (`place_tile`, `place_relative`,
  `move_tile`, `unplace_tile`, `set_pin`, `apply_plan`). Every write either succeeds or
  returns a `Conflict` — never silently overwrites a held cell.
- `layout` module: read-only BFS reflow engine. `walk()` proposes positions and reports
  conflicts; `plan()` runs a fixed-point pass on top to compute the maximal set of moves
  safe to write together, accounting for pinned tiles and cascading blocks.
- `CmdMap` (`+map`): view (all players) + place/move/unplace/pin/unpin/reflow/check
  (staff, gated on `MAPS_STAFF_LOCK`, default `"cmd:perm(Builder)"`).
- Exit-creation listener (`SIGNAL_OBJECT_POST_CREATE`): auto-places a newly-created exit's
  destination when its source room is already mapped. Wrapped in a broad try/except — a
  mapping failure must never break `dig`.
- `MapsRoomMixin`: optional Room mixin providing `terrain_tags`, `set_terrain()`,
  `has_terrain()`. Fires `terrain_changed`, refreshing a placed tile's terrain snapshot.
- Signals: `tile_placed`, `tile_conflicted`, `terrain_changed` (all live), plus
  `collect_tile_overlays` (declared, unconnected — the web tile-overlay seam is a later
  phase of this extraction).
- Zero model-level dependency on any other contrib. `evennia-regions` is a separate,
  purely semantic room grouping with no geometry; the two are only ever joined at the
  web layer, in a later phase.
- No web/API surface yet — see README "Roadmap".
