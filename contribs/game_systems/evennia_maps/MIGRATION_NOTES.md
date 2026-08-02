# Migration Notes — evennia-maps

## Source inventory

Extracted from a private Evennia game project. This is the **core phase**
of the extraction: models, geometry, commands, listeners, and the room
mixin. The website/API surface and SVG/Leaflet static assets are a
later phase — see "What's not shipped yet" below.

| Source module | Contrib module | Notes |
|---|---|---|
| `world/maps/models.py` | `models.py` | Copied; `AbstractArchived` rebased from `evennia_links` (source game's own `world/utils/archiving.py`) |
| `world/maps/signals.py` | `signals.py` | Copied; `collect_tile_overlays` carried over as a declared-but-unconnected signal — the web tile-overlay seam is a later phase |
| `world/maps/direction.py` | `direction.py` | Direct copy |
| `world/maps/terrain.py` | `terrain.py` | Direct copy |
| `world/maps/placement.py` | `placement.py` | Direct copy; import paths rebased to `evennia_maps.*` |
| `world/maps/layout.py` | `layout.py` | Direct copy; import paths rebased |
| `world/maps/listeners.py` | `listeners.py` | Direct copy; import paths rebased |
| `world/maps/apps.py` | `apps.py` | Rewritten for contrib conventions (`label = "evennia_maps"`); `connect_on_ready` now imported from `evennia_links` instead of the source game's `world/utils/listeners.py` |
| `world/maps/admin.py` | `admin.py` | Copy; RUF012 noqa added |
| `commands/maps.py` | `commands.py` | Copy; hardcoded `perm(Builder)` check replaced with `permissions.is_staff()` resolving `MAPS_STAFF_LOCK`, matching the `evennia-regions` convention; error strings changed from "Builder permissions" to "staff permissions" to match |
| `typeclasses/rooms.py` (terrain slice) | `typeclasses.py` (`MapsRoomMixin`) | New module — the source game's Room typeclass declares `terrain_tags`/`set_terrain`/`has_terrain` directly; a contrib cannot patch the game's Room, so this ships as a mixin, the same shape as `evennia_posing.PosingRoomMixin` / `evennia_social.SocialRoomMixin` |
| — | `permissions.py` | New module — `is_staff()` only, resolving `MAPS_STAFF_LOCK`. Mirrors `evennia_regions.permissions.is_staff()`. Web-facing helpers (`is_staff_user`, `is_room_web_visible` + `MAPS_ROOM_VISIBILITY`) land with the website phase |

## What's not shipped yet

The source game's `web/website/views/maps.py`, `web/api/views.py` (`PlaneViewSet`),
templates, and `static/*/leaflet` assets are **not** part of this release. That surface —
SVG rendering, the live Leaflet map, the DRF API, and the tile-overlay signal seam that
lets `evennia-scenes`/`evennia-lore`/`evennia-calendar` light up overlays without
`evennia-maps` importing any of them — is a separate phase of this extraction. Until then,
`evennia-maps` is a fully functional in-game system (`+map`, auto-placement on `dig`,
`+map/reflow`) with no web presence.

## Key divergences from source game

**Staff permission configurable via `MAPS_STAFF_LOCK`.** The source game's `+map`
hardcoded `caller.locks.check_lockstring(caller, "perm(Builder)")` with no settings hook.
The contrib introduces `MAPS_STAFF_LOCK` (default `"cmd:perm(Builder)"`) via a
`permissions.is_staff()` helper, matching `evennia_regions`'s `REGIONS_STAFF_LOCK`
convention rather than inventing a new one.

**`MapsRoomMixin` is new.** The source game has no equivalent module — `terrain_tags`,
`set_terrain()`, and `has_terrain()` live directly on its Room typeclass, alongside
unrelated game state. Splitting them into a mixin is what makes the terrain half of this
contrib usable without inheriting the source game's whole Room class. A game that skips
the mixin still gets a working map (placement, auto-placement, reflow are all
independent of terrain); `RoomTile.terrain` just never gets a value, since nothing calls
`set_terrain()` to fire `terrain_changed`. A game with its own terrain concept can send
that signal itself (`evennia_maps.signals.terrain_changed.send(sender=Room, room=room)`)
after updating its own terrain state, and the listener will refresh the snapshot the
same way.

**Settings namespaced under `MAPS_`.** The source game reads `DIRECTION_OFFSETS` and
`TERRAIN_PRECEDENCE`; the contrib reads `MAPS_DIRECTION_OFFSETS` and
`MAPS_TERRAIN_PRECEDENCE`. Unprefixed names are fine inside one game, but a contrib
shares `settings.py` with every other installed app, and `DIRECTION_OFFSETS` in
particular is a name a game or a second mapping contrib could plausibly want. Every other
setting across these contribs is already `<PREFIX>_*` (`MAPS_STAFF_LOCK`,
`REGIONS_STAFF_LOCK`, `LORE_*`); these two now match. A game moving from the source
layout renames the two settings — no data or schema change.

**Constraint name prefixed with `evennia_maps_`.** `maps_one_plane_per_elevation` is
renamed to `evennia_maps_one_plane_per_elevation` for the same collision-avoidance reason
`evennia-lore`/`evennia-regions` rename theirs.

**FK dependency pinned to `("objects", "__first__")`.** Portable across Evennia installs.

## v0.1.0 extracted from source MUSH project at commit: _see git tag in private repo_
