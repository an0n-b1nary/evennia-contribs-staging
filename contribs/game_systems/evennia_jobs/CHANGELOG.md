# Changelog — evennia-jobs

## 0.1.0 — initial extraction

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
