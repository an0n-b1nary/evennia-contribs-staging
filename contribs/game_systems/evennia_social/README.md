# evennia-social

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before the contrib is submitted to `evennia/evennia`.

The social quality-of-life command layer for [Evennia](https://www.evennia.com/)
games: character profiles, player/venue discovery, private messaging,
ignore/mute, consensual teleportation, OOC room chat, and navigation
shortcuts.

This is a **leaf** layer — it depends on [evennia-posing](../evennia_posing)
but nothing depends on it. Install it once you have the pose pipeline in
place.

---

## What's included

| Name | Purpose |
|---|---|
| `SocialCharacterMixin` | Character mixin: profile/page/ignore/summon/home state, ignore-filter `msg()` |
| `SocialRoomMixin` | Room mixin: `hangout_type`, `allow_teleport` |
| `HANGOUT_TYPES` | Tuple of valid `+hangouts` categories |
| `commands/finger.py` | `CmdFinger` — profile view/edit, bio (`EvEditor`), followed themes |
| `commands/discovery.py` | `CmdWhere`, `CmdHangouts` — player/venue discovery |
| `commands/filtering.py` | `CmdIgnore` — account-level ignore list |
| `commands/messaging.py` | `CmdPage` — private OOC messaging |
| `commands/teleportation.py` | `CmdSummon`, `CmdJoin` — consensual teleport requests |
| `commands/ooc.py` | `CmdOoc` — OOC room chat |
| `commands/navigation.py` | `CmdOocTeleport`, `CmdHome` — instant shortcuts |
| `commands/tel.py` | `CmdTel` — enhanced `@tel` with fuzzy matching and access tiers |
| `commands/roomconfig.py` | `CmdRoomConfig` — designate a room as a hangout |
| `commands/roulette.py` | `CmdRoulette` — scene-idea stub for games to extend |
| `search.py` | `find_room()`, `find_room_for_player()` — fuzzy room matching |
| `social.py` | `is_staff()`, `get_connected_characters()`, `find_character()` |

**No Django models.** All state lives on Character/Room `AttributeProperty`
fields, so there is nothing to migrate.

---

## Installation

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_social&egg=evennia_social"
```

This pulls in `evennia-posing` automatically (hard dependency).

Add to `INSTALLED_APPS` in `server/conf/settings.py`:

```python
INSTALLED_APPS += ["evennia_posing", "evennia_social"]
```

No migrations to run — this contrib has no models.

---

## Integration recipe

### 1. Mix the Character and Room typeclasses

Put the social mixins **before** the posing mixins so ignored content is
filtered before header/highlight processing runs:

```python
from evennia_posing import PosingCharacterMixin, PosingRoomMixin
from evennia_social import SocialCharacterMixin, SocialRoomMixin

class Character(SocialCharacterMixin, PosingCharacterMixin,
                 ObjectParent, DefaultCharacter):
    ...

class Room(SocialRoomMixin, PosingRoomMixin, ObjectParent, DefaultRoom):
    ...
```

Both mixins override hook methods (`at_post_move`, `at_post_puppet`, `msg()`
on Character) and call `super()` to chain — the order above is required for
`msg()`'s cooperative behavior (ignore-filter runs first, then
header/highlight). Order between the two Room mixins does not matter since
they touch disjoint state.

### 2. Add the commands to your CharacterCmdSet

```python
from evennia_social.commands import (
    CmdFinger, CmdWhere, CmdHangouts, CmdIgnore, CmdPage,
    CmdSummon, CmdJoin, CmdOoc, CmdOocTeleport, CmdHome,
    CmdRoomConfig, CmdRoulette, CmdTel,
)

class CharacterCmdSet(CmdSet):
    def at_cmdset_creation(self):
        self.add(CmdFinger)
        self.add(CmdWhere)
        self.add(CmdHangouts)
        self.add(CmdIgnore)
        self.add(CmdPage)
        self.add(CmdSummon)
        self.add(CmdJoin)
        self.add(CmdOoc)
        self.add(CmdOocTeleport)
        self.add(CmdHome)
        self.add(CmdRoomConfig)
        self.add(CmdRoulette)
        self.add(CmdTel)   # replaces Evennia's stock @tel
```

### 3. Register the settings this contrib reads

```python
# server/conf/settings.py

# Dbref of your OOC hub room. Required for +ooc and +home's fallback.
OOC_ROOM_DBREF = "#2"

# "visited" (default) restricts player @tel to rooms they've visited or
# control; "open" allows any public room.
TELEPORT_MODE = "visited"
```

`+finger` needs no settings — its fields are self-contained
`AttributeProperty` state.

### 4. Designating hangouts

`+hangouts` only lists rooms that have been designated as hangouts. Use
`+roomconfig` (included above) to do that in-game:

```
+roomconfig/hangout bar       - designate the current room as a bar
+roomconfig/hangout/clear     - remove the designation
+roomconfig                   - show the current room's settings
```

Permitted for the room's owner (`control` access) or Builder+ staff. The
valid types are `evennia_social.HANGOUT_TYPES`. You can equivalently set
`room.hangout_type = "bar"` from Python.

### 5. Character seams this contrib provides

- `visited_rooms` — feeds `@tel`'s "visited" teleport mode.
- `home_room` — used by `+home`.
- `last_pager`, `pending_summon_requests` — reply/consent state for
  `page`/`+summon`/`+join`.
- `profile_*`, `followed_themes` — `+finger` state.

### 6. Optional attributes this contrib *reads* but does not own

Both are read with a defensive default, so a game that never defines them
behaves sensibly and needs to do nothing here.

| Attribute | On | Default assumed | Effect if you define it |
|---|---|---|---|
| `room_type` | Room | `"ic"` | `+where`/`+hangouts`/`+summon`/`+join`/`+home` treat `"staff"` rooms as staff-only, and `+where/ic` / `+where/ooc` filter on `"ic"`/`"ooc"`. Owned by no contrib — `evennia-rptracker` and `evennia-scenes` read it too, so it stays a game-level Room attribute. |
| `combat_state` | Character | `"idle"` | `@tel` refuses to teleport a character whose `combat_state == "in_combat"`, with a clearer message than a generic failure. Purely a nicety: if your game blocks combat movement in `at_pre_move` (the usual place), the move is rejected anyway. |
| `room_mood` | Room | `""` | Shown in `+hangouts` listings and `+roomconfig`'s display when set. |

---

## The severed `+ooc` scene-log coupling

The source project's OOC room-chat command called its scene-logging system
directly. That's the same kind of game-specific coupling `evennia_posing`
solved with the `pose_recorded` signal — so `CmdOoc` in this contrib fires
that same signal (`pose_type="ooc"`) instead of calling `record_pose()`.
This preserves the documented behavior ("OOC messages do not affect pose
order") while still giving your game's `pose_recorded` glue listener (see
evennia-posing README step 4) a chance to log OOC chat if it wants to:

```python
@receiver(pose_recorded)
def on_pose_recorded(sender, character, pose_text, pose_type, location, **kwargs):
    from evennia_scenes.capture import capture_to_scene
    capture_to_scene(character, pose_text, log_type=pose_type)  # pose_type may be "ooc"
```

---

## Screen-reader support (optional)

Install the `[accessibility]` extra to get plain-list renderings of
`+where` and `+hangouts` for players with `screenreader_mode` enabled:

```
pip install -e "...&egg=evennia_social[accessibility]"
```

Requires [evennia-accessibility](../../utils/evennia_accessibility). Falls
back to the standard fixed-width table when not installed — this is a soft
dependency, not a hard requirement.

---

## Version history

See [CHANGELOG.md](CHANGELOG.md).
