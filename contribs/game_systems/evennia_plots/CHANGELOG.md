# Changelog

All notable changes to `evennia-plots` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.7.0] - 2026-10-11

- **Added:** threads. A thread (`StoryThread`) is an open question, problem or
  lead inside a plot, referenced as `#<plot>.<thread>`. Threads can be
  requested, accepted or declined, resolved with a summary, dropped, reopened,
  and led or followed. A plot's `thread_policy` says who adds them: `open`
  (anyone who can link; the default), `request` (others ask, owners decide) or
  `owners`. In game: `+plot/thread` and its switches, and `+plot/threads`. On
  the web: a Threads section on the plot page, and add, resolve, answer and
  carry pages. The API lists each plot's threads.
- **Added:** held threads and sealed answers. Owners mark a thread held when
  they already know its answer; a plot with an open held thread shows
  *Owner-led*. An optional sealed answer is readable by owners and staff only,
  keeps every earlier wording, and is revealed only by choice, when the thread
  resolves or later. It is never shown in `+plot`, on the plot page, in the
  API or on the map while sealed, and the API never includes it at all.
- **Added:** loose ends. Concluding or archiving a plot turns its open threads
  into loose ends and declines pending requests, without blocking. A loose end
  can be carried into a declared sequel by someone who runs both plots; its
  sealed answer travels only when the sequel has no new owners.
- **Added:** plot owners (`PlotOwner`). The creator is the first owner;
  `+plot/owner` and the web's *Manage Owners* page add and remove more. Owners
  replace the creator in every permission check (`plot.is_owner()`,
  `plot.can_manage()`). Ownership never creates a `PlotParticipant`, so it
  never pays the conclusion bonus. Staff actions on plots they don't own are
  kept in `staff_log`.
