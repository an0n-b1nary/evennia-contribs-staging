# Changelog — evennia-rptracker

All notable changes to `evennia-rptracker` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

- Reject unknown, ambiguous and stacked switches before command lookups or changes, including stock command replacements.
  `+rptracker/review` remains accepted, as its help documents.

## [0.3.0] - 2026-10-21

### Breaking

- Replace `+report activity [days]` with `+report/activity [days]`. The old
  positional form and stacked switches are refused. Unique switch prefixes work;
  the default seven-day window and 1–90 day range are unchanged.

## 0.2.6 — 2026-10-18

- `+activity/detail` names a session's scenes by their public scene number, as `+scene` and `+log` do. It showed the database key, which players never see. `RPTRACKER_SCENE_DISPLAY` still overrides it.
- Guide pages: `rp-sessions` covers what `+activity/detail` shows, how sessions link to scenes, guests, and staff's advisory notices about characters from one account playing together.
- README: the Scene bridge section and settings table give the real `evennia_scenes` default and describe the soft reference; the old "hardcoded FK" limitation is gone. The bridge module's docstring matches.

## 0.2.5 — 2026-10-18

- Guide pages: a staff page, `rptracker-staff`, covering session review and flags, automatic flags, the activity report and alt co-presence notices.

## 0.2.4 — 2026-10-13

- Alt co-presence advisories are limited to one per account per window.
  Later exchanges, and sessions joining an exchange already reported, no
  longer open another staff notice. No schema change.

## 0.2.3 — 2026-10-13

- Advisory-only repeated alt co-presence notices for room and channel sessions,
  with durable deduplication and no change to sessions or XP eligibility.
- IC channels participate in the shared communication restriction seam.

## 0.2.2 — 2026-10-12

- Exclude guests from room and channel tracking, partner detection and activity reports, including in a misconfigured IC room.

## [0.2.1] - 2026-10-10

- **Added:** a player guide page for evennia-guides, `rp-sessions` (how RP
  sessions are noticed and counted) and the `rp-never-a-quota` principle, in
  `guides/` and the package data. It describes the system in general terms,
  without exact numbers, and links only to pages this contrib or its required
  dependencies ship. Without evennia-guides it's ignored.

## [0.2.0] - 2026-10-09

- Added independent IC-channel sessions, character-attributed channel typeclass,
  configurable eligibility, partner windows, lifecycle cleanup and XP collector.
- Added read-only staff activity reports grouped by canonical region or room,
  with separate channel totals and excluded flagged sessions. Deleted rooms keep
  separate named buckets; deleted characters still count as participants.
- Added an additive migration for session sources, channel history, persisted
  activity timestamps and account snapshots. Existing rows remain room sessions.
- **Fix:** the post-batch hooks now mark a session awarded only when its XP
  ledger row matches the award's character as well as its source and session;
  a ledger row written for another character no longer confirms it.
- Requires evennia-links >=0.7 for shared playable-account partner exclusion.

## [0.1.5] - 2026-10-07

- **Docs:** the README now names the shipped values for two hooks:
  `RPTRACKER_FLAG_REVIEW_HOOK` → evennia-jobs'
  `integrations.staff_review.file_review_job`, and `RPTRACKER_XP_PROJECTION` →
  evennia-xp's `projection.activity_lines`. It also points the XP section at
  this contrib's own `integrations.xp` collector instead of saying XP is
  entirely the game's job. No code change.

## [0.1.4] - 2026-10-02

- **Fixed:** exported `__version__` now matches the installed package metadata.

## [0.1.3] — 2026-08-02 — use the shared resolve_dotted

- `commands.py`'s local `_resolve_dotted` now delegates to
  `evennia_links.resolve_dotted`, wrapped in the same log-and-skip fallback so a
  misconfigured `RPTRACKER_SCENE_DISPLAY` / `RPTRACKER_XP_PROJECTION` still degrades
  gracefully instead of crashing the command. Dedupes one of three hand-rolled copies
  of this helper across the staging repo. Requires `evennia-links>=0.4`.

## [0.1.2] — 2026-07-05 — fix app-label defaults and gate hardening

- `RPTRACKER_SCENES_APP_LABEL` default changed from `"scenes"` → `"evennia_scenes"` to
  match `evennia_scenes`'s real Django app-label.
- `EvenniaRptrackerConfig.ready()` membership gate replaced with the robust
  `apps.is_installed(label) or any(cfg.label == label …)` pattern.

---

## [0.1.1] — 2026-07-05 — add XP integration module

- `evennia_rptracker/integrations/xp.py` — new module with XP collector and
  post-batch hook:
  - `collect_rp_sessions(window_end)` — yields 1 XP `Award` per eligible
    `RPSession` (status=COMPLETED, duration ≥ 30 min, ≥ 1 partner,
    `xp_awarded=False`). Multiplier via `evennia_xp.gating.resolve_xp_multiplier`.
  - `flip_session_flags(window_end, awards, week_label)` — post-batch hook:
    sets `xp_awarded=True` / `xp_week` on sessions that have confirmed `XPLog`
    rows (DB-checked for safety after partial rollbacks).
- Register in `settings.py`:
  ```python
  XP_COLLECTORS += [
      ("rp_session", "evennia_rptracker.integrations.xp.collect_rp_sessions"),
  ]
  XP_POST_BATCH_HOOKS += [
      "evennia_rptracker.integrations.xp.flip_session_flags",
  ]
  ```

## [0.1.0] — 2026-06-27 — initial extraction

- `RPSession` + `RPSessionPartner` models: passive RP session detection
  with status lifecycle (pending → active → completed / flagged), duration
  helpers, `is_xp_eligible()` default criteria, and flag/unflag transitions.
- `RPSessionSceneLink`: integer soft-reference bridge (no FK dependency on
  an optional scenes app). Created by the `rp_activity_recorded` listener
  when `RPTRACKER_SCENES_APP_LABEL` is installed.
- `tracker.py`: in-memory session state machine with batched DB writes,
  idle-check Script, and server lifecycle hooks.
- `antigaming.py`: `sweep_rp_sessions(window_end)` — pose-spam and
  manual-end-abuse detection; notification via `RPTRACKER_FLAG_REVIEW_HOOK`.
- `commands.py`: `CmdActivity` (+activity) and `CmdRPTrackerStaff` (+rptracker).
  XP projection and scene-title display via configurable hook settings.
- Soft-dependency scene bridge: gated on `RPTRACKER_SCENES_APP_LABEL` in
  `INSTALLED_APPS`; requires `evennia-links>=0.2` for cascade cleanup.
- Settings table: 12 `RPTRACKER_*` knobs covering thresholds, locks, and hooks.
