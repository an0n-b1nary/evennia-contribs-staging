# evennia-scenes

Scene logging system for [Evennia](https://www.evennia.com/) games.

Provides a full RP scene lifecycle (`+scene`/`+log`), automatic capture hooks,
a Bootstrap-compatible web log browser, and a DRF REST API.

---

## Requirements

- `evennia>=6.0`
- `evennia-links>=0.3` (provides `AbstractArchived`, `AbstractVersion`,
  `EditingMixin`)

Optional:
- `evennia-accessibility>=0.1` + `djangorestframework>=3.14` for web/API (`[web]` extra)

---

## Quick start

### 1. Install

```
pip install evennia-scenes[web]
```

### 2. Add to `INSTALLED_APPS`

```python
INSTALLED_APPS += [
    "evennia_links",   # must precede evennia_scenes
    "evennia_scenes",
]
```

### 3. Migrate

```
evennia migrate
```

### 4. Add commands to your CharacterCmdSet

```python
from evennia_scenes.commands import CmdScene, CmdLog

class CharacterCmdSet(CmdSet):
    def at_cmdset_creation(self):
        ...
        self.add(CmdScene)
        self.add(CmdLog)
```

### 5. Wire capture hooks in your typeclasses

```python
# In your Character typeclass (e.g. typeclasses/characters.py):
from evennia_scenes.capture import capture_to_scene

class Character(DefaultCharacter):
    def at_say(self, speech, msg_self=None, msg_location=None, **kwargs):
        super().at_say(speech, msg_self=msg_self, msg_location=msg_location, **kwargs)
        capture_to_scene(self, speech, log_type="say")

# In your Room typeclass:
from evennia_scenes.capture import register_room_entry

class Room(DefaultRoom):
    def at_object_receive(self, moved_obj, source_location, **kwargs):
        super().at_object_receive(moved_obj, source_location, **kwargs)
        if moved_obj.has_account:  # player character arriving
            register_room_entry(self, moved_obj)
```

### 6. Wire URLs (optional — requires `[web]` extra)

```python
# In your game's urls.py:
from django.urls import include, path

urlpatterns += [
    path("", include(("evennia_scenes.urls", "evennia_scenes"))),
    path("api/v1/", include("evennia_scenes.api.urls")),
]
```

---

## Integration contract

### `active_scene_id` convention

`evennia_scenes` stores the active scene's integer pk in
`room.active_scene_id` — an Evennia Attribute on the room object, accessed
via `room.active_scene_id`. It is set to `None` when no scene is active.

Cross-domain consumers (e.g., an RP-tracker contrib that links sessions to
scenes) should read this attribute and store it as an integer soft-reference
(`scene_id = models.IntegerField(null=True)`) rather than as a `ForeignKey`.
This avoids a hard dependency on `evennia_scenes` being installed.

### Capture hooks

Two functions in `evennia_scenes.capture` form the public hook API:

- **`capture_to_scene(character, content, log_type)`** — call from your
  character's pose/say/emit recording point. No-op if the room has no active
  scene.

- **`register_room_entry(room, character)`** — call from your room's
  `at_object_receive`. Auto-registers arriving player characters as scene
  participants. **Cannot be auto-wired**: Evennia ships no room-receive
  signal; you must call this manually.

### Why no bridges ship in this contrib

`evennia_scenes` deliberately owns zero cross-domain foreign keys. If you
want to link scenes to XP awards, calendar events, or RP sessions, create
bridge models in your own `world/links/` app. The `active_scene_id` integer
attribute is the only surface this contrib exposes to consumers.

---

## Settings

| Setting | Default | Description |
|---|---|---|
| `SCENES_STAFF_LOCK` | `"cmd:perm(Builder)"` | Lock expression for staff operations in `+scene` and `+log`. |
| `SITE_URL` | `""` | Optional absolute base URL for web links in MXP telnet clients (e.g. `"https://mygame.com"`). |

---

## Privacy tiers

| Tier | Web visibility | Who can pose |
|---|---|---|
| `public` | Everyone | Anyone in the room |
| `pose-private` | Everyone | Only invited characters (`+scene/invite`) |
| `view-private` | Only invited characters and staff | Only invited characters |

Closed `public` and `pose-private` scenes appear in the web log browser
automatically — no separate publish step is needed.

---

## Commands

### `+scene`

| Switch | Description |
|---|---|
| (none) | Show current room's active scene, or list recent scenes |
| `/open [<title>]` | Open a new scene in this room |
| `/close` | Pause the active scene |
| `/resume [<id>]` | Resume a closed scene |
| `/title <text>` | Set or change the scene title |
| `/desc` | Edit the scene description (EvEditor) |
| `/privacy <public\|pose-private\|view-private>` | Set scene privacy tier |
| `/invite <character>` | Invite a character to pose |
| `/join` | Join the active scene |
| `/leave` | Leave the active scene |
| `/info [<id>]` | View detailed scene info |

### `+log`

| Invocation | Description |
|---|---|
| `+log` | List your recent scenes |
| `+log <scene_id>` | View a scene's log entries |
| `+log <scene_id>=<page>` | View a specific page |
| `+log/edit <entry_id>` | Edit a log entry (your own, or staff) |
| `+log/history <entry_id>` | View edit history |
| `+log/rollback <entry_id>=<ver>` | Rollback to a version (staff only) |
| `+log/diff <entry_id>=<ver>` | View diff against a version |
| `+log/ic <scene_id>` | Show only IC entries (pose/emit/say) |
| `+log/ooc <scene_id>` | Show only OOC entries |

---

## License

BSD-3-Clause. See `LICENSE`.
