# Changelog — evennia-scenes

## [0.2.0] — 2026-08-01

### Added
- `Scene.WEB_READABLE_PRIVACY` and `Scene.is_web_readable(privacy)` — the
  canonical answer to "may a web visitor read this scene's log?", declared
  next to the `Privacy` enum. Games adding their own web surface should ask
  these rather than re-deriving the tier set.

### Fixed
- **Privacy could fail open on an added tier.** `SceneListView` and the DRF
  `SceneViewSet` filtered `privacy__in [PUBLIC, POSE_PRIVATE]`, while
  `_can_view_scene()` — which gates `SceneDetailView`, `LogEntryHistoryView`
  and `LogEntryDiffView` — tested `!= VIEW_PRIVATE`. Those agree only while
  exactly three tiers exist. A game adding a fourth tier got it hidden from
  the listing and the API but *served* by the detail page and the edit-history
  drill-downs. All consumers now ask `is_web_readable()`, which is a
  membership test, so an unclassified tier is private everywhere.
  No behaviour change for the three shipped tiers; no migration.

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
