# Changelog — evennia-maps

All notable changes to `evennia-maps` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.1] — 2026-08-15 — overlay tests against real providers

- **Changed:** the overlay tests now run with *exactly* the providers they connect,
  detaching whatever the host game wired up for the duration. They previously asserted
  on the shape of the whole merged dict, which was only ever true in a maps-only
  install: a real partner contrib answers every collect, with empty dicts when it has
  no data, so four cases went red the moment `evennia-scenes`, `-lore`, `-regions` and
  `-calendar` shipped their providers. A maps suite that breaks when the seam is used
  is testing the wrong thing.

- **Added:** `test_query_count_is_flat_with_the_real_providers_installed` — the existing
  guard proves the *map* asks once per render, using a fake provider. This one proves
  the answer stays flat with whatever partners the game actually installed, which is
  where an N+1 would really come from.

- **Docs:** the README now names a worked example. `example_game/` in this repo installs
  this contrib alongside `evennia-regions`, `-scenes`, `-lore` and `-calendar`, seeds a
  six-room plane from one hand-placed origin tile, and proves all six overlay keys come
  back from one collect (`world/sandbox/tests.py::TestMapOverlaySeam`). That test cannot
  live here: this contrib's own suite has no partner contribs to install.

- **Docs:** README "Overlays" now says outright that an outbound overlay link needs the
  partner's **website URLconf mounted**, not merely its app installed.
  `overlay_url_templates()` reverses each role and silently drops the ones that do not
  resolve, so a game that installs `evennia-scenes` but never mounts
  `evennia_scenes.urls` gets tile popups listing recent logs as unlinked text, with no
  error anywhere to explain it.

- **Docs:** `MIGRATION_NOTES.md` records two divergences it had left implicit — the
  commands module's location, and the deliberate duplication of `is_room_web_visible()`
  between this contrib and `evennia-regions` — and drops a stale note calling
  `collect_tile_overlays` unconnected, which stopped being true in 0.2.0.

- **Docs, corrected:** `MIGRATION_NOTES.md` claimed the source game's plane list and
  detail views served archived planes and only its API filtered them. They did not — its
  `AbstractArchived` default manager excludes archived rows, the same as
  `evennia_links`', and its `PlaneListView` docstring says so. The real divergence is
  narrower: this contrib writes `.filter(is_archived=False)` out explicitly instead of
  trusting a manager the host game is free to replace. Rewritten to say that instead.

---

## [0.2.0] — 2026-08-15 — web surface

Adds the whole web half of the contrib. No schema change; `evennia-maps` 0.1.x installs
upgrade by running `pip install -e "evennia_maps[web]"` and mounting the two URL includes.

- **Website views** (`views.py`, `urls.py`, `templates/evennia_maps/`): `PlaneListView`
  (`/map/`), `PlaneMapView` (`/map/<pk>/`, inline-SVG grid, no JavaScript) and
  `PlaneLiveMapView` (`/map/<pk>/live/`, Leaflet). `build_svg_context()` and
  `filter_visible_tiles()` are public so a game or partner contrib can render a mini-map
  of a tile subset without restating the privacy filter or the layout math.
- **REST API** (`api/`): `PlaneViewSet` with a nested `tiles` action. Self-contained
  authentication/permission/pagination/filter classes — no dependency on the consumer's
  global `REST_FRAMEWORK` config. `PlaneSerializer.bounds` is computed from the *visible*
  tile set, so a bounding box never leaks the extent of rooms the caller cannot see.
  `TilePagination` is page-number rather than cursor: tile visibility is filtered in
  Python (Evennia Attributes, not columns), and cursor pagination cannot slice a list.
- **`collect_tile_overlays` is now live.** Sent once per map render — never per tile —
  with `room_ids` and `staff`, and merged through `evennia_links.collect_dicts()`. Partner
  contribs contribute `primary_region`, `has_active_scene`, `recent_scene_count`,
  `recent_scenes`, `has_lore` and `upcoming_events` from their own `ready()`, each under
  its own privacy rule, with no import in either direction and nothing to configure. A
  provider that raises degrades its own overlay to absent. See README "Overlays".
- **`hangout_type`** is read locally, duck-typed like `terrain_tags` — the one overlay
  with no table and no privacy rule behind it.
- **Portal markers**: `portal_target_planes_by_room()` infers portal-ness from exit
  geometry in two bulk queries (a room with an exit onto a different standalone plane),
  and checks the destination room's own visibility so a marker cannot name a hidden
  interior by the back door.
- **`permissions.is_staff_user()` / `is_room_web_visible()`** + `MAPS_ROOM_VISIBILITY`,
  mirrored from `evennia_regions`'s hardened version. Fails closed: a
  configured-but-unusable override hides every room rather than reverting to the default.
  `read_room_attr()` reads both an `AttributeProperty` and a plain Evennia Attribute, so
  a game that writes `room.db.room_type` is not silently published.
- **Outbound links are seams, not assumptions**: `MAPS_OVERLAY_URL_NAMES` (merged over
  the defaults) and `MAPS_TILES_URL_NAME`. A route that does not reverse renders as plain
  text rather than a broken link, and the live page explains itself instead of showing an
  empty canvas when the API is not mounted.
- **Static assets** under `static/evennia_maps/` (`evennia_maps.css`, `evennia_maps.js`).
  Leaflet 1.9.4 from a CDN with an SRI hash; nothing vendored.
- **New settings**: `MAPS_TERRAIN_TILESET`, `MAPS_ROOM_VISIBILITY`,
  `MAPS_OVERLAY_URL_NAMES`, `MAPS_TILES_URL_NAME`. New `[web]` extra
  (`djangorestframework`, `django-filter`).
- **Fixed**: the `{# ... #}` documentation comments in `_empty_state.html` and
  `_pagination.html` spanned lines. Django's comment regex is not `DOTALL`, so those were
  never comments — the usage example inside each one was a live `{% include %}` of the
  partial itself, which recursed until the stack blew. Now `{% comment %}` blocks. Same
  fix landed in `evennia-jobs`, `evennia-lore`, `evennia-regions`, `evennia-xp` and
  `evennia-accessibility`, which shipped copies of the same partials.
- 123 new tests, including a query-count guard asserting the overlay pass stays flat in
  tile count, and a render suite that renders the templates for real — a lazy
  `TemplateResponse` hides a `NoReverseMatch` from any test that only reads
  `context_data`, which is exactly how the two bugs above stayed invisible.

---

## [0.1.0] — 2026-08-02 — core extraction (no web)

- `MapPlane(AbstractArchived)` model: a 2D coordinate space. Planes sharing a non-blank
  `zstack` are vertically stacked layers at different `elevation`s (`evennia_maps_one_plane_per_elevation`
  constraint); a blank `zstack` marks a standalone/interior plane.
- `RoomTile` model: places a room at `(x, y)` on a plane. One tile per room, one room per
  cell (`unique_together`), plus a `pinned` flag and a denormalized `terrain` snapshot.
- `direction.resolve()`: canonical direction vocabulary (n/s/e/w/ne/nw/se/sw/u/d, both
  abbreviation and full name), settings-overridable via `MAPS_DIRECTION_OFFSETS`.
- `terrain.resolve_terrain()`: resolves a room's `terrain_tags` to a single base terrain
  key via ordered `MAPS_TERRAIN_PRECEDENCE`.
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
