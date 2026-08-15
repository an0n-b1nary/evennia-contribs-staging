# Changelog — evennia-jobs

All notable changes to `evennia-jobs` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

- **Fixed:** the documentation comments at the top of `_empty_state.html` and
  `_pagination.html` spanned multiple lines. Django's template tag regex is not
  `DOTALL`, so a multi-line `{# ... #}` is not a comment — its text renders into the
  page, and the usage example inside each partial was a live `{% include %}` of the
  partial itself, recursing until the stack blew. Both are now `{% comment %}` blocks.
  Surfaced while building `evennia-maps`' web surface, whose tests render templates
  rather than only inspecting view context.

- **Fixed:** `job_form.html` and `job_comment_form.html` passed their Cancel link as
  `cancel_url="{% url 'job-list' %}"`. A tag nested inside a quoted argument does not
  parse — the tokenizer ends the outer `{% include %}` at the first `%}` — so both
  authoring forms were `TemplateSyntaxError`. Now resolved up front with
  `{% url ... as cancel_url %}`, which also degrades to an empty string (hiding the
  Cancel link) rather than raising when the routes are not mounted.

- **Added:** `TestWebPagesRender` — every jobs page (my tickets, the staff queue, ticket
  detail, all three submission forms, the comment form) is now rendered for real via
  `response.render()`, with the test module doubling as a test URLconf. Both fixes above
  were compile-time failures that no context-only view test could see.

---

## [0.1.0] — 2026-06-01 — initial extraction

- `Job` model: staff ticket with status lifecycle (open → in_review → answered → closed),
  priority levels (normal / high / urgent), ISSUE anonymity, global `job_number`, and
  `Job.create_job()` factory classmethod.
- `JobComment` model: append-only comments with `is_staff_only` flag and
  `JobComment.create_comment()` factory classmethod.
- `JobManager.by_priority()`: correct urgency-ordered queryset (avoids alphabetic
  sort pitfall on string enum values).
- 5 commands: `CmdRequest`, `CmdBug`, `CmdIssue` (player), `CmdDiscuss`, `CmdJobs`
  (staff). EvEditor integration for multi-line submissions.
- Configurable staff lock via `JOBS_STAFF_LOCK` setting.
- Optional `evennia-accessibility` integration for screen-reader-friendly command output.
- Website surface (`[web]` extra): `JobListView`, `JobAllView`, `JobDetailView`,
  `JobCreateView`, `JobCommentCreateView` + accessible forms and templates.
- DRF API (`[web]` extra): `JobViewSet` (read-only), `JobSerializer`, `JobFilter`,
  `JobsCursorPagination` — self-contained, does not rely on global REST_FRAMEWORK config.
