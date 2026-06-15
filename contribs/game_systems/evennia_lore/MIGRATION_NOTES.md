# Migration Notes — evennia-lore

## Source inventory

Extracted from a private Evennia game project.

| Source module | Contrib module | Notes |
|---|---|---|
| `world/lore/models.py` | `models.py` | `LoreTag`/`LoreEntry`/`LoreVersion` copied; source game docstrings stripped; `AbstractArchived`/`AbstractVersion` rebased from `evennia_links`; `regions` M2M removed (see below) |
| `world/lore/signals.py` | `signals.py` | Direct copy |
| `world/lore/apps.py` | `apps.py` | Rewritten for contrib: partner-label gating, cleanup hooks, trickle listener |
| `world/lore/admin.py` | `admin.py` | Rewritten; RUF012 noqa added |
| `world/lore/selection.py` | `selection.py` | Rebased; `_resolve_context()` provider seam added (A4 from source game) |
| `world/lore/providers.py` | _not shipped_ | source game-specific cross-domain context provider; consumers write their own |
| `commands/editing.py` | _deleted in v0.1.1_ | `EditingMixin` hoisted into `evennia-links>=0.3`; imported from there |
| `commands/lore.py` | `commands.py` | All 5 commands rebased; `is_staff` from `LORE_STAFF_LOCK`; partner app imports lazy via `_get_model()` helper; `uses_screenreader` optional-import fallback |
| `world/links/models.py` (LoreAcquisition, PlotLoreLink, LoreSceneLink) | `models.py` | Bundled with their owning contrib; foreign edges are integer soft-refs (A1) |
| `world/links/models.py` (LoreRegionLink) | `models.py` | New bridge introduced in A2 to replace the `LoreEntry.regions` M2M |
| `web/website/permissions.py` | `permissions.py` | Copy; perm configurable from `LORE_STAFF_LOCK` |
| `web/website/views/_authoring.py` | `authoring.py` | Copy; `AuthoringMixin` (renamed from source game mixin) |
| `web/website/forms.py` (Lore forms) | `forms.py` | Rebased onto `AccessibleModelForm`/`AccessibleForm` |
| `web/website/views/lore.py` | `views.py` | 11 CBVs; imports rebased; soft-ref resolution for sidebar; `AuthoringMixin` (renamed from source game mixin) |
| `web/website/urls.py` (lore patterns) | `urls.py` | Extracted; flat URL names |
| `web/templates/website/lore_*.html` | `templates/evennia_lore/lore_*.html` | Form partials rebased to `evennia_accessibility/`; `cov-*` CSS class names replaced with generic Bootstrap |
| `web/templates/website/partials/_pagination.html` | `templates/evennia_lore/_pagination.html` | Shipped copy |
| `web/templates/website/partials/_empty_state.html` | `templates/evennia_lore/_empty_state.html` | Shipped copy |
| `web/api/serializers.py` (Lore serializers) | `api/serializers.py` | Rebased; permission helper imported from contrib's permissions module |
| `web/api/filters.py` (LoreEntryFilter) | `api/filters.py` | Rebased; region filter via LoreRegionLink method |
| `web/api/views.py` (LoreEntryViewSet) | `api/views.py` | Self-contained: explicit pagination/auth/permission/filter classes |
| `web/api/pagination.py` | `api/pagination.py` | Renamed `LoreCursorPagination` |
| `web/api/urls.py` (lore registrations) | `api/urls.py` | Extracted |

## Key divergences from source game

**Bridge models bundled with evennia_lore.** In the source game, `LoreAcquisition`,
`PlotLoreLink`, `LoreSceneLink`, and `LoreRegionLink` live in `world/links/models.py`
per the domain-island architecture rule. In the contrib they are in `models.py` because
`evennia_lore` owns them (contributing/consuming role per the bridge-ownership convention).

**`LoreEntry.regions` M2M → `LoreRegionLink` integer soft-ref.** The source game's
`LoreEntry.regions` ManyToManyField was a direct FK to `world.regions.Region`, creating
a migration-time dependency on that app. Replaced with `LoreRegionLink(entry, region_id)`
so the bridge table has no dependency on the regions app.

**Cross-domain bridge FK edges are integer soft-references.** `PlotLoreLink.thread_id`,
`LoreSceneLink.scene_id`, and `LoreAcquisition.session_id` are plain integer fields (no FK
constraint on the partner app). Hard-deletion is compensated by `connect_soft_ref_cleanup()`
hooks registered in `LoreConfig.ready()`.

**Trickle context-provider seam (`LORE_SESSION_CONTEXT_PROVIDER`).** In the source game,
`selection.py` directly imported from `world.links`, `world.plots`, and `world.scenes` to
resolve session context (room_id / region_id / thread_ids). The contrib exposes this as a
settings-resolved callable so the trickle engine works standalone. Without a provider,
the engine degrades to tag-only weighting.

**`world/lore/providers.py` not shipped.** This is the source game's concrete provider
that reads `RPSessionSceneLink → ScenePlotLink → thread_ids` and `RegionMembership →
region_id`. Consumers write their own provider returning the required context dict.

**Staff permission configurable via `LORE_STAFF_LOCK`.** The source game hardcoded
`perm(Builder)` in commands and web views. The contrib resolves this from the setting,
consistent across commands, website views, and the API.

**`EditingMixin` hoisted into `evennia-links`.** Previously shipped as a local copy in
`evennia_lore/editing.py`. As of v0.1.1, `commands.py` imports it from `evennia-links>=0.3`
and the local file has been removed. Consumers who imported from `evennia_lore.editing`
should update to `from evennia_links import EditingMixin`.

**`cov-*` CSS class names stripped from templates.** Replaced with generic Bootstrap 4
equivalents (`table-responsive`, `h6`, `mb-3`, etc.).

**Object FK `related_name` set to `"+"`.** The `rooms` and `objects_tagged` M2Ms on
`LoreEntry` use `related_name="+"` to avoid reverse accessor name collisions when both the
contrib and the source game's `lore` app are in `INSTALLED_APPS` at the same time (e.g.
during migration generation or testing).

**Constraint name prefixed with `evennia_lore_`.** `loreentry_title_published_unique` is
renamed to `evennia_lore_title_published_unique` for the same reason.

**FK dependency pinned to `("objects","__first__")`.** Portable across Evennia installs.

## v0.1.0 extracted from source MUSH project at commit: _see git tag in private repo_
