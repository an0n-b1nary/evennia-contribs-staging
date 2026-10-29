# Changelog

All notable changes to `evennia_posing` are documented here.

## [Unreleased]

- Test bases register their account options for each test class only, so a host game that runs them keeps its own option definitions and later test classes see its settings unchanged.

- Reject unknown, ambiguous and stacked switches before command lookups or changes, including stock command replacements.

## 0.1.3 — 2026-10-18

- Guide pages: `posing` explains that poses, emits and semiposes are refused, with a reason, while the game stops someone speaking in the room.

## 0.1.2 — 2026-10-13

- Check the Links communication seam before delivering poses, emits and
  semiposes. Links is now a declared hard dependency.

## 0.1.1 — 2026-10-10

- **Added:** a player guide page for evennia-guides, `posing` (pose, emit,
  semipose, `+pot` and the display settings), in `guides/` and the package data.
  It describes the system in general terms, without exact numbers, and links
  only to pages this contrib or its required dependencies ship. Without
  evennia-guides it's ignored.

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
