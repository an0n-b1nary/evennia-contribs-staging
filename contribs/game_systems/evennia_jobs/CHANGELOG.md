# Changelog — evennia-jobs

All notable changes to `evennia-jobs` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## 0.7.1 — 2026-10-12

- Guests retain plain private requests and bug reports; player questionnaires remain unavailable until a dedicated admissions flow is installed.

## 0.7.0 ? 2026-10-11

- Add attributed author withdrawal, domain-owned forms and transactional review/withdrawal signals.

## [0.6.1] - 2026-10-10

- **Added:** a player guide page for evennia-guides, `requests` (requests, bugs
  and issue reports, and following up), in `guides/` and the package data. It
  describes the system in general terms, without exact numbers, and links only
  to pages this contrib or its required dependencies ship. Without
  evennia-guides it's ignored.

## [0.6.0] - 2026-10-10

- **Added:** every colour in the stylesheet is a shared `--evennia-color-*` theme
  token with its previous colour as the fallback, so a host stylesheet that
  sets the tokens on `:root` rethemes this contrib's pages along with the
  others. Nothing changes until a host sets one. The token list is in
  evennia-accessibility's README.

## [0.5.0] - 2026-10-10

- **Added:** settings-owned request questionnaires with shared command/web
  validation, required acknowledgements, resumable in-game answers, and web forms.
- **Added:** preserved submission revisions with saved question wording, explicit
  approval/decline/change-request decisions, reviewer attribution and explanations.
  Revisions require staff to request changes; stale submissions and reviews fail.
- **Added:** transactional `request_approved` seam for optional partners. Duplicate
  approvals and ordinary ticket-status changes never repeat partner work. Listener
  failure rolls back the review and transactional writes.
- **Added:** read-only proposal history in ticket commands, web pages, admin and
  the existing privacy-filtered API. Existing tickets retain their workflow.

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

## [0.3.0] - 2026-10-09

- **Added:** the request, bug and issue forms prefill their title and
  description from `?title=` and `?description=` (capped at 255 and 2,000
  characters). A guide page's "Ask about this page" link uses this. The
  submitter still edits and submits the form; nothing is created from the
  link alone.

## [0.2.1] - 2026-10-09

- **Fixed:** the website now resolves the acting character from the account's
  playable characters through `evennia_links.characters.web_character`, so a
  visitor who is not connected in-game still acts as their character. Before, only
  a live puppet counted: pages and writes that need a character treated the
  visitor as having none ("A puppeted character is required") unless the account
  was also in the game. Requires evennia-links 0.8.

## [0.2.0] - 2026-10-07

- **Added:** `evennia_jobs.integrations.staff_review.file_review_job(title,
  description)`, a ready-made value for the flag hooks other contribs expose:
  `RPTRACKER_FLAG_REVIEW_HOOK` (evennia-rptracker) and
  `BOARDS_ANTIGAMING_REPORTER` (evennia-boards). It files an authorless
  `DISCUSS` ticket, the staff-only type, and returns the `Job`. Games no longer
  have to write this wrapper themselves; the source project kept two copies of
  it.

## [0.1.4] - 2026-10-02

- **Changed:** web templates use the self-contained namespaced stylesheet and
  table, metadata, and empty-state conventions.

- **Changed:** the optional web extra now depends on ``evennia-links>=0.5``;
  HTTP staff checks use its shared predicate.
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

## [0.1.3] - 2026-10-02

- Stack labelled table rows below 640px while retaining table semantics and desktop columns.

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
