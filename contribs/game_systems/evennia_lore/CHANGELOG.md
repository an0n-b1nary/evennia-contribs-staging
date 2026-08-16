# Changelog — evennia-lore

All notable changes to `evennia-lore` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] — 2026-08-15 — map tile overlay

- **Added:** `integrations/maps.py` — the `has_lore` map tile overlay. With
  `evennia-maps` installed, `LoreConfig.ready()` connects the provider to its
  `collect_tile_overlays` signal and mapped rooms whose primary region has readable
  lore gain a pin. Two queries for the whole grid; nothing to configure; nothing
  imported when the map is absent. New `LORE_MAPS_APP_LABEL` setting (default
  `"evennia_maps"`).

  Lore attaches to *regions* and the map draws *rooms*, so the provider resolves the
  room→region step itself through the existing `LORE_REGIONS_APP_LABEL` gate; with
  regions absent the overlay is empty rather than broken. The pin uses the passive
  pool's own eligibility — PUBLISHED + PUBLIC + not archived — for staff and visitors
  alike: it names no entry, it is drawn on a public page, and widening it for staff
  would only make the map disagree with the compendium. Lore attached to an archived
  region does not light a tile, matching the region page's own 404.

- **Fixed:** the documentation comments at the top of `_empty_state.html` and
  `_pagination.html` spanned multiple lines. Django's template tag regex is not
  `DOTALL`, so a multi-line `{# ... #}` is not a comment — its text renders into the
  page, and the usage example inside each partial was a live `{% include %}` of the
  partial itself, recursing until the stack blew. Both are now `{% comment %}` blocks.
  Surfaced while building `evennia-maps`' web surface, whose tests render templates
  rather than only inspecting view context.

- **Fixed:** `lore_list.html` built its empty-state message as
  `message="No lore entries found{% if ... %} matching your filters{% endif %}."`.
  A tag nested inside a quoted argument does not parse, so the page 500'd whenever
  the entry list was empty. Split into an `{% if %}`/`{% else %}` around two
  `{% include %}` calls.

- **Fixed:** `lore_detail.html` reversed its region, scene and plot links with a bare
  `{% url %}`. evennia_regions, evennia_scenes and evennia_plots are soft dependencies —
  a game can install the model side, so the links populate, without mounting the
  partner's `urls.py`, or can mount it under different route names. Any of those turned
  the whole detail page into a `NoReverseMatch` 500. Now resolved with
  `{% url ... as var %}`, which assigns an empty string instead of raising; the partner's
  name renders as plain text when its route is absent.

