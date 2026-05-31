# Migration Notes — evennia-rptracker

## Source inventory

Extracted from a private Evennia game project. Source files and their
contrib equivalents:

| Source module | Contrib module | Notes |
|---|---|---|
| `world/rptracker/models.py` | `models.py` | Added `RPSessionSceneLink` (lives in `world/links/` in source game) |
| `world/rptracker/tracker.py` | `tracker.py` | Imports rebased to `evennia_rptracker.*` |
| `world/rptracker/signals.py` | `signals.py` | Direct copy; source game references stripped |
| `world/rptracker/antigaming.py` | `antigaming.py` | Direct copy; imports rebased |
| `world/rptracker/admin.py` | `admin.py` | Imports rebased |
| `commands/events/rptracker.py` | `commands.py` | Post-A2 version with pluggable hooks |
| `world/links/listeners.py` (partial) | `bridges_scenes.py` | Only the `on_rp_activity_recorded` listener |

## Structural divergences from source game

**`RPSessionSceneLink` location:** In the source game, bridge models between
domain apps live in a separate `world/links/` app (the domain-island pattern
forbids cross-app FKs). In this contrib the bridge is bundled with its owner
(`models.py`) because the contrib is self-contained.

**`RPSessionSceneLink.scene_id` is an integer, not a FK:** The source game
originally used a FK to `scenes.Scene`. This was converted to a
`PositiveBigIntegerField` before extraction so the bridge table has no DB
dependency on the optional scenes contrib. Cascade compensation is provided
by `evennia-links >= 0.2` (`connect_soft_ref_cleanup`).

**Lore trickle listener not shipped:** The source game's
`on_rp_session_ended` listener triggers passive lore acquisition. This is
game-specific reward logic and was not extracted. The `rp_session_ended`
signal is available for adopting games to wire their own reactions.

**Anti-gaming rules relocated from XP batch:** The source game originally
kept pose-spam and manual-end-abuse detection in an XP-domain module. These
were moved to `rptracker/antigaming.py` before extraction (anti-gaming
belongs to the system that tracks the activity). Rules for other content
types (cutscene spam, thread gaming) remain in the XP domain.

## v0.1.0 extracted from source game commit: _see git tag in private repo_
