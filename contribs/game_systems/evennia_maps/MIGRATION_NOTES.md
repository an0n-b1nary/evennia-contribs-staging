# Migration Notes — evennia-maps

## Source inventory

Extracted from a private Evennia game project, in two phases: 0.1.0 covered
models, geometry, commands, listeners and the room mixin; 0.2.0 adds the
website, the REST API, the static assets and the tile-overlay seam.

| Source module | Contrib module | Notes |
|---|---|---|
| `world/maps/models.py` | `models.py` | Copied; `AbstractArchived` rebased from `evennia_links` (source game's own `world/utils/archiving.py`) |
| `world/maps/signals.py` | `signals.py` | Copied. `collect_tile_overlays` shipped in 0.1.0 declared but unconnected; 0.2.0 sends it once per render and the partner contribs answer it (see "Cross-domain glue became signal providers" below) |
| `world/maps/direction.py` | `direction.py` | Direct copy |
| `world/maps/terrain.py` | `terrain.py` | Direct copy |
| `world/maps/placement.py` | `placement.py` | Direct copy; import paths rebased to `evennia_maps.*` |
| `world/maps/layout.py` | `layout.py` | Direct copy; import paths rebased |
| `world/maps/listeners.py` | `listeners.py` | Direct copy; import paths rebased |
| `world/maps/apps.py` | `apps.py` | Rewritten for contrib conventions (`label = "evennia_maps"`); `connect_on_ready` now imported from `evennia_links` instead of the source game's `world/utils/listeners.py` |
| `world/maps/admin.py` | `admin.py` | Copy; RUF012 noqa added |
| `commands/maps.py` | `commands.py` | Copy; hardcoded `perm(Builder)` check replaced with `permissions.is_staff()` resolving `MAPS_STAFF_LOCK`, matching the `evennia-regions` convention; error strings changed from "Builder permissions" to "staff permissions" to match |
| `typeclasses/rooms.py` (terrain slice) | `typeclasses.py` (`MapsRoomMixin`) | New module — the source game's Room typeclass declares `terrain_tags`/`set_terrain`/`has_terrain` directly; a contrib cannot patch the game's Room, so this ships as a mixin, the same shape as `evennia_posing.PosingRoomMixin` / `evennia_social.SocialRoomMixin` |
| — | `permissions.py` | New module — `is_staff()` resolving `MAPS_STAFF_LOCK`, plus (0.2.0) `is_staff_user`, `is_room_web_visible` + `MAPS_ROOM_VISIBILITY`, and `read_room_attr`. Mirrors `evennia_regions.permissions` |
| `web/website/views/maps.py` | `views.py` | Copy; the source game's direct `Region`/`Scene` imports replaced by the overlay seam (below). The archive exclusion is written out explicitly rather than left to the default manager (below) |
| `web/api/views.py` (`PlaneViewSet`), `serializers.py`, `filters.py`, `pagination.py` | `api/` | Split out of the source game's shared API modules into a self-contained package with its own auth/permission/pagination/filter classes |
| `web/templates/website/plane_*.html`, `partials/_plane_svg.html` | `templates/evennia_maps/` | Copy; `cov-*` CSS classes renamed `evennia-maps-*`, breadcrumbs moved into the content block, sekizai `addtoblock` replaced (below) |
| `web/static/website/{js/cov_map.js,css/cov_map.css}` + `cov.css` §15 | `static/evennia_maps/` | Merged: the source game kept the SVG map's styles in its global stylesheet and only the Leaflet styles in a separate file. The contrib ships both in one self-contained file with no CSS custom properties, since a contrib cannot assume a host game defines any |
| — | `overlays.py` | New module — the `collect_tile_overlays` contract, the merge call, and the outbound-URL seam |
| `world/{scenes,lore,calendar}/maps_integration.py` | *(shipped in the partner contribs)* | The four providers live in `evennia_{regions,scenes,lore,calendar}/integrations/maps.py`, not here — same split as the source game's, which had already moved this glue into its owning domains before extraction |

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

**Cross-domain glue became signal providers.** This is the largest divergence, and the
one the whole web phase turns on. The source game's `PlaneViewSet.tiles()` imported
`world.scenes`, `world.lore`, `world.calendar` and `world.regions` directly to build its
six overlays. A standalone contrib cannot, and — more to the point — *should* not: five
of the six carry a privacy rule only the owning domain can apply. So the contrib sends
`collect_tile_overlays` once per render and merges whatever the installed partners answer.
The source game was restructured the same way first (its overlay helpers now live in
`world/<domain>/maps_integration.py` behind the same signal), so the two layouts mirror
each other rather than diverging.

The source game had no equivalent of the `primary_region` overlay key — it read
`RegionMembership` inline. Here that is `evennia-regions`' contribution like any other
partner's, which is what keeps `evennia-maps` and `evennia-regions` free of any dependency
edge in either direction.

**No sekizai `addtoblock`.** The source game's `base.html` renders a sekizai `"js"` block;
Evennia's stock `website/base.html` loads `sekizai_tags` but renders no such block, so an
`addtoblock` would have silently dropped the Leaflet and map scripts and the live map
would never have initialized. The contrib's template loads them with plain `<script>` tags
at the end of the content block instead.

**Outbound links are configurable and fail soft.** The source game's templates hardcoded
`{% url 'region-detail' %}` / `'scene-detail'` / `'calendar-event-detail'`. Those pages
belong to other contribs that may not be installed, so the contrib reverses them through
`MAPS_OVERLAY_URL_NAMES` and renders plain text where a route does not resolve. Same shape
for the tile feed via `MAPS_TILES_URL_NAME`.

**Archived planes are excluded explicitly, not left to the manager.** Every plane
queryset in `views.py` and `api/` spells out `.filter(is_archived=False)`. Today that is
redundant in both codebases — `AbstractArchived.objects` already excludes archived rows,
in `evennia_links` exactly as in the source game's `world/utils/archiving.py` — and it is
written out anyway because a contrib cannot see what a host game does to the model it
installs. The cost is one clause on an indexed boolean; the failure it forecloses is a
map that publishes planes the operator archived. The portal-marker code, which the source
game has no equivalent of, additionally checks the *destination* plane, so a marker cannot
route a visitor to an archived plane's 404.

**Terrain sprites namespaced.** `TERRAIN_TILESET` → `MAPS_TERRAIN_TILESET`, for the same
reason `MAPS_TERRAIN_PRECEDENCE` and `MAPS_DIRECTION_OFFSETS` were namespaced in 0.1.0.

**CSS classes renamed.** `cov-map-*` → `evennia-maps-*`, and the container id
`#cov-live-map` → `#evennia-maps-live`.

**Multi-line template comments fixed.** The source game's map templates carry the same
multi-line `{# ... #}` documentation comments this repo's partials did. Django's tag regex
has no `DOTALL` flag, so those are not comments: their text renders into the page, and any
`{% %}` inside them is parsed as a live tag. Fixed here (and across the other contribs
shipping copies of the same partials); the source game's own copies are worth the same
sweep.

**Commands ship inside the package, not in a `commands/` folder.** The source game keeps
every command module in one top-level `commands/` package (`commands/maps.py`,
`commands/regions.py`, …) and its cmdsets import from there. A contrib has no such folder
to put anything in — a game installs `evennia_maps`, so `CmdMap` has to be importable as
`evennia_maps.commands.CmdMap`. This is the same shape every other contrib in this repo
uses, and the reason the install instructions read
`from evennia_maps.commands import CmdMap` rather than pointing at a game-local module.
A game moving from the source layout deletes its `commands/maps.py` and changes one
import in its `CharacterCmdSet`; the command's syntax, switches and lock are unchanged.

**`is_room_web_visible()` is duplicated with `evennia-regions`, deliberately.** Both
contribs publish room names on a web page, and both therefore need the same question
answered — is this room fit to show a logged-out visitor? In the source game that lived
once, in a shared `web/website/permissions.py`. Sharing it here would mean one of these
two contribs depending on the other purely for a visibility predicate, and the pair is
otherwise dependency-free in both directions — which is the property that lets a game
install either one alone. So each ships the rule with its own settings hook
(`MAPS_ROOM_VISIBILITY` / `REGIONS_ROOM_VISIBILITY`), and a game that overrides one and
not the other gets exactly what it asked for. Keep the two implementations in step: the
`getattr`-plus-AttributeHandler read and the fail-closed override resolution are both
security-relevant, and a fix to one is a fix owed to the other.

## v0.1.0 extracted from source MUSH project at commit: _see git tag in private repo_
