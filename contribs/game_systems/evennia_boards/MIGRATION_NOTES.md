# Migration Notes — evennia-boards

This document records intentional divergences between `evennia_boards` and the
source game installation it was extracted from. Games porting from the source
should read this alongside CHANGELOG.md.

## PostCalendarLink lives in the contrib (not world/links/)

The source game stores `PostCalendarLink` in a dedicated cross-domain bridge
app (`world/links/`) to keep board and calendar apps fully isolated at the model
layer. `evennia_boards` bundles `PostCalendarLink` directly in this package so
the contrib ships as a self-contained unit.

**Impact:** If you run both `evennia_boards` and a game-side bridge version of
`PostCalendarLink`, you will have two tables storing the same data. Pick one:
- Use the contrib model and drop your game-side one (migrate data if needed).
- Keep your game-side model and do not register `PostCalendarLink` cleanup from
  `BoardsConfig.ready()` (set `BOARDS_CALENDAR_APP_LABEL` to an app label that
  is not in `INSTALLED_APPS`).

## `Subscription.account` related_name

Source: `board_subscriptions`
Contrib: `evennia_board_subscriptions`

Renamed to avoid reverse-accessor clashes when both the source app and
`evennia_boards` are installed in the same project during testing.

## `PostVersion` base class

Source: `world/utils/versioning.AbstractVersion` (in-repo copy)
Contrib: `evennia_links.AbstractVersion` (hard dependency)

Both classes are API-identical. The contrib moves the dependency to
`evennia-links` so it can ship independently.

## `Post.AbstractArchived` base class

Same situation as `PostVersion` — source uses in-repo copy, contrib delegates
to `evennia_links.AbstractArchived`.

## Login notification wiring

Source: wired in `world/boards/apps.py::BoardsConfig.ready()`, which imports
`world.boards.listeners`.

Contrib: wired in `evennia_boards.apps.BoardsConfig.ready()`. The signal handler
deduplicates via `dispatch_uid="evennia_boards.notify_board_subscriptions"`. If
you run the source game **and** evennia_boards simultaneously (for testing),
both listeners fire — each sends its own notification message. Remove the
source listener before deploying the contrib in production.

## XP collector / sweep registry keys

Source uses `"world.boards.xp_integration.*"` dotted paths in `XP_COLLECTORS`
and `XP_ANTIGAMING_SWEEPS`. Swap these for the contrib paths:

```python
# settings.py
XP_COLLECTORS += [("cutscene", "evennia_boards.integrations.xp.collect_cutscene_posts")]
XP_ANTIGAMING_SWEEPS += ["evennia_boards.integrations.xp.sweep_cutscene_spam"]
```

## `_find_burst` is now internal

In the source game `_find_burst` was accessible from `world.xp.antigaming`.
It is now a private helper inside `evennia_boards.integrations.xp`. There is
no public API for it; do not import it from outside the module.
