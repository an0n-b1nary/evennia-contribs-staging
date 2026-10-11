# evennia-maps

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before submission to `evennia/evennia`.

A 2D coordinate map of your game's rooms, auto-grown from canonical exits, for
[Evennia](https://www.evennia.com/) games. A `MapPlane` is a coordinate space (an overworld
surface, an underground layer, a standalone city interior); a `RoomTile` places one room at
`(x, y)` on one plane. As builders `dig`/`@tunnel` in a canonical direction (n/s/e/w/ne/nw/se/sw,
u/d), the destination room is placed automatically relative to its mapped source — the map grows
with the game, with no separate mapping step.

`+map` is the manual layer on top of that: bootstrapping a room onto a fresh plane, fixing a
placement conflict, pinning a landmark room so auto-placement/reflow never moves it, and
reconciling drift (`+map/check`, `+map/reflow`).

---

## What's included

| Component | Purpose |
|---|---|
| `MapPlane`, `RoomTile` | Core models |
| `direction`, `terrain`, `placement`, `layout` | Geometry: canonical direction vocabulary, terrain resolution, the single tile-write path, and a read-only BFS reflow engine |
| `CmdMap` | `+map` command (view for all players; place/move/unplace/pin/unpin/reflow/check for staff) |
| Exit-creation listener | Auto-places a newly-dug exit's destination when its source room is already mapped |
| `MapsRoomMixin` | Optional Room mixin providing `terrain_tags`/`set_terrain()`/`has_terrain()`, keeping a placed tile's terrain snapshot in sync |
| Website views | `/map/` plane list, `/map/<pk>/` static SVG grid, `/map/<pk>/live/` interactive Leaflet map |
| REST API | `PlaneViewSet` (`planes/`, `planes/<id>/tiles/`, `planes/<id>/tiles/<room_id>/detail/`) — the tile feed and room panel the live map reads |
| `collect_tile_overlays` | The signal seam other contribs light map overlays through, with no import in either direction |
| `collect_tile_detail` | The seam other contribs add sections to the live map's room panel through |

---

## Installation

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_maps&egg=evennia_maps"
```

Add to `INSTALLED_APPS` in `server/conf/settings.py`:

```python
INSTALLED_APPS += ["evennia_links", "evennia_maps"]
```

**Run migrations:**

```
evennia migrate evennia_maps
```

---

## Add the command to your CharacterCmdSet

```python
from evennia_maps.commands import CmdMap


class CharacterCmdSet(CmdSet):
    def at_cmdset_creation(self):
        self.add(CmdMap)
```

---

## Add the room mixin (optional, recommended)

Without it the map still works — placement, auto-placement, and reflow are all independent of
terrain — but `RoomTile.terrain` never gets a value, since nothing calls `set_terrain()` to
notify the map:

```python
from evennia_maps.typeclasses import MapsRoomMixin


