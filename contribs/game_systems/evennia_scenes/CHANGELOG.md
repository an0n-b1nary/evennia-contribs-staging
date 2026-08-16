# Changelog — evennia-scenes

## [0.3.0] — 2026-08-15 — map tile overlays

### Added
- `integrations/maps.py` — the `has_active_scene`, `recent_scene_count` and
  `recent_scenes` map tile overlays. With `evennia-maps` installed,
  `ScenesConfig.ready()` connects the provider to its `collect_tile_overlays`
  signal: live scenes highlight their tile, closed scenes drive an activity
  heatmap, and the three newest public logs link out of the tile popup. Four
  queries for the whole grid; nothing to configure; nothing imported when the
  map is absent. New `SCENES_MAPS_APP_LABEL` setting (default `"evennia_maps"`).

  Each overlay applies `WEB_READABLE_PRIVACY` itself. That is the reason the seam
  is a signal at all: `Scene.room_id` is a bare pk with no privacy dimension, so a
  map reading it directly would pin every view-private scene for every anonymous
  visitor. `recent_scenes` stays public-tier even for staff — it renders as links
  to log pages, which leak by URL — while `recent_scene_count` widens for staff,
  who need the heatmap to show where play actually happens.
- `recent_public_scene_ids_by_room()` is public in that module: any surface needing
  "the newest readable logs for these rooms" should ask for it rather than
  re-deriving the privacy rule.
- `TestWebPagesRender` — every scene page (archive, scene detail, log-entry edit
  form, edit history, diff) is now rendered for real via `response.render()`.

### Changed
- The old `TestSceneTemplatesLoad` only called `get_template()` on each file, on
  the stated reasoning that a contrib cannot full-render in isolation because the
  templates extend the host's `website/base.html` and reverse the host-wired
  `evennia_scenes:` namespace. That reasoning was wrong: Evennia ships both
  `website/base.html` and its own urlpatterns, so a test module can mount this
  contrib's routes itself and splat Evennia's in after them. Compiling a template
  resolves no `{% extends %}` or `{% include %}` target and reverses no URL, so
  the old check could not have caught the `NoReverseMatch` and missing-partial
  faults that shipped in sibling contribs. Replaced with real renders.

---

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
