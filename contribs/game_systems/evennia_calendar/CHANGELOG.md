# Changelog

## v0.1.1 — add SceneCalendarLink bridge model

- `SceneCalendarLink(AbstractAuthoredLink)` model: links a `CalendarEvent` to a
  Scene via an integer soft-reference (`scene_id`). Owned by evennia_calendar per
  the bridge-ownership convention. Uniqueness: one link per `(event, scene_id)`.
- `CalendarConfig.ready()` now registers a `connect_soft_ref_cleanup()` hook to
  cascade-delete orphaned `SceneCalendarLink` rows when a Scene is hard-deleted
  (gated on `CALENDAR_SCENES_APP_LABEL` being present in `INSTALLED_APPS`; default
  label: `"evennia_scenes"`).
- `SceneCalendarLinkAdmin` registered in `admin.py`.
- Migration `0002_scenecalendarlink`.
- **evennia-links** is now a runtime dependency (was a dev/test-only dep prior to
  this release). Add `evennia-links` to your `INSTALLED_APPS`.

## v0.1.0 (2026-06-25)

Initial extraction and packaging from a source MUSH project.

### Added

- `CalendarEvent` model with three RSVP modes: open, capped, and staff lottery
- `EventCluster` model for grouped ranked-choice RSVP across parallel events
- `ClusterRSVP` + `ClusterRSVPPreference` through-model for ranked preferences
- `RSVP` model with status machine: confirmed / waitlisted / invited / lottery-entered / lottery-selected / released
- `PriorityToken` model with `EVENT` and `CLUSTER_RANK1` scopes
- `EventTag` staff-managed thematic tag list
- `EventExclusion` mutual-exclusion pair for standalone events
- `CalendarMaintenanceScript` — Evennia DefaultScript running every 10 min:
  - Lottery draw 72 h before event (`run_lottery`, `run_cluster_lottery`)
  - Confirmation expiry at 24 h deadline (`expire_unconfirmed`)
  - Post-event token issuance (`issue_post_event_tokens`)
  - 24 h reminders (`event_starting_soon` signal)
- `ensure_calendar_script_running()` — idempotent server-start hook
- `CmdCalendar` (+calendar / +cal): creation, viewing, editing, cancellation, cap, tags, exclusions, cluster management
- `CmdRsvp` (+rsvp): RSVP, cancel, confirm, list, waitlist, invite, ping, token management, cluster ranked-choice RSVP
- 10 Django signals covering the full event/RSVP lifecycle
- Web views: `CalendarMonthView`, `CalendarListView`, `CalendarEventDetailView`, `ClusterDetailView` (GET + POST)
- Web authoring views: create/edit/cancel/invite/tag/exclusion/cluster views
- 12 Bootstrap 4 templates (all URL-namespaced as `evennia_calendar:*`)
- REST API: `CalendarEventViewSet` (read-only) with `after`/`before`/`emphasis`/`is_staff_event` filters
- `permissions.py` and `authoring.py` for web permission gates
- `forms.py` with 9 forms (Bootstrap 4 + ARIA base classes)
- Anti-favoritism guard: `is_staff_event` blocks pre-inviting in both commands and web views
- Accessibility shim: optional `evennia-accessibility` integration for screenreader-friendly command output
- `CALENDAR_STAFF_LOCK` settings seam for configurable staff permission level
- `SITE_URL`-gated web link helper for in-game MXP `|lu` links
- BSD-3-Clause license
