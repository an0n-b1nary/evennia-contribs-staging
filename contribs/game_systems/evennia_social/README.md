# evennia-social

`SOCIAL_IGNORE_MUTE_ALIAS` defaults to `True`, retaining `+mute` as an alias
for personal `+ignore`. Set it to `False` when installing Moderation's staff
`+mute` command, then reload the command sets. `+ignore` remains available.

Managed property integration uses Links' optional `LINKS_ROOM_TRAVEL` and
`LINKS_ROOM_VISIBILITY` providers. A three-way travel answer can explicitly
admit a character to a private, unvisited home or deny entry; `None` preserves
existing teleport rules. Home arrival and summon/join acceptance recheck
admission, so an occupant's consent never substitutes for the owner's grant.
Remote presence and empty hangout discovery respect managed-room visibility;
self, same-room and existing staff visibility remain intact. Individual
unfindable/scene privacy continues to apply. Social imports no property package.

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before the contrib is submitted to `evennia/evennia`.

The social quality-of-life command layer for [Evennia](https://www.evennia.com/)
games: character profiles, player/venue discovery, private messaging,
ignore/mute, consensual teleportation, OOC room chat, navigation
shortcuts, and room mood.

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
| `commands/presence.py` | `CmdUnfindable`, `CmdWho` — per-character presence and a `who` that honours staff `dark` |
| `integrations/maps.py` | Who's here on the live map (`present`), wired only when `evennia-maps` is installed |
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
    CmdRoomConfig, CmdRoulette, CmdTel, CmdMood, CmdUnfindable,
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
        self.add(CmdMood)
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

### 5. Room mood

A mood is one line of atmosphere shown under the room's description:

```
+mood                       - show the mood and who set it
+mood Rain hammers the shutters; the fire is low.
+mood/clear                 - remove it
```

Setting or clearing it is announced to the room. `SocialRoomMixin` renders it
in `look` as `[Mood] <text> (set by <name>)`.

Who can set it:

| Situation | Who |
|---|---|
| Always | The room's owner (`control` access) and Builder+ staff |
| A public scene is running in the room | Also any active participant (not observers) |
| A scene with any other privacy tier is running | Also its host, and no one else |

The scene rules need [evennia-scenes](../evennia_scenes); without it only
owners and staff can set a mood. If your scenes app has a different label, set
`SOCIAL_SCENES_APP_LABEL`. A privacy tier this contrib doesn't recognise is
treated as private. Closing a scene does not clear the mood.

From Python: `evennia_social.mood.set_mood(room, text, setter)`,
`clear_mood(room)`, and `can_set_mood(character, room)`.

### 6. Character seams this contrib provides

- `visited_rooms` — feeds `@tel`'s "visited" teleport mode.
- `home_room` — used by `+home`.
- `last_pager`, `pending_summon_requests` — reply/consent state for
  `page`/`+summon`/`+join`.
- `profile_*`, `followed_themes` — `+finger` state.

### 7. Optional attributes this contrib *reads* but does not own

Both are read with a defensive default, so a game that never defines them
behaves sensibly and needs to do nothing here.

| Attribute | On | Default assumed | Effect if you define it |
|---|---|---|---|
| `room_type` | Room | `"ic"` | `+where`/`+hangouts`/`+summon`/`+join`/`+home` treat `"staff"` rooms as staff-only, and `+where/ic` / `+where/ooc` filter on `"ic"`/`"ooc"`. Owned by no contrib — `evennia-rptracker` and `evennia-scenes` read it too, so it stays a game-level Room attribute. |
| `combat_state` | Character | `"idle"` | `@tel` refuses to teleport a character whose `combat_state == "in_combat"`, with a clearer message than a generic failure. Purely a nicety: if your game blocks combat movement in `at_pre_move` (the usual place), the move is rejected anyway. |

---

## Presence: unfindable and dark

Each character chooses whether it can be found from afar, with `+unfindable`:

| Setting | `+where`, venue counts, web maps | `who` | Who can set it |
|---|---|---|---|
| `findable` (default) | shown | shown | anyone |
| `unfindable` | hidden | shown | anyone |
| `dark` | hidden | hidden | staff (`perm(Builder)`) |

Being in the same room always reveals a character, and staff see through both
settings (with a marker in `+where`). Unfindable is privacy from people who
aren't there, not invisibility.

Every presence surface asks `evennia_social.presence`, so they can't disagree.
In-game code calls `is_findable(character, viewer)` (location) or
`is_listed(character, viewer)` (online at all); web code with no in-game viewer
calls `is_publicly_findable(character)` / `is_publicly_listed(character)`.

`who` lives in the AccountCmdSet. To leave dark staff out of it, add this
contrib's `CmdWho` there; it replaces Evennia's command of the same key:

```python
from evennia_social.commands import CmdWho

class AccountCmdSet(default_cmds.AccountCmdSet):
    def at_cmdset_creation(self):
        super().at_cmdset_creation()
        self.add(CmdWho)
```

Add `CmdUnfindable` to the CharacterCmdSet with the other social commands.

### Who's here on the live map

With [`evennia-maps`](../evennia_maps/README.md) 0.7 or later installed, this
contrib answers the map's `collect_tile_overlays` seam with `present`: the
names of connected characters in each room. There's nothing to configure. When
both apps are installed, `ready()` connects the provider
(`integrations/maps.py`). Set `SOCIAL_MAPS_APP_LABEL` if your map app has a
different label.

The map follows the table above. Players see only findable characters, in
both the names and the "N here" count. Staff see everyone, with the
`(unfindable)` / `(dark)` marker. From evennia-maps 0.9 the live map passes
the viewer, the character the visitor plays on the website, and the same-room
rule applies too: if that character is connected and standing in the room, the
names and count there include unfindable characters, as `look` would. A
character that isn't connected in-game doesn't count as being there, even if
your game leaves offline characters in rooms. Names appear only on the live
map, which requires a login, never on the public SVG map. The provider makes
one pass over live sessions per render, with no query per tile.

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

## Guide pages

The `guides/` directory holds player guide pages for
[evennia-guides](../../utils/evennia_guides/README.md): `social`,
`glossary-hangout`. They explain the system to players in general terms,
without exact numbers, and link only to pages this contrib or its required
dependencies ship. With evennia-guides installed they appear on its web guide;
without it they're ignored. To restate one for your game, add a page with the
same key to `GUIDES_DIRS`.

---

## Version history

See [CHANGELOG.md](CHANGELOG.md).

## Optional profile providers

`SOCIAL_PROFILE_PROVIDERS` is a list of dotted paths to `(viewer, target) -> dict`
callbacks. Returned label/value fields are appended to `+finger`; each provider
owns its visibility policy. Missing or failing providers are logged and skipped.
For gathering leans, install resources and add
`"evennia_rp_resources.profile.gathering_field"`. Leave the list empty when no
extra fields are needed; social acquires no new dependencies.


Room-owner rights in `+roomconfig` and `+mood` use
`evennia_links.rooms.can(character, room, "configure")`. Without a provider this
is the existing control-lock check. A configured provider can grant rights to
owners/residents/stewards without granting general Evennia control. Staff and
mood's scene-host/participant permissions remain independent. See Links' room
provider settings; Social never imports an ownership package.

### Host temporary mood permission

`SOCIAL_ROOM_MOOD_PERMISSION` accepts a callable or dotted path taking
`(character, room)`. Return True to grant, False to deny, or None to defer to
the existing staff, scene and Links configure checks. Exceptions and invalid
results deny. This permission only sets temporary mood text; it does not grant
room configuration. Building 0.3 supplies `evennia_building.access.steward_mood_permission`.

Room configuration display also renders an optional room method
`get_extra_room_details(viewer)`, returning `(label, value)` pairs. Cooperative
host mixins can show provenance here while keeping it out of ordinary look text.
Displaying metadata does not grant configuration permission.

## Disposable guests

Guests may page staff only, return to their own lounge with +ooc/+home, appear marked in connected listings, and stay out of permanent public presence.

Guest identity comes from `evennia_links.guests.is_guest`, using the actual
account typeclass and playable ownership rather than a hierarchical Guest
permission check. See the reference game for restricted command composition.


## Staff-run character identity and communication policy

`SOCIAL_STAFF_RUN_MARKER = True` adds a public `(staff-run)` marker to
`+finger`, player-facing `who`, and `+where`. The default is off.
`evennia_social.identity.staff_run_marker(character)` supplies the same
display-only suffix for host website lists/profiles. It checks current
account roster permissions, including offline characters and quelling;
`SOCIAL_STAFF_PERMISSION` defaults to Builder. When NPCs is installed,
currently controlled NPCs also reflect their controller's account status.
It never identifies the account or links other alts.

Page delivery and explicit OOC chat consult Links' optional communication
restriction seam before persistence, room delivery or pose-recorded signals.
Existing guest pages remain staff-only. Moderation uses this seam to preserve
staff contact while stopping communication with other players.

## Shared temporary atmosphere and sensory prose

Mood uses Links' `decorate` policy, shared with temporary crafted room layers.
The existing `SOCIAL_ROOM_MOOD_PERMISSION` extension retains its grant/defer/deny
semantics; a temporary grant never permits installation or lasting configuration.
`+roomconfig/smell <text>` and `/sound <text>` set free owner-written sensory
prose (400 characters; empty clears), using `configure` permission. These work
without Crafting; its room sensory commands append fixture lines when installed.
Tuple-tagged `crafting_event` messages from ignored ordinary players are fully
suppressed, without a pose placeholder or header. Staff keep existing bypass
semantics. Item events never enter Social/Posing's ordinary pose processing.
