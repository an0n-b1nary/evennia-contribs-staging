# Changelog

All notable changes to `evennia_posing` are documented here.

## 0.1.0 — 2026-07-12

Initial extraction from a source MUSH project's roleplay
quality-of-life command layer. See `MIGRATION_NOTES.md` for the full
source inventory and rename map.

- `PosingCharacterMixin`: pose/say tracking (`last_pose_time`,
  `last_pose_text`, `pose_status`), `record_pose()`, pose-header and
  name-highlighting `msg()` override.
- `PosingRoomMixin`: pose-sorted character listing, name highlighting in
  room appearance.
- `pose_recorded` signal — replaces direct calls into scene-logging/RP-
  tracking systems from the source project's `record_pose()`.
- Commands: `CmdPose`, `CmdEmit`, `CmdSemipose`, `CmdPot`, `CmdLastPose`,
  `CmdPoseHeader`, `CmdHighlight`.
- `highlighting.py`: `highlight_names()`, `format_pose_time()`.
- Optional screen-reader support for `+pot` via `evennia-accessibility`.
