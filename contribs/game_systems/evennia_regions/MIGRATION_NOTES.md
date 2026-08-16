# Migration Notes — evennia-regions

## Source inventory

Extracted from a private Evennia game project.

| Source module | Contrib module | Notes |
|---|---|---|
| `world/regions/models.py` | `models.py` | Copied; `AbstractArchived`/`AbstractAuthoredLink` rebased from `evennia_links` (source game split these across `world/utils/archiving.py` and `world/utils/links.py`) |
| `world/regions/signals.py` | `signals.py` | Direct copy |
| `world/regions/apps.py` | `apps.py` | Rewritten for contrib conventions (`label = "evennia_regions"`, docstring explaining the app has no `ready()`); behaviour identical — no listeners either way |
| `world/regions/admin.py` | `admin.py` | Copy; RUF012 noqa added |
| `commands/regions.py` | `commands.py` | Copy; `commands/editing.py::EditingMixin` imported from `evennia-links>=0.4` instead; hardcoded `perm(Builder)` checks replaced with `permissions.is_staff()` resolving `REGIONS_STAFF_LOCK` |
| `web/website/permissions.py` (partial) | `permissions.py` | New module — `is_staff`, `is_staff_user`, `is_room_web_visible` rebased onto contrib settings (`REGIONS_STAFF_LOCK`, `REGIONS_ROOM_VISIBILITY`) instead of the source game's hardcoded `perm(Builder)` and `world.utils` imports |
| `web/website/views/regions.py` | `views.py` | `RegionListView`/`RegionDetailView` ported; see divergences below — the lore-entries stub and the maps mini-map are **not** shipped |
| `web/website/urls.py` (region patterns) | `urls.py` | Extracted; namespaced (`app_name = "evennia_regions"`) |
| `web/templates/website/region_*.html` | `templates/evennia_regions/region_*.html` | Rebased to the `evennia_regions/` template namespace; region-maps and lore-entries sections removed to match the trimmed view |
| `web/templates/website/partials/_pagination.html`, `_empty_state.html` | `templates/evennia_regions/_pagination.html`, `_empty_state.html` | Shipped copies (same partials `evennia-lore` ships), rebased to the `evennia_regions/` namespace |
| `web/api/serializers.py` (`RegionSerializer`) | `api/serializers.py` | Rebased; staff check imported from contrib's `permissions.py` |
| `web/api/filters.py` (`RegionFilter`) | `api/filters.py` | Direct copy |
| `web/api/views.py` (`RegionViewSet`) | `api/views.py` | Self-contained: explicit pagination/auth/permission/filter classes, matching the `evennia-lore`/`evennia-calendar` API convention (the source game instead relies on one shared `REST_FRAMEWORK` config for all viewsets) |
| `web/api/urls.py` (region registration) | `api/urls.py` | Extracted |
| `web/website/views/maps.py::primary_regions_by_room` | `integrations/maps.py` | Moved to the owning domain and reshaped as a `collect_tile_overlays` provider — in the source game the map imported `RegionMembership` directly. Now also excludes archived regions (below) |

## Key divergences from source game

**The region-detail lore section and mini-map are not shipped.** In the source game,
`RegionDetailView` also renders linked `LoreEntry` rows (via the lore app's
`LoreRegionLink` bridge) and an embedded SVG mini-map per plane (via the maps app's
`RoomTile` + SVG builder). Both require importing another domain's models directly,
which would break the "zero model-level coupling" property that makes regions one of
the simplest contribs to extract. Neither integration has a signal-based seam today
(unlike the maps `collect_tile_overlays` pattern used by scenes/lore/calendar) — adding
one is future work, not invented here per the standing rule against building an
unused extension point.