class Room(MapsRoomMixin, ObjectParent, DefaultRoom): ...
```

If you also use `evennia_posing`/`evennia_social`'s room mixins, ordering relative to them
doesn't matter — `MapsRoomMixin` doesn't override `msg()` or any hook they touch.

---

## Settings

| Setting | Default | Description |
|---|---|---|
| `MAPS_STAFF_LOCK` | `"cmd:perm(Builder)"` | Staff lock for place/move/unplace/pin/reflow/check |
| `MAPS_DIRECTION_OFFSETS` | `{}` | Merged over `direction.DEFAULT_DIRECTION_OFFSETS` — add or override individual directions without redeclaring the whole table |
| `MAPS_TERRAIN_PRECEDENCE` | `[]` | Ordered list of terrain tag names; the first one present on a room's `terrain_tags` wins as `RoomTile.terrain` |
| `MAPS_TERRAINS` | `{}` | `{terrain_key: {"label", "color", "sprite"}}`, each field optional: how a terrain looks on the web map. See [Terrain display](#terrain-display) |
| `MAPS_TERRAIN_TILESET` | `{}` | `{terrain_key: sprite_url}`, the older sprite-only table; used when `MAPS_TERRAINS` gives a terrain no sprite |
| `MAPS_UNMAPPABLE_ROOM_TYPES` | `()` | `room_type` values the auto-placer must never map — an OOC lounge, a chargen suite. Digging a directional exit into one places nothing; `+map/place` still honours an explicit request, and `/check` reports the result. **Not a privacy setting** — see below |
| `MAPS_ROOM_VISIBILITY` | unset | Dotted path to a `callable(room) -> bool` replacing the default room-hiding rule. **Fails closed** — see below |
| `MAPS_OVERLAY_URL_NAMES` | see below | Route names the map links out to, merged over the defaults |
| `MAPS_TILES_URL_NAME` | `"api-plane-tiles"` | Route name of the tile feed. Set to `""` to turn the live map off |
| `MAPS_TILE_DETAIL_URL_NAME` | `"api-plane-tile-detail"` | Route name of the room panel's detail route. Set to `""` and the panel shows only what the tile feed carries |

---

## Canonical directions

Only exits whose key or an alias matches a canonical direction participate in layout —
free-form/flavor exits ("a rickety ladder") are ignored entirely, which is what makes an
auto-growing grid possible without banning creative exits. Both the abbreviation and full name
are registered for every direction (`n`/`north`, `u`/`up`, ...), since `dig north=New Room`
creates the full name with no alias. `in`/`out` are deliberately absent — portal-ness is inferred
from geometry (the destination lands on a non-stacked plane), not declared as a direction.

Vertical exits (`u`/`d`) move within the source plane's *zstack* — a label shared by planes that
represent aligned vertical layers (e.g. an `"overworld"` zstack with `elevation` -1/0/+1 for
underground/surface/sky). A blank `zstack` marks a standalone plane (a city interior reached
through a portal); vertical exits from a standalone plane don't participate in layout.

---

## Programmatic API

```python
from evennia_maps import placement, layout
from evennia_maps.models import MapPlane, RoomTile

plane = MapPlane.objects.create(name="Overworld")
tile = placement.place_tile(room, plane, 0, 0, actor=character)

# Reflow: BFS from an already-placed room, moving everything reachable
# via canonical exits to its geometrically-correct position.
result = layout.plan(room)  # dry run — no writes
placement.apply_plan(result, actor=character)  # writes exactly what plan() promised
```

`place_tile`/`move_tile`/`place_relative` all return either the written `RoomTile` or a
`placement.Conflict` (never raise on a held cell) — check `isinstance(result, placement.Conflict)`
before treating the return value as a tile.

---

## Web surface

Install the extra, then mount the routes:

```
pip install -e "evennia_maps[web]"
```

```python
# web/urls.py
urlpatterns += [
    path("map/", include(("evennia_maps.urls", "evennia_maps"))),
    path("api/v1/", include("evennia_maps.api.urls")),
]
```

Include the website routes **namespaced** as above — the templates reverse their own
routes through the `evennia_maps` namespace. Include the API router **without** a
namespace, or point `MAPS_TILES_URL_NAME` at whatever name you give it: the live map
page finds its tile feed by reversing that name, and renders an explanatory notice
rather than an empty canvas when it does not resolve.

| Route | Name | What it is |
|---|---|---|
| `/map/` | `evennia_maps:plane-list` | Paginated list of non-archived planes |
| `/map/<pk>/` | `evennia_maps:plane-detail` | Static inline-SVG grid; works with JavaScript off |
| `/map/<pk>/live/` | `evennia_maps:plane-live-map` | Leaflet map with elevation and overlay controls |
| `/api/v1/planes/` | `api-plane-list` | Plane list, with a visible-tile bounding box |
| `/api/v1/planes/<id>/tiles/` | `api-plane-tiles` | Paginated tile feed |
| `/api/v1/planes/<id>/tiles/<room_id>/detail/` | `api-plane-tile-detail` | One room's panel, for the requesting viewer. See [The room panel](#the-room-panel) |

The API viewsets carry their own authentication, permission, pagination and filter
classes, so they do not depend on your project's global `REST_FRAMEWORK` settings.
Tiles require an authenticated account; the SVG page does not.

**Leaflet is loaded from a CDN** (unpkg, 1.9.4, with an SRI hash) by
`plane_live_map.html`. Nothing is vendored into this package. If your site runs
without third-party CDN access, override that template and serve Leaflet yourself —
the static SVG map has no JavaScript dependency at all.

### Terrain display

`MAPS_TERRAINS` sets how each resolved terrain key looks:

```python
MAPS_TERRAINS = {
    "salt_pan": {"label": "Salt pan", "color": "#ece7dc", "sprite": "/static/terrain/salt_pan.svg"},
    "scrub": {"label": "Dry scrub", "color": "#8a7a4a"},  # colour only: a tinted swatch
}
```

- **sprite** draws over the cell, at any size; the map scales it. It falls back to
  `MAPS_TERRAIN_TILESET`, then to a swatch.
- **color** fills a cell with no sprite and colours its legend chip. Only hex
  values (`#rgb`, `#rgba`, `#rrggbb`, `#rrggbbaa`) are used; anything else falls back
  to the default swatch, since the value reaches SVG attributes.
