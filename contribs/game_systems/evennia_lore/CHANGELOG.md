# Changelog — evennia-lore

## 0.1.2 — add LoreInspirationCredit and XP integration module

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

## 0.1.1 — consume EditingMixin from evennia-links

- `EditingMixin` removed from `evennia_lore/editing.py` (file deleted). The mixin
  is now imported from `evennia-links>=0.3`. No behaviour change; the mixin API is
  identical.
- **Upgrade path:** if you imported `EditingMixin` from `evennia_lore.editing`,
  change to `from evennia_links import EditingMixin`. Add `evennia-links>=0.3` to
  your `INSTALLED_APPS` entry (it was already a transitive dep of `evennia-lore`).

## 0.1.0 — initial extraction

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
