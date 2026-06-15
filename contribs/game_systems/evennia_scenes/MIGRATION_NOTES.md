# Migration Notes — evennia-scenes

This document records divergences between `evennia_scenes` (the extracted
contrib) and the source game's `world.scenes` app.

## Upgrading from `world.scenes` to `evennia_scenes`

If you have an existing `world.scenes` app that predates this contrib, create
a data migration to copy rows to the new tables, update any `ForeignKey`
references in your game that pointed to `world.scenes` models, then remove
the old app.

---

## Divergences from source `world.scenes`

### Abstract base imports

| Source (`world.scenes`) | Contrib (`evennia_scenes`) |
|---|---|
| `from world.utils.mixins import AbstractArchived, AbstractVersion` | `from evennia_links import AbstractArchived, AbstractVersion` |

### `ForeignKey` related_names

Renamed with an `evennia_` prefix to avoid Django E304 reverse-accessor clashes
when the source game's `world.scenes` app is installed alongside this contrib.

| Field | Source `related_name` | Contrib `related_name` |
|---|---|---|
| `Scene.room` | `"scenes"` | `"evennia_scenes"` |
| `Scene.creator` | `"created_scenes"` | `"evennia_created_scenes"` |
| `SceneParticipant.character` | `"scene_participations"` | `"evennia_scene_participations"` |

Update any queryset traversals in your game code that used these reverse names.

### `EditingMixin` source

`CmdLog` inherits `EditingMixin` from `evennia_links` rather than from a local
`world.scenes.commands` copy. The mixin API is identical; no call-site changes
are needed.

### Player-character check in `_resume`

| Source | Contrib |
|---|---|
| `hasattr(obj, "last_pose_time")` | `obj.has_account` |

The source used a game-specific attribute as a player-character sentinel.
`has_account` is the standard Evennia idiom for this check and avoids a
hard dependency on the game's character typeclass.

### Bridges removed: zero cross-domain FK

`evennia_scenes` ships **no** bridge models that reference other contrib
domains (e.g., `RPSession`, `XPLog`, `CalendarEvent`). If your game had
tables linking scenes to those systems, recreate them in your own
`world/links/` app (or the appropriate consuming contrib). The
`active_scene_id` integer-Attribute convention on rooms is this contrib's
only cross-system surface: consumers store it as an integer soft-reference,
never as a direct FK.

### No `publish` step

The source `world.scenes` had a separate publish command/field to make scenes
visible on the web. `evennia_scenes` removes this: closed PUBLIC and
POSE_PRIVATE scenes appear in the web log automatically. STAFF can still hide
a scene by setting it to VIEW_PRIVATE before closing. The `+scene/publish`
switch redirects users to the privacy model with an explanatory message.

### `register_room_entry` cannot be auto-wired

Evennia ships no room-receive signal (`at_object_receive` is a typeclass hook).
`ScenesConfig.ready()` therefore does **not** attempt to auto-wire this hook.
Your game must call `register_room_entry(room, character)` manually from
`Room.at_object_receive` (or equivalent). See `capture.py` module docstring.
