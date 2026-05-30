# Migration Notes — evennia-links

## Source inventory

This contrib was extracted from a private Evennia game project. The following
source files map to the contrib modules listed:

| Source file | Contrib module | Notes |
|---|---|---|
| `world/utils/links.py` | `links.py` | New file authored in source game, then extracted |
| `world/utils/versioning.py` | `versioning.py` | Direct copy; example class names genericized |
| `world/utils/archiving.py` | `archiving.py` | Direct copy; example class names genericized |
| `world/utils/listeners.py` | `listeners.py` | New file authored in source game, then extracted |

## What was NOT extracted

**Concrete bridge models** — the source game has a `world/links/` Django app
containing ~13 concrete bridge models (`ScenePlotLink`, `LoreSceneLink`, etc.)
that connect domain apps within that specific game. These are **not** part of
this contrib. They remain in the source game as game-specific integration glue.

The `world/links/` app is intentionally not extracted; it serves as a
recipe/example for contrib consumers who want to wire multiple domain contribs
together in their own game.

The bridge-ownership convention in the README is the generalizable pattern
those models embody.

**NotificationDispatcher** — the source game's `world/notifications/` app is
an empty stub (Phase 8 work); the dispatcher architecture is planned but not
yet implemented. It will be extracted in a future release once built and
battle-tested in the source game.

## Rename map

Class names are unchanged between source and contrib. Docstring examples
that referenced the source game's domain app names were replaced with
generic placeholders.

## v0.1.0 extracted from source game commit: _see git tag in private repo_