- **label** names the terrain in tooltips and legends. It defaults to the key in
  sentence case (`salt_pan` → "Salt pan"). Keys are data; labels can change freely.

Both maps show a terrain key for the terrains present on the plane. The live map adds
a hover highlight that keeps the terrain's hue, a tooltip with the room, terrain,
region and activity badges ("Scene now", "Event soon", "Lore here", hangout type),
and a **Room list** button beneath the map. The list shows every visible room grouped
by region, each a button that opens the room's panel, which is the keyboard and
screen-reader route to everything the map shows.

### Browsable API with Evennia's API disabled

With `REST_API_ENABLED = False`, mounting this router still serves JSON, but
Evennia's global `rest_framework/api.html` theme tries to reverse the absent
`api:openapi` and `api:redoc` routes when a browser requests HTML. Add a
game-level override at **`web/templates/rest_framework/api.html`**:

```django
{% extends "rest_framework/base.html" %}
{% block userlinks %}
  {{ block.super }}
  {% url 'api:openapi' as openapi_url %}
  {% url 'api:redoc' as redoc_url %}
  {% if openapi_url %}<li><a href="{{ openapi_url }}">Schema</a></li>{% endif %}
  {% if redoc_url %}<li><a href="{{ redoc_url }}">Documentation</a></li>{% endif %}
{% endblock %}
```

Extend DRF's `base.html` directly; extending `rest_framework/api.html` inherits
the unconditional Evennia links again. The `as` form makes each reverse
optional, so this override also works when Evennia's API is enabled later.
The game template directory must precede app templates in your Django template
loader configuration (the standard Evennia game scaffold already does this).
Restart the web server and check an authenticated HTML request to the router
root and resource list; successful JSON responses alone do not verify this.

### Privacy

A map tile exposes an individual room's identity **and its position**, so tiles for
rooms flagged `room_type == "staff"` or `allow_teleport == "secret"` are dropped for
non-staff visitors, on the SVG page and the API alike. Tile *counts* are staff-only for
the same reason — a count tells a player exactly how many rooms they are not being
shown. `MAPS_ROOM_VISIBILITY` replaces the rule wholesale; a configured-but-unusable
value **hides every room** rather than falling back to the default, because a game only
overrides this when its rules are *stricter*, and silently reverting on a typo would
publish exactly what the operator was trying to withhold.

### Off-map room types