- **Fixed:** `lore_list.html` tried to accumulate the active filters into a query string
  with nested `{% with %}` blocks, so that paging could preserve them. That cannot work —
  a `{% with %}` assignment dies at its own `{% endwith %}` — and the value was never
  passed to the pagination partial either. Every page-2 link silently dropped the filter
  and showed page 2 of the unfiltered list. `LoreListView` now supplies a urlencoded
  `extra_params` (the request's query string minus `page`), which the template passes on.

- **Fixed:** the usage examples inside `_pagination.html` and `_empty_state.html` named
  `website/partials/...` paths that do not exist in this contrib, and `_pagination.html`
  documented `extra_params` as needing a trailing `&` that the partial itself adds.

- **Added:** `TestLoreListRenders` and friends — every lore page (list, detail,
  compendium, approval queue, create/edit form, lean form, history, diff) is now
  rendered for real via `response.render()`, with the test module doubling as a test
  URLconf. The partner-link seam is tested from both sides, against a second URLconf
  that mounts stub region/scene/plot routes.

---

## [0.1.3] — 2026-07-05 — fix app-label defaults and gate hardening

- `LORE_SCENES_APP_LABEL` default changed from `"scenes"` → `"evennia_scenes"`.
- `LORE_PLOTS_APP_LABEL` default changed from `"plots"` → `"evennia_plots"`.
- `LORE_REGIONS_APP_LABEL` default changed from `"regions"` → `"evennia_regions"`.
  (`LORE_RPTRACKER_APP_LABEL` was already `"evennia_rptracker"` — no change.)
- `LoreConfig.ready()` membership gate replaced with the robust
  `apps.is_installed(label) or any(cfg.label == label …)` pattern via an
  inline `_app_present()` helper; eliminates false negatives for AppConfig-path
  installs.
- Same gate hardening applied to the rptracker membership check in
  `integrations/xp.py` (`collect_lore_inspiration`).
- Updated all `_get_model(…)` third-arg defaults in `commands.py`, and all
  `getattr(settings, …)` defaults in `views.py`, `selection.py`, and
  `integrations/xp.py` to match.

---

## [0.1.2] — 2026-07-05 — add LoreInspirationCredit and XP integration module

- `LoreInspirationCredit` model: per-`(LoreSceneLink, character_id)` XP eligibility
  row. Used as `source_ref_id` for `XPLog(LORE_INSPIRATION, ...)` so the batch is
  idempotent across re-runs. Migration `0002_loreinspirationcredit`.
- `evennia_lore/integrations/xp.py` — new module with two collectors:
  - `collect_lore_authored(window_end)` — 1 XP per published `LoreEntry` authored
    within the window; skips already-awarded entries via `XPLog` pre-fetch.
  - `collect_lore_inspiration(window_end)` — 0.5 XP per `(LoreSceneLink, participant)`
    pair; participant discovery unions `SceneParticipant` rows (gated on
    `LORE_SCENES_APP_LABEL`) and `RPSessionPartner` rows (gated on
    `LORE_RPTRACKER_APP_LABEL`); falls back gracefully when either app is absent.
- Register in `settings.py`:
  ```python
  XP_COLLECTORS += [
      ("lore_authored",    "evennia_lore.integrations.xp.collect_lore_authored"),
      ("lore_inspiration", "evennia_lore.integrations.xp.collect_lore_inspiration"),
  ]
  ```

## [0.1.1] — consume EditingMixin from evennia-links

- `EditingMixin` removed from `evennia_lore/editing.py` (file deleted). The mixin
  is now imported from `evennia-links>=0.3`. No behaviour change; the mixin API is
  identical.
- **Upgrade path:** if you imported `EditingMixin` from `evennia_lore.editing`,
  change to `from evennia_links import EditingMixin`. Add `evennia-links>=0.3` to
  your `INSTALLED_APPS` entry (it was already a transitive dep of `evennia-lore`).

## [0.1.0] — 2026-06-27 — initial extraction

- `LoreTag` model: major/minor tags with `is_major` flag for thematic grouping.
- `LoreEntry(AbstractArchived)` model: full status lifecycle (DRAFT → SUBMITTED →
  PUBLISHED / REJECTED), PUBLIC/RESTRICTED privacy, moderation (flag/review), version
  history snapshots via `LoreVersion`. `LoreEntry.create_entry()` atomically assigns
  `entry_number` with retry hardening (mirrors `Job.create_job` from evennia-jobs).
- `LoreVersion(AbstractVersion)`: append-only edit snapshots; rollback support.
- 4 bridge models (owned by evennia-lore; integer soft-references on the partner side):
  - `LoreAcquisition` — per-character compendium row; `session_id` soft-ref (rptracker).
  - `PlotLoreLink` — `thread_id` soft-ref (plots).
  - `LoreSceneLink` — `scene_id` soft-ref (scenes).
  - `LoreRegionLink` — `region_id` soft-ref (regions); replaces former `LoreEntry.regions` M2M.
- 4 signals: `lore_entry_created`, `lore_entry_published`, `lore_entry_edited`, `lore_acquired`.
- `select_passive_lore()` trickle engine: weighted-random acquisition at session end; lean
  multiplier; weekly ceiling; degrades gracefully when no context provider is configured.
- `LORE_SESSION_CONTEXT_PROVIDER` seam: cross-domain context (room/region/thread IDs)
  supplied by a settings-configured callable; engine degrades to tag-only when absent.
- Configurable staff lock via `LORE_STAFF_LOCK` (default `"cmd:perm(Builder)"`); consistent
  across commands, web views, and API.
- 5 commands: `CmdLore` (+lore), `CmdInvestigate` (+investigate/+inv), `CmdShare` (+share),
  `CmdHint` (+hint), `CmdForget` (+forget). EvEditor integration for multi-line submission.
- Optional `evennia-accessibility` integration for screen-reader-friendly output.
- `EditingMixin`: generic EvEditor + difflib version-editing mixin (candidate for future
  hoisting into evennia-links once the plots contrib ships its copy).
- Website surface (`[web]` extra): `LoreListView`, `LoreDetailView`, `LoreCompendiumView`,
  `LoreApprovalQueueView`, `LoreCreateView`, `LoreEditView`, `LoreVersionHistoryView`,
  `LoreVersionDiffView`, `LoreLeanView`, `LoreApproveView`, `LoreRejectView` + accessible
  forms and Bootstrap 4 templates.
- DRF API (`[web]` extra): `LoreEntryViewSet`, `LoreTagViewSet` — self-contained (explicit
  auth/pagination/filter classes; RESTRICTED body hidden via acquisition ownership check).
- Connect soft-ref cleanup hooks registered in `LoreConfig.ready()` for all 3 partner apps
  (scenes, plots, regions), gated on each label being present in `INSTALLED_APPS`.
- rptracker listener registered in `LoreConfig.ready()` only when rptracker is present.
