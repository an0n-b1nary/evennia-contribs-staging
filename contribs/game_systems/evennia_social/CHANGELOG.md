# Changelog

All notable changes to `evennia_social` are documented here.

## [0.8.0] - 2026-10-21

### Breaking

- Replace `+roomconfig/hangout/clear` with `+roomconfig/unhangout`. Stacked
  switches are refused, including unknown extras; unique switch prefixes work.

## 0.7.7 - 2026-10-18

- Guide pages: `social` corrects summon and join: accepting doesn't admit anyone to a place they aren't allowed into. It adds `@tel`, `+home/set`, pending requests, multi-recipient pages and page history, theme visibility, room smells and sounds, hangout designation, guests, and that staff still see unfindable characters.
- MIGRATION_NOTES: the `+hangouts/all` fix is recorded as fixed in the source too, not owed upstream.

## 0.7.6 - 2026-10-18

- Guide pages: a staff page, `social-staff`, covering presence as staff see it, going dark, teleporting, staff rooms, hangouts and moods.

## 0.7.5 - 2026-10-14

- Share Links decorate permission with Crafting; add free owner-written room sensory prose and suppress ignored crafting events.

## 0.7.4 — 2026-10-13

- Check shared communication restrictions before creating or delivering pages.
- Hosts can disable the personal `+mute` alias with `SOCIAL_IGNORE_MUTE_ALIAS`
  so it does not hide Moderation's staff command; `+ignore` remains available.
- Opt-in public staff-run markers use current account roster membership, including
  offline characters and quelled staff, with a reusable website helper.

## 0.7.3 — 2026-10-12

- Guests may page staff only, return to their own lounge with +ooc/+home, appear marked in connected listings, and stay out of permanent public presence.

## 0.7.2 — 2026-10-12

- Add optional `SOCIAL_ROOM_MOOD_PERMISSION` for narrowly scoped temporary mood rights.
  True/False is authoritative; None preserves existing staff, scene and configure rules.
  Provider errors and invalid results deny; this grants no lasting room configuration.
- Display optional cooperative room metadata in `+roomconfig` for authorized viewers.

## 0.7.1 ? 2026-10-11

- Respect authoritative property travel and visibility in discovery, home, teleport, summon and join.

## [0.7.0] - 2026-10-10

- Room configuration and the owner/control branch of mood permissions now
  ask the Links room-permission provider for `configure`. Existing staff and
  scene-participant/host rules remain in place. Added a direct Links dependency.

## 0.6.0 — 2026-10-10

- **Changed:** the live map's who's-here overlay uses the viewer evennia-maps 0.9
  passes. An unfindable character shows, in the names and the count, to a viewer
  whose character is connected and in the same room, as `look` would. A character
  that isn't connected in-game doesn't count as being there. With no viewer the
  rule is unchanged.

## 0.5.1 — 2026-10-10

- **Added:** a player guide page for evennia-guides, `social` (finding people,
  profiles, pages, ignoring, consensual movement and room mood) and the
  `glossary-hangout` term, in `guides/` and the package data. It describes the
  system in general terms, without exact numbers, and links only to pages this
  contrib or its required dependencies ship. Without evennia-guides it's
  ignored.

## 0.5.0 — 2026-10-10

- **Added:** who's here on the live map. With evennia-maps installed,
  `ready()` connects `integrations/maps.py` to its `collect_tile_overlays`
  seam, which answers `present`: the names of connected characters in each
  room. The map is a remote presence surface, so it follows `+where`:
  players see only findable characters (`is_publicly_findable`), and
  unfindable or dark characters are left out of both the names and the
  count. Staff see everyone, with the `(unfindable)` / `(dark)` marker. One
  pass over live sessions per map render, with no query per tile. Shows on
  evennia-maps 0.7 or later; older maps ignore the key.

## 0.4.0 — 2026-10-09