`MAPS_UNMAPPABLE_ROOM_TYPES` and `MAPS_ROOM_VISIBILITY` sound similar and do
opposite things. Visibility **hides a tile that exists**; this setting **stops the
tile existing**. For a room that is not part of the physical world at all — an OOC
lounge, a chargen suite — hiding is the wrong tool: the row still holds its cell
under the `(plane, x, y)` unique constraint, `layout.plan()` still routes around
it, and `+map/check` still reports it, leaving an invisible occupied hole in the
grid.

It is enforced on exactly one path, the exit-creation listener, because that is
the one placement nobody asked for — the tile is a side effect of `dig`. A builder
who types `+map/place` on such a room meant it, so the command is left alone and
`+map/check` reports the tile instead. Block the accident, report the decision.

This is game cosmology, not privacy, which is why it is configuration and defaults
to empty while the `"staff"` / `"secret"` privacy flags stay hardcoded and
fail-closed.

If you also run `evennia-regions`, point `MAPS_ROOM_VISIBILITY` and
`REGIONS_ROOM_VISIBILITY` at the same callable. The two contribs deliberately keep
their own copy of this predicate rather than depending on each other, and a room hidden
on one surface but named on the other is not hidden.

---

## Overlays: how other contribs light up the map

`evennia_maps` knows where rooms are. It knows nothing about scenes, lore, events or
regions — and must not, because most of what those would put on a map carries a privacy
rule only the owning domain can apply correctly. A scene's room id is a bare pk with no
privacy dimension; pin a marker from it and a view-private scene announces itself to
every visitor.

So the map **asks** instead. Once per render — never per tile — it sends
`collect_tile_overlays` with the room ids being drawn and whether the caller is staff.
Each installed partner answers for the rooms it has data about, under its own privacy
rule, and the answers are merged. There is nothing to configure: install a partner and
its overlay appears, uninstall it and the overlay is simply absent.

The calendar's ``is_staff_event`` flag is a public lottery RSVP mode, not a
privacy tier. Calendar overlays therefore return those events to both player
and staff renders; providers continue to own their domain-specific privacy
rules.

| Overlay key | Provided by | Rendered as |
|---|---|---|
| `primary_region` | `evennia-regions` | Tile label and link to the region page |
| `has_active_scene` | `evennia-scenes` | Highlighted tile border |
| `active_scenes` | `evennia-scenes` | Live log links in the room panel and static map |
| `recent_scene_count` | `evennia-scenes` | Activity heatmap layer |
| `recent_scenes` | `evennia-scenes` | Log links in the room panel |
| `has_lore` | `evennia-lore` | Lore pin layer |
| `upcoming_events` | `evennia-calendar` | Event links in the room panel |
| `present` | `evennia-social` | "N here" in the tooltip and names in the room panel (live map only) |
| `hangout_type` | *(read locally)* | Hangout marker layer |

The live map also sends `viewer`: the character the visitor is playing on the
website (`evennia_links.characters.web_character`), or `None`. The SVG map never
sends one. Providers that don't need it ignore it through `**kwargs`.

