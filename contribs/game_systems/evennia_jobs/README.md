# evennia-jobs

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before submission to `evennia/evennia`.

Staff ticket system for [Evennia](https://www.evennia.com/) games. Players submit
requests, bug reports, and anonymised issue reports; staff manage the queue via
in-game commands and (optionally) a web interface + REST API.

---

## What's included

| Component | Purpose |
|---|---|
| `Job` + `JobComment` models | Ticket + comment storage |
| `Job.create_job()` | Public programmatic API for filing tickets from other systems |
| 5 commands | `CmdRequest`, `CmdBug`, `CmdIssue` (players); `CmdDiscuss`, `CmdJobs` (staff) |
| Website surface (`[web]`) | 5 views, accessible forms, Bootstrap 4 templates |
| DRF API (`[web]`) | Read-only `JobViewSet` with privacy filtering |

---

## Installation

**Core** (models + commands, no web deps):

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_jobs&egg=evennia_jobs"
```

**With web + API surface** (requires evennia-accessibility, DRF, django-filter):

```
pip install -e "...(same URL)...[web]"
```

Add to `INSTALLED_APPS` in `server/conf/settings.py`:

```python
INSTALLED_APPS += ["evennia_jobs"]
# If using the [web] extra, also add:
INSTALLED_APPS += ["evennia_accessibility"]
```

**Run migrations:**

```
evennia migrate evennia_jobs
```

---

## Add commands to your CharacterCmdSet

```python
from evennia_jobs.commands import CmdBug, CmdDiscuss, CmdIssue, CmdJobs, CmdRequest

class CharacterCmdSet(CmdSet):
    def at_cmdset_creation(self):
        self.add(CmdRequest)
        self.add(CmdBug)
        self.add(CmdIssue)
        self.add(CmdDiscuss)
        self.add(CmdJobs)
```

---

## Settings

| Setting | Default | Description |
|---|---|---|
| `JOBS_STAFF_LOCK` | `"cmd:perm(Builder)"` | Lock string for `+discuss` and `+jobs`; also used by web views and API for staff checks |

The staff check is consistent across commands, website views, and the API — all read
from `JOBS_STAFF_LOCK`.

---

## Screen-reader support (optional)

Install `evennia-accessibility` (`[web]` pulls it automatically) and the commands
will use accessible plain-text formatting when `uses_screenreader(character)` returns
`True`. Without the package, formatting falls back to standard coloured output.

---

## Web surface (requires `[web]`)

Add the URL patterns to your game's URL config (no namespace):

```python
from django.urls import include, path
urlpatterns += [path("jobs/", include("evennia_jobs.urls"))]
```

URL names: `job-list`, `job-all`, `job-create`, `job-detail`, `job-comment`.

The templates extend `website/base.html` (stock Evennia website base, which provides
`titleblock` and `content` blocks). The `breadcrumbs` block is defined but silently
dropped on games that don't use it — harmless. To use a custom base template, override
`template_name` on the views or set a project-wide `website/base.html`.

Add a navigation link to the jobs list from your own nav template:

```html
<a href="{% url 'job-list' %}">Tickets</a>
```

---

## REST API (requires `[web]`)

```python
from django.urls import include, path
urlpatterns += [path("api/v1/", include("evennia_jobs.api.urls"))]
```

Generates `GET /api/v1/jobs/` and `GET /api/v1/jobs/<id>/`.

Authentication uses Django session auth (`SessionAuthentication`); all endpoints
require an authenticated user (`IsAuthenticated`). The viewset sets these explicitly —
it does not depend on your global `REST_FRAMEWORK` configuration.

Privacy rules:
- Staff (per `JOBS_STAFF_LOCK`) see all non-closed tickets.
- Non-staff see only tickets they authored or are assigned to; `+discuss` excluded.
- ISSUE reporter names are masked (`null`) for non-staff.
- Staff-only comments are omitted for non-staff.

---

## Programmatic API

File tickets from your own code without the commands (useful for auto-flagging,
plot events, etc.):

```python
from evennia_jobs.models import Job, JobComment, JobType

# File a ticket (author=None for system-generated tickets):
job = Job.create_job(
    job_type=JobType.DISCUSS,
    author=None,
    title="Auto-flag: suspicious session",
    description="RPSession #42 was flagged for pose spam.",
)

# Add a comment:
JobComment.create_comment(
    job=job,
    author=staff_char,
    content="Reviewing now.",
    is_staff_only=True,
)
```

This replaces the un-shipped `review.py` adapter from the source game. Wire your own
hook to call `Job.create_job` as needed.

---

## Version history

See [CHANGELOG.md](CHANGELOG.md).
