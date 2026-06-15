# Changelog — evennia-scenes

## [0.1.0] — 2026-06-14

Initial extraction from source MUSH project.

### Added
- `Scene` model with full status lifecycle (open → active → closed) and three
  privacy tiers (public, pose-private, view-private).
- `SceneParticipant` through-model tracking per-character joins, leaves, pose
  counts, invite flags, and observer/participant roles.
- `LogEntry` model for capturing poses, emits, says, OOC comments, dice rolls,
  combat actions, and system messages within a scene.
- `LogEntryVersion` append-only edit-history table (via `AbstractVersion` from
  `evennia-links>=0.3`).
- `capture_to_scene(character, content, log_type)` — public hook for pose
  recording; call from your character typeclass.
- `register_room_entry(room, character)` — public hook for auto-registering
  arriving characters as participants; call from `Room.at_object_receive`.
- `CmdScene` (`+scene`) with switches: `/open`, `/close`, `/resume`, `/title`,
  `/desc` (EvEditor), `/privacy`, `/invite`, `/join`, `/leave`, `/info`.
- `CmdLog` (`+log`) with switches: `/edit`, `/history`, `/rollback`, `/diff`,
  `/ic`, `/ooc`. `CmdLog` inherits `EditingMixin` from `evennia-links>=0.3`.
- Django signals: `scene_opened`, `scene_started`, `scene_closed`,
  `log_entry_created`.
- Web views: `SceneListView`, `SceneDetailView`, `LogEntryEditView`,
  `LogEntryHistoryView`, `LogEntryDiffView` (requires `[web]` extra).
- DRF API: `SceneViewSet` (read-only) with nested `/log/` action (requires
  `[web]` extra).
- 5 Bootstrap-compatible HTML templates extending `website/base.html`.
- `render_scene_ref(scene_id)` display helper for cross-system soft-references.
- `SCENES_STAFF_LOCK` settings seam (default `cmd:perm(Builder)`).

### Dependencies
- `evennia>=6.0`
- `evennia-links>=0.3` (provides `AbstractArchived`, `AbstractVersion`,
  `EditingMixin`)
