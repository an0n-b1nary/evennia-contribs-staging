# Changelog — evennia-boards

All notable changes to `evennia-boards` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
