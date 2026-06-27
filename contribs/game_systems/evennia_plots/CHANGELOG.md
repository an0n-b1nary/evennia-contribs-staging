# Changelog

All notable changes to `evennia-plots` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] — 2026-06-27

### Added

**Models (7 domain + 3 bridges + PlotBonusCredit):**
- `PlotThread` — named narrative container. Statuses: PROPOSED → ACTIVE → CONCLUDED → ARCHIVED. Privacies: PUBLIC / INVITE_ONLY / PRIVATE. Auto-incrementing `plot_number`. `conclude()` computes a 0–5 XP bonus from three checklist rules (advance-notice calendar link +3, ≥2 scene links +1, IC board post +1).
- `PlotArc` — staff-managed story arc with a partial unique constraint (`plotarc_one_current_global`) ensuring at most one globally-current arc. Per-source XP multipliers (`xp_mult_rp_session`, `xp_mult_cutscene`, `xp_mult_lore`, `xp_mult_thread_bonus`); type defaults STORY=1.0× / DOWNTIME=0.0×. `conclude()` clears `is_current`.
- `PlotTag` — major/minor classification tags for threads.
- `PlotParticipant` — thread ↔ character join table (FK to `ObjectDB`). Auto-created by the scene-link listener.
- `PlotUpdate` — append-only journal blocks (thread or arc; auto-incrementing `block_number` per parent). `clean()` enforces XOR (thread xor arc).
- `PlotUpdateVersion` (via `evennia_links.AbstractVersion`) — full edit history with rollback support.
- `ThreadLink` — sequel/related links between threads; `accept()` creates the reverse mirror and fires `thread_link_accepted`.
- `ScenePlotLink` — soft-ref (`scene_id`) bridge; `create_link()` fires `scene_linked_to_thread`.
- `PlotCalendarLink` — soft-ref (`event_id`) bridge; captures `advance_notice_met` at link time.
- `PlotBoardLink` — soft-ref (`post_id`) bridge; captures `is_ic_post` at link time.
- `PlotBonusCredit` — one-per-(thread, character) eligibility row; used by the collector for idempotent XP award.

**Commands:**
- `+plot` — create, view, edit, conclude, archive, activate, tag/untag, privacy, invite, sequel, relate, link-scene, link-post, link-event, update create/edit/history/diff. Screenreader-accessible fallback.
- `+arc` (staff) — arc create/edit/conclude/archive/setcurrent/clearcurrent; per-source XP multiplier overrides.
- `+hook` (staff) — append an audit entry to `PlotThread.hook_log`; rejects private threads.

**Signals (12):** `plot_thread_created`, `plot_thread_activated`, `plot_thread_concluded`, `plot_thread_archived`, `scene_linked_to_thread`, `post_linked_to_thread`, `event_linked_to_thread`, `thread_link_accepted`, `plot_update_created`, `plot_thread_edited`, `arc_type_changed`, `arc_currency_changed`.

**XP glue (gating / collectors / anti-gaming):**
- `gating.py` — `resolve_active_arc()` + `resolve_xp_multiplier()`. Arc resolution order: thread's explicit arc → global `is_current` arc → None (full rate). Registers as `XP_MULTIPLIER_RESOLVER`.
- `collectors.py` — `collect_thread_bonuses()` + `collect_arc_bonuses()`. Idempotent via `PlotBonusCredit` + `XPLog.source_ref_id` check. Registers in `XP_COLLECTORS`.
- `antigaming.py` — `sweep()` (the registered `XP_ANTIGAMING_SWEEPS` entry point) drives `_flag_thread_gaming()`, which zeroes `bonus_xp_computed` and records a reason for threads concluded within 24 h of creation.

**Web (`[web]` extra):**
- ~18 CBVs covering list, detail, create, edit, invite, tag, update history/diff, arc management, arc set/clear current.
- 14 templates under `templates/evennia_plots/`.
- 8 model forms (`AccessibleModelForm` with fallback to Django base forms).
- Privacy gate: `PlotDetailView.get_queryset()` excludes PRIVATE threads.
- `PLOTS_STAFF_LOCK` seam (default `"cmd:perm(Builder)"`); `is_plot_staff(character)` and `is_staff_user(request)` helpers.

**API (`[web]` extra):**
- `PlotThreadViewSet` (read-only) — non-staff sees only ACTIVE PUBLIC/INVITE_ONLY threads; staff sees all.
- `PlotThreadSerializer` + `PlotTagSerializer`.
- `PlotThreadFilter` (django-filter) — filter by `tag` and `status`.

**Listener:**
- `on_scene_linked_to_thread` — auto-creates `PlotParticipant` rows from a linked scene's active participants. Gated on the scenes app being installed.

**Soft-ref cleanup:**
- On hard-delete of a partner scene/event/post, `connect_soft_ref_cleanup` nulls the corresponding `*_id` field (registered in `apps.py` per partner app label, defaulting to `"scenes"` / `"calendar"` / `"boards"`).

**Settings:**
- `PLOTS_STAFF_LOCK` — lock expression for staff operations (default `"cmd:perm(Builder)"`).
- `PLOTS_SCENES_APP_LABEL` — Django app label for scenes (default `"scenes"`).
- `PLOTS_CALENDAR_APP_LABEL` — Django app label for calendar (default `"calendar"`).
- `PLOTS_BOARDS_APP_LABEL` — Django app label for boards (default `"boards"`).
