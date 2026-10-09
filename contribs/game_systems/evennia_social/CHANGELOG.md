# Changelog

All notable changes to `evennia_social` are documented here.

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