- **Added:** presence (`evennia_social.presence`). Each character is
  `findable` (default), `unfindable` or, for staff only, `dark`. Unfindable
  characters are left out of `+where`, `+where/count` and `+hangouts` counts,
  but still appear in `who`; dark staff are also left out of `who`. Anyone in
  the same room, and staff, see through both; staff see a `(unfindable)` /
  `(dark)` marker in `+where`. A stored `dark` on a character that is no
  longer staff reads as `unfindable`. Web code with no in-game viewer uses
  `is_publicly_findable()` / `is_publicly_listed()`.
- **Added:** `+unfindable [on|off|dark]`, and a `CmdWho` that replaces
  Evennia's `who` (mount it in the AccountCmdSet) and leaves dark staff out
  for unprivileged accounts. `SocialCharacterMixin.presence_visibility`
  stores the setting.

## 0.3.0 — 2026-10-09

- Added: Optional `SOCIAL_PROFILE_PROVIDERS` callbacks for visibility-aware profile fields.

## 0.2.0 — 2026-10-07

- **Added:** room mood. `SocialRoomMixin` now owns `room_mood` and
  `room_mood_setter` and shows the mood under the room's description in
  `look`, attributed to whoever set it. New `+mood` command: bare shows the
  mood, `+mood <text>` sets it (up to 200 characters, announced to the room),
  `+mood/clear` removes it. `+roomconfig` shows the setter too.
- **Added:** mood permissions (`evennia_social.mood.can_set_mood`). The room's
  owner or Builder+ staff, always. With `evennia-scenes` installed and a scene
  running in the room, any active participant of a public scene, or only the
  host of a scene with any other privacy tier (an unknown tier counts as
  private). `evennia-scenes` stays optional, found through
  `SOCIAL_SCENES_APP_LABEL` (default `"evennia_scenes"`).
- **Changed:** `room_mood` is no longer documented as an attribute "read but
  not owned"; games that defined it themselves can drop their own definition.
  `+hangouts` and `+roomconfig` still read it defensively, so a Room without
  the mixin keeps working.

## 0.1.0 — 2026-07-15

Initial extraction from a source MUSH project's social quality-of-life
command layer. See `MIGRATION_NOTES.md` for the full source inventory and
rename map.

- `SocialCharacterMixin`: profile fields, page/ignore/summon/home state,
  ignore-filtering `msg()` (cooperative with `evennia_posing`'s
  header/highlight `msg()`), `get_display_name()` short-desc suffix.
- `SocialRoomMixin`: `hangout_type`, `allow_teleport`.
- Commands: `CmdFinger`, `CmdWhere`, `CmdHangouts`, `CmdIgnore`, `CmdPage`,
  `CmdSummon`, `CmdJoin`, `CmdOoc`, `CmdOocTeleport`, `CmdHome`,
  `CmdRoomConfig`, `CmdRoulette`, `CmdTel`.
- `search.py`: `find_room()`, `find_room_for_player()` — generalized to
  `isinstance()`-based Room/Character matching (see MIGRATION_NOTES).
- `social.py`: `is_staff()`, `get_connected_characters()`,
  `find_character()`.
- Hard dependency on `evennia-posing` (`format_pose_time`, pose state for
  `+where`, cooperative `msg()` layering).
- `CmdOoc` fires `evennia_posing`'s `pose_recorded` signal (`pose_type=
  "ooc"`) instead of the source project's direct scene-log call — a
  coupling not covered by the original extraction scoping report,
  discovered and severed during this extraction (see MIGRATION_NOTES).
- Fixed a cooperative-`msg()` ordering bug found by the standalone test
  suite: the ignored-sender placeholder was being run through
  `evennia_posing`'s pose-header/highlight pass, which put a `--- <sender>
  ---` header above a notice whose whole point is to *not* name the sender.
  `SocialCharacterMixin.msg()` now retags the placeholder's message type
  before handing it to `super().msg()` (see MIGRATION_NOTES).
- Fixed a latent bug carried from the source: `+hangouts/all` listed rooms
  whose hangout designation had been cleared as permanently "empty"
  hangouts (see MIGRATION_NOTES).
- Optional screen-reader support for `+where`/`+hangouts` via
  `evennia-accessibility`.