- **Added:** migrations `0002` (owners, threads, thread policy, staff log) and
  `0003` (makes each existing plot's creator its first owner).
- **Changed:** player-facing wording says "plot" where it said "plot thread",
  in commands, pages, guides and the admin. The XP source label is now "Plot
  Bonus"; the stored key stays `thread_bonus`. Python names are unchanged.
- **Removed:** the `+thread` alias of `+plot`, which would now mislead.
- **Unchanged:** the conclusion bonus and the 24-hour anti-gaming rule. Threads
  have no effect on XP, in either direction.
- **Fixed:** the package docstring's mis-encoded dashes.

## [0.6.0] - 2026-10-10

- **Added:** a "Plots here" section in evennia-maps' room panel (0.9+): active
  and concluded threads with a scene in the room, newest first, each noting its
  arc. Needs evennia-scenes. Players count only scenes the web may show and never
  see private threads; staff see private threads noted and unlinked.
  `PLOTS_MAPS_APP_LABEL` names the map app.

## [0.5.1] - 2026-10-10

- **Added:** a player guide page for evennia-guides, `plots` (threads, privacy,
  the conclusion bonus and arcs) and the `glossary-arc` term, in `guides/` and
  the package data. It describes the system in general terms, without exact
  numbers, and links only to pages this contrib or its required dependencies
  ship. Without evennia-guides it's ignored.

## [0.5.0] - 2026-10-10

- **Added:** every colour in the stylesheet is a shared `--evennia-color-*` theme
  token with its previous colour as the fallback, so a host stylesheet that
  sets the tokens on `:root` rethemes this contrib's pages along with the
  others. Nothing changes until a host sets one. The token list is in
  evennia-accessibility's README.

## [0.4.0] - 2026-10-10

- **Added:** every authoring form names the character it writes as ("Posting as
  **Name**") above its submit button, and the button is described by that text for
  screen readers, so a player with several characters can't post as the wrong
  one unnoticed. Authoring views put `acting_character` in the template context;
  the label is `evennia_accessibility/_acting_as.html`. Requires
  evennia-accessibility 0.3.1 for the `[web]` extra.
- A character picked on the website (Evennia's own puppet link) now applies to
  every page and write here when the game installs evennia-links 0.8.1's
  `WebCharacterMiddleware`. No change is needed in this package.
- **Added:** `plot_thread_concluded` now also sends `concluded_by`, the character
  passed to `PlotThread.conclude()` (`None` when nobody was named). Receivers that
  take `**kwargs` are unaffected. evennia-lore 0.5 uses it to remind whoever
  concluded a thread that its linked lore still has sealed notes.

## [0.3.3] - 2026-10-10

- Add `collect_thread_content`, an optional collector for creative-content
  providers such as NPCs. Its boolean contributions share the IC-post checklist
  item; linking both never awards the point twice. No NPC dependency is added.

## [0.3.2] - 2026-10-09

- **Fixed:** the website now resolves the acting character from the account's
  playable characters through `evennia_links.characters.web_character`, so a
  visitor who is not connected in-game still acts as their character. Before, only
  a live puppet counted: pages and writes that need a character treated the
  visitor as having none ("A puppeted character is required") unless the account
  was also in the game. Requires evennia-links 0.8.

## [0.3.1] - 2026-10-08

- **Fixed:** weekly thread bonuses honor the host-configured XP multiplier
  resolver, including scaling and suppression, rather than bypassing it.
  Default arc gating and credit idempotency remain unchanged.

## [0.3.0] - 2026-10-02

- **Breaking:** remove the deprecated top-level `collectors.py`,
  `antigaming.py`, and `gating.py` stubs promised in 0.2.0.
  Update dotted settings paths to `evennia_plots.integrations.xp`,
  `evennia_plots.integrations.antigaming`, and
  `evennia_plots.integrations.gating`, respectively.

- **Changed:** web templates use namespaced classes, packaged CSS, and the
  shared metadata, table, and empty-state conventions.

- **Changed:** HTTP staff checks use the shared ``evennia_links`` predicate;
  player plot details no longer expose the privacy field.
- **Fixed:** every shipped template included its partials from
  `website/partials/…` — `_form_errors.html`, `_form_field.html`,
  `_form_actions.html`, `_empty_state.html` and `_pagination.html`. None of
  those files exists: not in this contrib, not in Evennia, and no install step
  tells a game to create them. Every authoring form and every empty state was a
  guaranteed `TemplateDoesNotExist` 500 — that is the whole web surface. The
  three form partials now come from `evennia_accessibility`, which this
  contrib's `[web]` extra has always required; `_empty_state.html` and
  `_pagination.html` are now shipped locally under `evennia_plots/`. The
  leftover paths came from the source game, where those partials were global.

- **Fixed:** `_pagination.html` documented `extra_params` as needing a trailing
  `&` that the partial itself adds.

- **Added:** `TestWebPagesRender` — all fourteen pages are now rendered for real
  via `response.render()`, with the test module doubling as a test URLconf.

- **Changed:** the old `TestTemplateCompile` asserted only that each of the
  fourteen templates loads. All fourteen compiled cleanly for as long as the
  broken includes shipped, because compiling a template resolves no
  `{% include %}` target. Replaced with real renders.

## [0.2.4] - 2026-10-02

- **Fixed:** command helpers import the public accessibility export so the installed
  partner's screen-reader preference is honored; the absent-partner fallback remains.

## [0.2.3] - 2026-10-02

- Stack labelled table rows below 640px while retaining table semantics and desktop columns.

## [0.2.0] — 2026-07-05 — XP glue moved to integrations/ + app-label fixes

### Changed (breaking)

- XP integration modules moved into an `integrations/` subpackage for
  consistency with `evennia-lore`, `evennia-rptracker`, and `evennia-boards`.
  Update settings paths:

  | Old path | New path |
  |---|---|
  | `evennia_plots.gating.resolve_xp_multiplier` | `evennia_plots.integrations.gating.resolve_xp_multiplier` |
  | `evennia_plots.collectors.collect_thread_bonuses` | `evennia_plots.integrations.xp.collect_thread_bonuses` |
  | `evennia_plots.collectors.collect_arc_bonuses` | `evennia_plots.integrations.xp.collect_arc_bonuses` |
  | `evennia_plots.antigaming.sweep` | `evennia_plots.integrations.antigaming.sweep` |

  The old top-level `collectors.py`, `antigaming.py`, and `gating.py` are now
  empty stubs; they will be removed in a future release.

- `PLOTS_SCENES_APP_LABEL` default changed from `"scenes"` → `"evennia_scenes"`.
- `PLOTS_BOARDS_APP_LABEL` default changed from `"boards"` → `"evennia_boards"`.
- `PLOTS_CALENDAR_APP_LABEL` default changed from `"calendar"` → `"evennia_calendar"`.
- `PlotsConfig.ready()` membership gate replaced with the robust
  `apps.is_installed(label) or any(cfg.label == label …)` pattern.

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
