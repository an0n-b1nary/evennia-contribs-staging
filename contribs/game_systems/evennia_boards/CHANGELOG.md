# Changelog — evennia-boards

All notable changes to `evennia-boards` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.0] — 2026-10-02

- **Fixed:** the login listener emits `board_unread_notified` once per subscribed
  board with new posts, with account, board and unread count.
- **Changed:** the board index shows latest post, author and per-account web unread
  counts. Read markers persist after successful full-board renders, independently
  of subscription notification timestamps; archived posts are excluded.

## [0.2.0] — 2026-10-02

- **Fixed:** long post titles truncate in the flexible title area while the
  author/date byline and Reply/Edit controls remain readable and non-shrinking.

- **Changed:** web templates use the self-contained namespaced stylesheet and
  table, metadata, and empty-state conventions.

- **Changed:** HTTP staff checks now use ``evennia_links.is_staff_user`` and
  the web-wide ``EVENNIA_WEB_STAFF_LOCK`` policy.
- **Fixed:** the board list page raised `TemplateSyntaxError` on every request.
  `BoardListView` attached the per-board post count as `board._post_count`, and
  Django's template engine refuses to resolve any variable whose name begins with
  an underscore. Renamed to `board.post_count`. No view test caught this because
  building a view's context compiles no template; a template compile sweep
  (`scripts/check_templates.py`) now runs in pre-commit and CI.

- **Added:** `TestWebPagesRender` — every board page (list, detail, new post, reply,
  edit) is now rendered for real via `response.render()`, with the test module doubling
  as a test URLconf. The template compile sweep added alongside the fix above is a
  floor, not a substitute: compiling a template resolves no `{% extends %}` or
  `{% include %}` target and reverses no URL.

---

## [0.1.1] — 2026-07-05 — fix README label example

- `BOARDS_CALENDAR_APP_LABEL` README example corrected from `"calendar"` to
  `"evennia_calendar"` to match `evennia_calendar`'s real Django app-label.
  The code default (`None`) was never wrong; only the documentation example
  referenced a non-resolving bare label.

---

## [0.1.0] — 2026-06-07 — initial extraction

Initial extraction. All features drawn from a production MUSH installation.

### Added

**Models**
- `Board` — named bulletin board with OOC/IC type, ordering, and read-only flag
- `Post(AbstractArchived)` — per-board auto-numbered threaded posts; `xp_flagged` / `xp_flag_reason` for anti-gaming sweep
- `Subscription` — account-level board subscriptions with `last_notified_at` timestamp
- `PostVersion(AbstractVersion)` — append-only edit history
- `PostCalendarLink(AbstractAuthoredLink)` — optional integer soft-ref bridge to calendar events

**Commands**
- `CmdBoard` (`+bb` / `+board`) — list boards, read posts, post, reply, subscribe, unsubscribe, archive (staff), set staff lock

**Web**
- Board list, board detail, post-create, post-reply, post-edit CBVs with `BoardsAuthoringMixin`
- REST API (read-only): `BoardViewSet`, `PostViewSet` with cursor pagination and explicit DRF auth

**Integrations**
- `integrations/xp.py` — cutscene collector + anti-gaming sweep for evennia-xp (optional)
- `BOARDS_ANTIGAMING_REPORTER` seam — dotted-path callable for staff ticket creation without importing a jobs app

**Signals**
- `post_created` — fires after `Post.create_post()`
- `board_unread_notified` — fires after login notification sweep

**Login listener**
- `SIGNAL_ACCOUNT_POST_LOGIN` → `_notify_board_subscriptions` — auto-wired in `BoardsConfig.ready()`; no game-side code required

**Settings seams**
- `BOARDS_STAFF_LOCK` (default `cmd:perm(Builder)`)
- `BOARDS_CALENDAR_APP_LABEL` — activates `PostCalendarLink` soft-ref cleanup hook
- `BOARDS_ANTIGAMING_REPORTER` — dotted path to the staff reporting callable