**The map overlay skips archived regions; the source game's did not.**
`primary_regions_by_room()` there joined through `RegionMembership` with no archive
filter, so a tile could name — and link to — a region whose own detail page 404s
(`Region.objects` excludes archived rows, and a filter on the membership table does not
apply that manager to the joined one). The provider filters `region__is_archived=False`,
which also means a room whose *flagged primary* is archived falls through to its next
visible membership rather than going blank. This is a deliberate divergence from
`RegionMembership.primary_for()`, whose answer stays the flagged one.

**Staff permission configurable via `REGIONS_STAFF_LOCK`.** The source game hardcoded
`perm(Builder)` in `commands/regions.py` (there was no staff-lock setting for regions at
all, unlike its sibling domains `world/lore`, `world/jobs`, etc., which all had one). The
contrib introduces `REGIONS_STAFF_LOCK` (default `"cmd:perm(Builder)"`), matching the
`LORE_STAFF_LOCK` convention, and uses it consistently across commands, web views, and
the API.

**Room-visibility rule made configurable (`REGIONS_ROOM_VISIBILITY`).** The source game's
`is_room_web_visible()` lived in one shared `web/website/permissions.py`, hardcoding
`room_type`/`allow_teleport` attribute names that come from another contrib
(`evennia-social`'s `SocialRoomMixin`). The contrib ships the same default rule but
exposes a dotted-path override for games with a different hiding convention. This is a
deliberate duplication rather than a dependency edge: `evennia-maps` now ships the
identical seam (`MAPS_ROOM_VISIBILITY`), which is what keeps the two contribs free of a
dependency in either direction and lets a game install either one alone. Keep them in
step — the AttributeHandler fallback and the fail-closed override resolution are both
security-relevant, so a fix to one is a fix owed to the other.

**The flag reads consult the AttributeHandler, not just `getattr`.** The source game reads
`getattr(room, "room_type", "ic")`, which works there only because its own Room typeclass
declares both flags as `AttributeProperty` descriptors. A game that instead sets
`room.db.room_type = "staff"` — the ordinary Evennia idiom — gets nothing from `getattr`,
which silently reported every such room as visible. The contrib checks the descriptor first
(so a typeclass default still wins) and falls back to `room.attributes.get(...)`, so either
storage convention hides the room.

**`REGIONS_ROOM_VISIBILITY` fails closed.** A configured-but-unusable override hides every
room rather than reverting to the built-in rule. A game sets this setting only because its
rules are *stricter* than the default, so falling back on a typo would publish exactly the
rooms the operator was withholding. The resolution also catches `Exception`, not
`ImportError` alone — importing the path runs the game's own top-level code, and calling the
override runs game code too (the same failure mode fixed in `evennia-rptracker` v0.1.3).

**`RegionMembership` gained `unique_together = [("region", "room")]`.** The source game
constrains only one-primary-per-room, leaving nothing to stop the same room joining the same
region twice; `member_count()` then double-counts it on the region page, and
`create_link()`'s `get_or_create` is not race-safe. `AbstractAuthoredLink`'s own docstring
requires the two `link_fields` be unique together. Added as migration `0002` rather than
folded into `0001` so anyone who already applied `0001` upgrades cleanly.

**Constraint name prefixed with `evennia_regions_`.** `regions_one_primary_per_room` is
renamed to `evennia_regions_one_primary_per_room` for the same collision-avoidance reason
`evennia-lore` renames its constraints.

**FK dependency pinned to `("objects", "__first__")`.** Portable across Evennia installs.

**Commands ship inside the package, not in a `commands/` folder.** The source game keeps
every command module in one top-level `commands/` package and its cmdsets import from
there; a contrib has no such folder, so `CmdRegion` is importable as
`evennia_regions.commands.CmdRegion` — the shape every contrib in this repo uses.
`evennia-maps` made the same move for the same reason. A game moving from the source
layout deletes its `commands/regions.py` and changes one import in its `CharacterCmdSet`;
syntax, switches and lock are unchanged.

## v0.1.0 extracted from source MUSH project at commit: _see git tag in private repo_
