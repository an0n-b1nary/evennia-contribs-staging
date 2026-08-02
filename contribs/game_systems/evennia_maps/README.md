# evennia-maps

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before submission to `evennia/evennia`. This release is the **core phase** — no web/API surface yet (see "Roadmap" below).

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

## Roadmap

This release covers models, geometry, the in-game command, auto-placement, and the room mixin.
Not yet shipped, in a later phase of this extraction:

- Website views (SVG map render, live Leaflet map with elevation control)
- REST API (`PlaneViewSet`)
- The `collect_tile_overlays` signal seam, letting `evennia-scenes`/`evennia-lore`/
  `evennia-calendar` light up map overlays (active scenes, lore, upcoming events) without
  `evennia-maps` importing any of them
- `MAPS_ROOM_VISIBILITY` + `is_room_web_visible()` (mirrors `evennia_regions`'s hardened,
  fail-closed version of the same seam)

`collect_tile_overlays` is already declared in `signals.py` so partner contribs can be written
against a stable import path; nothing sends or connects to it yet.

---

## Version history

See [CHANGELOG.md](CHANGELOG.md).
