# Changelog — evennia-rptracker

## 0.1.0 — initial extraction

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