`present` lists the connected characters in a room. The provider has already applied
its presence rule (players see only characters who are findable, or who are in the
same room as the viewer's connected character; staff see everyone with a marker), so
the map shows what it's given. It appears only on the live map, whose tile API
requires a login. The SVG map can be served to logged-out visitors, so it never shows
who is where.

`hangout_type` is the exception: a bare room attribute with no table and no privacy
rule, read duck-typed exactly as `terrain_tags` is. It happens to be an
`evennia-social` room attribute, but this contrib neither depends on nor checks for
that contrib.

### Writing a provider

```python
# yourcontrib/integrations/maps.py
def provide(sender, room_ids, staff, **kwargs):
    """One bulk query per overlay. Never per tile."""
    return {"has_lore": {rid: True for rid in _rooms_with_lore(room_ids, staff=staff)}}
```

```python
# yourcontrib/apps.py ready()
maps_label = getattr(settings, "YOURS_MAPS_APP_LABEL", "evennia_maps")
if apps.is_installed(maps_label):
    from evennia_maps.signals import collect_tile_overlays
    from yourcontrib.integrations import maps as maps_overlays

    collect_tile_overlays.connect(
        maps_overlays.provide, dispatch_uid="yourcontrib.tile_overlays"
    )
```

Keep the `evennia_maps` import **inside** the gated branch, so a game without the map
never imports it. Three rules for providers:

1. **One bulk query per overlay, flat in tile count.** A 500-room plane renders in one
   request; a provider that looks something up per tile turns that into 500.
2. **Write disjoint keys.** Receiver order is not guaranteed, so two providers claiming
   the same key is a bug in the providers, not something the map arbitrates.
3. **Apply your own privacy rule** using the `staff` flag. The map will not second-guess
   you, and cannot.

A provider that raises is logged and skipped — its overlay goes absent and the map
still renders. Outbound links are reversed from `MAPS_OVERLAY_URL_NAMES` (defaults:
`evennia_regions:room-detail`, `evennia_regions:region-detail`,
`evennia_scenes:scene-detail`,
`evennia_calendar:calendar-event-detail`); a name that does not resolve renders as
plain text instead of a broken link.

**Installing a partner is not the same as mounting it.** The overlay data arrives as
soon as the partner app is in `INSTALLED_APPS` — the *link* out of the tile popup needs
that partner's website URLconf mounted too, because `overlay_url_templates()` reverses
each role and silently drops the ones that do not resolve. Install `evennia-scenes`
without mounting `evennia_scenes.urls` and recent logs render as unlinked text, with no
error anywhere to explain it. If you want the links, mount the pages.

---

## The room panel

Clicking a tile on the live map, or its button in the room list, opens a panel for that
room: beside the map on a wide screen, a bottom sheet on a narrow one. It closes with
its button or Escape, and focus goes back to the room-list button that opened it.

The tile feed stays small, enough for tooltips and pins. The panel asks the detail
route about **one room**, which is where content that depends on who is looking can
live. The route 404s for a room that isn't on the plane or that the caller may not see,
using the same visibility rule as the tiles.

The panel has two sources:

- **Overlays, for one room.** The route collects `collect_tile_overlays` for the one
  room, with the viewer, and shows the room's description excerpt, terrain, region,
  who's here, live scenes, recent logs and upcoming events, each linked where the
  partner's pages are mounted.
- **Sections, from `collect_tile_detail`.** A partner returns whole blocks the map
  renders without knowing what they mean, so a new partner adds one without a maps
  release.

```python
# yourcontrib/integrations/maps.py
def provide_detail(sender, room_id, room, staff, viewer=None, **kwargs):
    return {
        "yours": {
            "title": "Notices",                # required
            "order": 70,                       # lower sorts first; default 100
            "summary": "Two notices here.",    # optional line under the title
            "items": [                         # optional
                {"label": "Gate closed", "url": "/notices/4/", "note": "until dusk"},
                {"label": "Sealed order", "locked": True},
            ],
        }
    }
```

Connect it the same way as an overlay provider, and look the signal up with `getattr`
so your contrib still loads beside an evennia-maps older than 0.9:

```python
from evennia_maps import signals as maps_signals

collect_tile_detail = getattr(maps_signals, "collect_tile_detail", None)
if collect_tile_detail is not None:
    collect_tile_detail.connect(maps_detail.provide_detail, dispatch_uid="yourcontrib.tile_detail")
```

The map validates sections rather than trusting them:

- a section without a title, or an item without a label, is dropped;
- a URL that isn't a site-relative path (`/...`) is dropped;
- each section keeps at most 25 items;
- every string is set as text, never as markup.

As with overlays, a provider that raises is logged and skipped, and its privacy rule
is its own. One collect costs the same however big the plane is.

Shipped sections, in display order:

| Section | Provided by | Shows |
|---|---|---|
| `lore` (40) | `evennia-lore` | Entries tied to the room's region; the ones the viewer's character knows are linked, public ones it doesn't are listed locked, restricted ones it doesn't are only counted |
| `plots` (50) | `evennia-plots` | Plot threads with a scene in this room, under scenes' and plots' privacy rules |
| `resources` (60) | `evennia-rp-resources` | What gathering in this terrain can turn up, once resources are revealed |

Without the detail route (`MAPS_TILE_DETAIL_URL_NAME = ""`), or if the request fails,
the panel shows what the tile feed already carries and no sections. A game template
from before the panel, with no `<aside id="evennia-maps-panel">`, gets a plain popup
naming the room.

---

## A worked example

`example_game/` in this repo is the reference wiring, and the only place the whole seam
can be shown working: it installs this contrib together with `evennia-regions`,
`-scenes`, `-lore`, `-calendar` and `-social`, so all five overlay providers are present at once.

| What | Where |
|---|---|
| Settings, staff lock, terrain precedence — and **no overlay settings at all** | `server/conf/settings.py` |
| The four website includes and the two DRF routers | `web/website/urls.py`, `web/urls.py` |
| `MapsRoomMixin` on the game's Room typeclass | `typeclasses/rooms.py` |
| A seeded plane: one hand-placed origin tile, five more derived by `layout.plan()` | `world/sandbox/management/commands/seed_sandbox.py` |
| Proof that one collect returns all eight overlay keys, from five different contribs | `world/sandbox/tests.py::TestMapOverlaySeam` |
| The room panel for a seeded room, with lore, plots and resources sections from real partners | `world/sandbox/test_map_panel.py` |

That last one cannot live in this contrib's own suite, which has no partner contribs to
install — its overlay tests connect fakes instead, and deliberately detach whatever the
host game connected so they keep testing the map rather than the ecosystem.

## Theming

Every colour in this contrib's stylesheet is a shared `--evennia-color-*`
token with its usual colour as the fallback, so the pages look the same
until your game sets one. Set them on `:root` in your own stylesheet to
retheme these pages along with the other contribs'. The token list and an
example are in [evennia-accessibility's README](../../utils/evennia_accessibility/README.md#theme-tokens).

The map has its own palette as well, as `--evennia-maps-*` properties with
these defaults. Leaflet draws some live-map cells itself, with colours set from
script rather than CSS, so the script reads `tile`, `edge`, `hover`, `active`,
`portal` and `portal-fill` from the same properties when the map loads.

| Property | Default | Used for |
|---|---|---|
| `--evennia-maps-canvas` | `#1b1b1b` | the live map's background, hangout marker text |
| `--evennia-maps-tile` | `#3a3a3a` | a cell whose terrain has neither art nor a colour |
| `--evennia-maps-edge` | `rgba(255, 255, 255, 0.25)` | cell edges, the terrain key's border |
| `--evennia-maps-frame` | `rgba(255, 255, 255, 0.15)` | the border around either map |
| `--evennia-maps-hover` | `#ffffff` | the edge of the cell under the pointer |
| `--evennia-maps-active` | `#ffce54` | the edge of a cell with a scene running |
| `--evennia-maps-active-glow` | `rgba(255, 206, 84, 0.8)` | that cell's glow |
| `--evennia-maps-portal` | `#b39ddb` | a portal cell's edge and arrow |
| `--evennia-maps-portal-fill` | `#2b2536` | a portal cell's fill (script only) |
| `--evennia-maps-swatch-edge` | `rgba(255, 255, 255, 0.35)` | legend swatch borders |
| `--evennia-maps-badge-bg` | `#2d2d2d` | tooltip badges |
| `--evennia-maps-panel-bg` | `rgba(27, 27, 27, 0.9)` | the terrain key panel |
| `--evennia-maps-panel-text` | `#f0f0f0` | text on badges and the terrain key |
| `--evennia-maps-error` | `rgba(255, 128, 128, 0.4)` | the load-error banner's border |
| `--evennia-maps-heat` | `#ff7043` | the activity heatmap |
| `--evennia-maps-lore` | `#ffd54f` | lore pins |
| `--evennia-maps-hangout` | `#80cbc4` | hangout markers |

Terrain colours come from `MAPS_TERRAINS`, not from these.

## Guide pages

The `guides/` directory holds player guide pages for
[evennia-guides](../../utils/evennia_guides/README.md): `map`. They explain the
system to players in general terms, without exact numbers, and link only to
pages this contrib or its required dependencies ship. With evennia-guides
installed they appear on its web guide; without it they're ignored. To restate
one for your game, add a page with the same key to `GUIDES_DIRS`.

---

## Version history

See [CHANGELOG.md](CHANGELOG.md).


## Private previews and cross-plane transplants

`MAPS_ROOM_VISIBILITY` also accepts `(room, viewer) -> bool` (including a
keyword-only `viewer`); the original `(room) -> bool` form remains supported.
The viewer is the selected character on web requests, the caller in-game,
and `None` for anonymous/public rendering. Errors hide the room. Staff keep
the existing command/web staff override; the callback need not implement it.
If regions is installed, set `REGIONS_ROOM_VISIBILITY` to the same callback.

`MapPlane.visibility_room` optionally anchors **plane access** to a room's
visibility. This guards names, direct URLs, empty planes, floor lists, portal
markers and API metadata before tiles are filtered. Existing planes with no
anchor keep their existing behavior. Deleting an anchor cascades to its planes
and map tiles, so an orphaned draft cannot become public accidentally; other
rooms are not deleted. Access to a plane never implies permission to edit it.

```python
from evennia_maps.placement import create_private_stack

# First set entry_room's privacy flags/ACL in your project's service.
plane = create_private_stack(entry_room, "A private draft", actor=proposer)
```

Each stack has a unique label and supports vertical layout. Floors created by
`resolve_stacked_plane` or auto-placement inherit the privacy anchor. Room
visibility still applies separately, so private floor rooms also need your
project's flags/ACL. After approval, the project service changes those rules
deliberately. Keep the entry anchor on an interior stack so portal markers
continue to recognize it after promotion.

```python
from evennia_maps.transplant import plan_transplant, apply_transplant

preview = plan_transplant(
    frontier_rooms, entry_room=entry, anchor_room=anchor, direction_name="north"
)
# preview.moves: room, target plane (possibly PendingPlane), x, y
# preview.conflicts: blockers; preview.adjacency: unconnected room pairs
if not preview.conflicts:
    apply_transplant(preview, actor=reviewer)
```

The planner is read-only, including missing destination floors. It translates
only the explicit room set, preserves relative coordinates/elevations, checks
internal compass geometry, and reports pins, collisions, occupied attachment
directions and archived planes. A standalone target cannot accept multiple
floors. Adjacency includes configured compass/vertical neighbors, excludes
already connected pairs and the intended entry/anchor connection, and warns
without blocking. Source and target coordinate spaces must differ.

Application re-plans under a transaction and rejects changed source tiles,
anchor coordinates, target occupancy/floors, pins or relevant exits. Every
selected tile moves or none does; tile primary keys survive. Destination floor
creation rolls back with the move, and tile notifications run after commit
(and disappear on an outer rollback). Catch `ValidationError` for conflicts
or stale previews and `IntegrityError` for concurrent cell claims, then request
a fresh preview. Database row locks serialize cooperating writers where
supported. Signals do not promise durable external delivery.

These are trusted service helpers: callers must authorize their actor, choose
and freeze the submitted room set, and handle project review. They create no
attaching exits, rooms, ownership or Jobs decisions. Construction commands and
project lifecycle belong to the consuming building package.

The plan is a full geometry report for trusted callers. A player-facing build
check must redact hidden neighbor identities before rendering it. The sandbox
report is Builder-only.
