# evennia-regions

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before submission to `evennia/evennia`.

Geographic grouping of rooms into named regions for [Evennia](https://www.evennia.com/) games.
A `Region` is a named area; rooms join it via `RegionMembership` (many-to-many, with one
membership per room flagged the *primary* for scalar consumers). Staff manage region
definitions and membership with `+region`; all players can browse regions and check which
region their current room belongs to.

`evennia-regions` has zero model-level dependency on any other contrib — it is one of the
smallest, most independent contribs in this repo. Partner contribs (e.g. `evennia-lore`) reach
into regions via a soft app-label gate, not the other way around.

---

## What's included

| Component | Purpose |
|---|---|
| `Region`, `RegionMembership` | Core models |
| `CmdRegion` | `+region` command (list/view/here + staff create/edit/add-room/remove-room/here-add/primary) |
| Website surface (`[web]`) | `RegionListView`, `RegionDetailView`, Bootstrap 4 templates |
| DRF API (`[web]`) | `RegionViewSet` |

---

## Installation

**Core** (models + command, no web deps):

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_regions&egg=evennia_regions"
```

**With web + API surface:**

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_regions&egg=evennia_regions[web]"
```

Add to `INSTALLED_APPS` in `server/conf/settings.py`:

```python
INSTALLED_APPS += ["evennia_links", "evennia_regions"]
```

**Run migrations:**

```
evennia migrate evennia_regions
```

---

## Add commands to your CharacterCmdSet

```python
from evennia_regions.commands import CmdRegion

class CharacterCmdSet(CmdSet):
    def at_cmdset_creation(self):
        self.add(CmdRegion)
```

---

## Settings

| Setting | Default | Description |
|---|---|---|
| `REGIONS_STAFF_LOCK` | `"cmd:perm(Builder)"` | Staff lock for create/edit/add-room/remove-room/here-add/primary; also used by web views and API |
| `REGIONS_ROOM_VISIBILITY` | `None` | Dotted path to a `callable(room) -> bool` (**True means visible**) replacing the default room-visibility rule used by the member-room list and the API's staff-only member count |

---

## Room visibility

The region detail page and API withhold hidden rooms from non-staff visitors — otherwise a
region page could name a room a game intentionally hides elsewhere. Without a
`REGIONS_ROOM_VISIBILITY` override, a room is visible unless it is flagged
`room_type == "staff"` or `allow_teleport == "secret"`. Both flags are read from a typeclass
attribute *and* a plain Evennia Attribute (`room.db.room_type = "staff"`) — either storage
convention hides the room, and if the two disagree the hidden answer wins. A game that uses
neither flag sees every room as visible.

Games with a different hiding convention can replace the rule entirely. The callable returns
**True when the room may be shown** — note the polarity, it is easy to invert:

```python
# my_game/room_visibility.py
def is_room_web_visible(room):
    return not room.tags.has("secret", category="zone")

# settings.py
REGIONS_ROOM_VISIBILITY = "my_game.room_visibility.is_room_web_visible"
```

An override *replaces* the default rule rather than adding to it — if you want the built-in
staff/secret checks too, call them yourself from your own function.

**This setting fails closed.** If the path cannot be imported, resolves to `None`, or the
callable raises, every room is treated as hidden and the failure is logged. Falling back to
the default rule would look tidier but is a silent privacy leak: you only set this because
your rules are *stricter* than the default, so a typo would quietly publish exactly the rooms
you were withholding. A region page that suddenly lists no rooms is loud and diagnosable; one
that lists secret rooms is not.

Membership *counts* that would include hidden rooms are staff-only for the same reason —
publishing a raw count tells a visitor how many rooms they are not being shown.

---

## Web surface (requires `[web]`)

```python
from django.urls import include, path
urlpatterns += [path("regions/", include("evennia_regions.urls"))]
```

URL names (prefix with `evennia_regions:` when reversing): `region-list`, `region-detail`.

---

## REST API (requires `[web]`)

```python
from django.urls import include, path
urlpatterns += [path("api/v1/", include("evennia_regions.api.urls"))]
```

Generates `/api/v1/regions/` and `/api/v1/regions/<id>/`. Filter by `?name=<partial>`.

`member_count` is `null` in the response for non-staff callers — see "Room visibility" above.

---

## Programmatic API

```python
from evennia_regions.models import Region, RegionMembership

# Create a region (fires the region_created signal):
region = Region.create_region(name="The Ashfields", creator=character, description="Volcanic.")

# Assign a room. (region, room) is unique, so create() on an existing pair
# raises IntegrityError — use create_link(), which get_or_creates and fills
# in created_by/created_by_name from linked_by:
membership, created = RegionMembership.create_link(
    region, room, linked_by=character, room_name=room.key,
    is_primary=not RegionMembership.objects.filter(room=room).exists(),
)

# Resolve the single deterministic region for a room:
membership = RegionMembership.primary_for(room.pk)
```

---

## Partner integration

`evennia-lore` connects `connect_soft_ref_cleanup` for `Region` → its `LoreRegionLink` bridge,
gated on `LORE_REGIONS_APP_LABEL` (default `"evennia_regions"`) — no configuration needed on
the regions side. Other partner contribs may connect to the `region_created` signal
(`from evennia_regions import region_created`), which ships with zero receivers.

### The map tile overlay

Install `evennia-maps` alongside this contrib and every mapped room gains a region label
linking to its region page. There is nothing to configure: `RegionsConfig.ready()` sees the
map, connects `evennia_regions.integrations.maps.provide` to its `collect_tile_overlays`
signal, and answers with

```python
{"primary_region": {room_id: {"id": ..., "name": ...}}}
```

one query for the whole grid. Without `evennia-maps` installed nothing is imported and
nothing is connected.

The answer follows `RegionMembership.primary_for()` — flagged primary first, then earliest
membership — with **one deliberate difference: archived regions are skipped**. A region's
detail page 404s once it is archived, so a room whose flagged primary is archived falls
through to its next visible membership rather than linking the map to a dead page. Set
`REGIONS_MAPS_APP_LABEL` if your game registers the maps app under a different label.

---

## Version history

See [CHANGELOG.md](CHANGELOG.md).
