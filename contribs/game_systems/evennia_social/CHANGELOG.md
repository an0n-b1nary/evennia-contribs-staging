# Changelog

All notable changes to `evennia_social` are documented here.

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
