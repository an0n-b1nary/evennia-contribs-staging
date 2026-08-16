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
| REST API | `PlaneViewSet` (`planes/`, `planes/<id>/tiles/`) — the tile feed the live map reads |
| `collect_tile_overlays` | The signal seam other contribs light map overlays through, with no import in either direction |

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
| `MAPS_TERRAIN_TILESET` | `{}` | `{terrain_key: sprite_url}` for the web map. A terrain with no sprite renders as a plain swatch |
| `MAPS_ROOM_VISIBILITY` | unset | Dotted path to a `callable(room) -> bool` replacing the default room-hiding rule. **Fails closed** — see below |
| `MAPS_OVERLAY_URL_NAMES` | see below | Route names the map links out to, merged over the defaults |
| `MAPS_TILES_URL_NAME` | `"api-plane-tiles"` | Route name of the tile feed. Set to `""` to turn the live map off |

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

The API viewsets carry their own authentication, permission, pagination and filter
classes, so they do not depend on your project's global `REST_FRAMEWORK` settings.
Tiles require an authenticated account; the SVG page does not.

**Leaflet is loaded from a CDN** (unpkg, 1.9.4, with an SRI hash) by
`plane_live_map.html`. Nothing is vendored into this package. If your site runs
without third-party CDN access, override that template and serve Leaflet yourself —
the static SVG map has no JavaScript dependency at all.

### Privacy

A map tile exposes an individual room's identity **and its position**, so tiles for
rooms flagged `room_type == "staff"` or `allow_teleport == "secret"` are dropped for
non-staff visitors, on the SVG page and the API alike. Tile *counts* are staff-only for
the same reason — a count tells a player exactly how many rooms they are not being
shown. `MAPS_ROOM_VISIBILITY` replaces the rule wholesale; a configured-but-unusable
value **hides every room** rather than falling back to the default, because a game only
overrides this when its rules are *stricter*, and silently reverting on a typo would
publish exactly what the operator was trying to withhold.

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

| Overlay key | Provided by | Rendered as |
|---|---|---|
| `primary_region` | `evennia-regions` | Tile label and link to the region page |
| `has_active_scene` | `evennia-scenes` | Highlighted tile border |
| `recent_scene_count` | `evennia-scenes` | Activity heatmap layer |
| `recent_scenes` | `evennia-scenes` | Log links in the tile popup |
| `has_lore` | `evennia-lore` | Lore pin layer |
| `upcoming_events` | `evennia-calendar` | Event links in the tile popup |
| `hangout_type` | *(read locally)* | Hangout marker layer |

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
`evennia_regions:region-detail`, `evennia_scenes:scene-detail`,
`evennia_calendar:calendar-event-detail`); a name that does not resolve renders as
plain text instead of a broken link.

**Installing a partner is not the same as mounting it.** The overlay data arrives as
soon as the partner app is in `INSTALLED_APPS` — the *link* out of the tile popup needs
that partner's website URLconf mounted too, because `overlay_url_templates()` reverses
each role and silently drops the ones that do not resolve. Install `evennia-scenes`
without mounting `evennia_scenes.urls` and recent logs render as unlinked text, with no
error anywhere to explain it. If you want the links, mount the pages.

---

## A worked example

`example_game/` in this repo is the reference wiring, and the only place the whole seam
can be shown working: it installs this contrib together with `evennia-regions`,
`-scenes`, `-lore` and `-calendar`, so all four overlay providers are present at once.

| What | Where |
|---|---|
| Settings, staff lock, terrain precedence — and **no overlay settings at all** | `server/conf/settings.py` |
| The four website includes and the two DRF routers | `web/website/urls.py`, `web/urls.py` |
| `MapsRoomMixin` on the game's Room typeclass | `typeclasses/rooms.py` |
| A seeded plane: one hand-placed origin tile, five more derived by `layout.plan()` | `world/sandbox/management/commands/seed_sandbox.py` |
| Proof that one collect returns all six overlay keys, from four different contribs | `world/sandbox/tests.py::TestMapOverlaySeam` |

That last one cannot live in this contrib's own suite, which has no partner contribs to
install — its overlay tests connect fakes instead, and deliberately detach whatever the
host game connected so they keep testing the map rather than the ecosystem.

---

## Version history

See [CHANGELOG.md](CHANGELOG.md).
