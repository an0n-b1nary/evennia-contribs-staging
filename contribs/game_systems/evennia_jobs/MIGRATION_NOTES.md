# Migration Notes — evennia-jobs

## Source inventory

Extracted from a private Evennia game project.

| Source module | Contrib module | Notes |
|---|---|---|
| `world/jobs/models.py` | `models.py` | Direct copy; source game references stripped |
| `world/jobs/apps.py` | `apps.py` | Explicit `label="evennia_jobs"` added |
| `world/jobs/admin.py` | `admin.py` | Import rebased |
| `world/jobs/migrations/` | `migrations/` | Generated fresh; FK dep pinned to `("objects","__first__")` |
| `commands/jobs.py` | `commands.py` | Imports rebased; `is_staff` local helper; `uses_screenreader` optional; staff lock configurable |
| `web/website/permissions.py` | `permissions.py` | Copied; perm configurable from `JOBS_STAFF_LOCK` |
| `web/website/views/_authoring.py` | `authoring.py` | Copied; `CoVAuthoringMixin` → `AuthoringMixin` |
| `web/website/forms.py` (JobCreateForm, JobCommentForm) | `forms.py` | Rebased onto `evennia_accessibility` base classes |
| `web/website/views/jobs.py` | `views.py` | Imports rebased; deprecated aliases removed |
| `web/website/urls.py` (jobs patterns) | `urls.py` | Extracted |
| `web/templates/website/job_*.html` | `templates/evennia_jobs/job_*.html` | Form partials rebased to `evennia_accessibility/` namespace |
| `web/templates/website/partials/_pagination.html` | `templates/evennia_jobs/_pagination.html` | Shipped copy (source game-local generic partial) |
| `web/templates/website/partials/_empty_state.html` | `templates/evennia_jobs/_empty_state.html` | Shipped copy (source game-local generic partial) |
| `web/api/serializers.py` (JobSerializer) | `api/serializers.py` | Rebased; permission helper imported locally |
| `web/api/filters.py` (JobFilter) | `api/filters.py` | Direct copy |
| `web/api/views.py` (JobViewSet) | `api/views.py` | Self-contained: explicit pagination/auth/permission classes |
| `web/api/pagination.py` (CovCursorPagination) | `api/pagination.py` | Renamed `JobsCursorPagination` |
| `web/api/urls.py` (jobs registration) | `api/urls.py` | Extracted |

## Divergences from source game

**`review.py` not shipped.** The source game has `world/jobs/review.py`, a thin
wrapper around `Job.create_job` that implements the `RPTRACKER_FLAG_REVIEW_HOOK`
contract. This is game-specific integration glue — consumers write their own hook
wrapper to suit their notification system. The public API is `Job.create_job(job_type,
author, title, description)` and `JobComment.create_comment(...)`.

**Staff perm now configurable.** `cmd:perm(Builder)` is the default but can be
overridden via `JOBS_STAFF_LOCK`. The permission check is consistent across commands,
web views, and the API (all use the same `permissions.py` helper).

**`CoVBaseModelForm`/`CoVBaseForm` → `AccessibleModelForm`/`AccessibleForm`.** The
source game's accessible form bases were extracted as `evennia-accessibility`. The
contrib's `forms.py` imports them from that contrib (`[web]` extra).

**API viewset is self-contained.** The source game's `JobViewSet` relied on global
`REST_FRAMEWORK` defaults for pagination, filter backends, and auth. The contrib sets
all these explicitly on the viewset so it works regardless of the consumer's
`REST_FRAMEWORK` configuration.

**FK dependency pinned to `("objects","__first__")`.** `makemigrations` would pin to
a game-specific `objects` migration. The contrib pins to `__first__` for portability
across Evennia installs.

## v0.1.0 extracted from source game commit: _see git tag in private repo_
