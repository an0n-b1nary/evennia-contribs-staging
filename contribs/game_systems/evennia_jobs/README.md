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
| Request-form registry | Settings-owned questionnaires with matching command and web validation |
| `RequestSubmission` + `RequestDecision` | Preserved revisions, saved question wording, explicit staff decisions |
| `integrations.staff_review` | Ready-made `(title, description)` reporter for the rptracker and boards flag hooks |
| 5 commands | `CmdRequest`, `CmdBug`, `CmdIssue` (players); `CmdDiscuss`, `CmdJobs` (staff) |
| Website surface (`[web]`) | Accessible ticket, questionnaire, revision and staff-review pages |
| DRF API (`[web]`) | Read-only `JobViewSet` with privacy filtering |

---

## Installation

**Core** (models + commands, no web deps):

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_jobs&egg=evennia_jobs"
```

**With web + API surface** (requires evennia-accessibility, DRF, django-filter):

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_jobs&egg=evennia_jobs[web]"
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
| `JOBS_STAFF_LOCK` | `"cmd:perm(Builder)"` | Lock string for `+discuss` and `+jobs`; HTTP staff checks use the shared web policy |
| `JOBS_REQUEST_FORMS` | `{}` | Enabled structured request forms, described below |

The staff check is consistent across commands, website views, and the API — all read
from `JOBS_STAFF_LOCK` for in-game commands. HTTP views use `EVENNIA_WEB_STAFF_LOCK`
through `evennia_links.is_staff_user`.

## Structured requests

Games configure question sets; Jobs supplies their submission and review workflow.
No building, crafting, regions or other domain partner is required. Ordinary
free-text requests keep working alongside structured forms.

```python
JOBS_REQUEST_FORMS = {
    "proposal": {
        "label": "Propose an addition",
        "description": "Explain the addition you would like staff to review.",
        "questions": [
            {"key": "name", "label": "Name", "type": "text", "max_length": 255},
            {"key": "description", "label": "Describe the addition"},
            {"key": "purpose", "label": "Purpose", "type": "choice",
             "choices": ["home", "shop", "public"]},
            {"key": "notes", "label": "Additional notes", "required": False},
            {"key": "reuse", "label": "I acknowledge that my contribution may be reused.",
             "type": "boolean"},
        ],
    },
}
```

Form and question keys are stable lowercase identifiers, up to 64 characters.
Question types are `text`, `longtext` (default), `choice`, and `boolean`.
Questions default to required, with a 10,000-character limit; `help_text` is
optional. A required boolean is an acknowledgement that must be affirmative.
The shorthand `("name", "Question wording")` defines a required long-text question.
Set `enabled=False` on a form to hide it and refuse new submissions or revisions;
saved history remains readable. Configuration errors fail explicitly.

In game:

```text
+request/forms
+request/form proposal=My proposal
+request/answer name=The Reading Room
+request/answer description=A quiet place with a shared table.
+request/answer purpose=public
+request/answer notes=
+request/answer reuse=yes
+request/preview
+request/submit
```

Use `+request/edit <key>` for the multiline editor on text questions; save with
`:w` and return with `:q`. Choices and acknowledgements use `/answer`.
The questionnaire is saved on the character across reloads. `/resume` shows
the next unanswered question, `/answer` can change any answer, and `/cancel`
discards unsubmitted answers. Web forms are linked from My Tickets and use
`/jobs/forms/<key>/` (`job-request-form`). Both surfaces use the same validation.
Form changes during completion require reloading or restarting, so acknowledgement
wording cannot change unnoticed.

Staff review the displayed revision explicitly:

```text
+jobs/approve 12 1=This fits the setting.
+jobs/decline 12 1=Please use the existing location instead.
+jobs/revise 12 1=Please describe the entrance.
```

The website offers the same outcomes at `/jobs/<pk>/review/`
(`job-request-review`). HTTP staff policy and the acting character's
`JOBS_STAFF_LOCK` must both permit a review. Every decision records its explanation,
reviewer and timestamp. Decisions are independent of ticket status: changing status,
closing or reopening a ticket never grants approval or emits an approval signal.

After **Changes requested**, the submitter uses `+request/revise 12` or the
**Revise proposal** link (`job-request-revise`). A new revision retains the old
answers and decision; acknowledgements must be renewed. Pending, approved and
declined revisions cannot be overwritten. Stale reviews and resubmissions are
refused. The ticket title stays unchanged across revisions. Corrections to
free-text tickets still use comments. Collaborator consent
is a domain review concern: one person's acknowledgement cannot cover another's work.

### Programmatic submission and approval listeners

```python
from evennia_jobs import submit_request

submission = submit_request(
    author=character, form_key="proposal", title="My proposal",
    answers={"name": "Reading Room", "description": "A quiet library.",
             "purpose": "public", "reuse": True},
)
```

For a requested revision, also pass `job=submission.job` and
`expected_revision=submission.revision`. `review_request(job=..., reviewer=...,
outcome="approved", reason=..., expected_revision=...)` enforces the Jobs staff lock.
Treat submissions and decisions as append-only; use these services for writes.
Their snapshots are read-only in the admin and appear in ticket detail and the
existing privacy-filtered, read-only API.

Optional partners connect to `evennia_jobs.signals.request_approved` in a gated
`AppConfig.ready()` integration. Receivers get `sender=RequestSubmission`,
`submission` and `decision`; filter by `submission.form_key`. Jobs never imports
partners or creates their content. A Pattern receiver, for example, can create a
draft for staff to finish instead of immediately publishing it.

The signal runs **inside the review transaction**. A failing receiver rolls back
the decision and transactional database changes, allowing a retry. Repeating an
already recorded approval returns its decision without emitting again. Receivers
should use `submission.pk` as an idempotency key and schedule external effects with
`transaction.on_commit()`; this is not a durable external-message delivery queue.
With no listeners installed, approval simply records staff authorization.

Upgrade with ordinary migrations. Existing jobs and comments remain unchanged;
the new tables begin empty. Do not regenerate earlier migrations.

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

### Staff review of automated flags

evennia-rptracker and evennia-boards flag suspicious activity and then call a
dotted-path setting with `(title, description)` so a person can review it. Point both
at the shipped reporter:

```python
# settings.py
RPTRACKER_FLAG_REVIEW_HOOK = "evennia_jobs.integrations.staff_review.file_review_job"
BOARDS_ANTIGAMING_REPORTER = "evennia_jobs.integrations.staff_review.file_review_job"
```

Each flag becomes an authorless `DISCUSS` ticket. `+discuss` is the staff-only type, so
the flagged player can't see it on the web or through the API. Any other code with a
`(title, description)` hook can use the same function. If filing fails, the error is
raised to the caller; both shipped callers log it and still record the flag.

## Theming

Every colour in this contrib's stylesheet is a shared `--evennia-color-*`
token with its usual colour as the fallback, so the pages look the same
until your game sets one. Set them on `:root` in your own stylesheet to
retheme these pages along with the other contribs'. The token list and an
example are in [evennia-accessibility's README](../../utils/evennia_accessibility/README.md#theme-tokens).

## Guide pages

The `guides/` directory holds player guide pages for
[evennia-guides](../../utils/evennia_guides/README.md): `requests`. They
explain the system to players in general terms, without exact numbers, and link
only to pages this contrib or its required dependencies ship. With
evennia-guides installed they appear on its web guide; without it they're
ignored. To restate one for your game, add a page with the same key to
`GUIDES_DIRS`.

---

## Version history

See [CHANGELOG.md](CHANGELOG.md).
