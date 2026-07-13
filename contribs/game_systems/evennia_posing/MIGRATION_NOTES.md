# Migration notes — evennia_posing v0.1.0

Audit trail for the initial extraction. Useful for upstream reviewers,
downstream adopters reconciling vendored copies, and future drift detection
against the source.

## Source inventory

| Source file | What we took |
|---|---|
| `commands/posing.py` | `CmdPose`, `CmdEmit`, `CmdSemipose`, `CmdPot`, `CmdLastPose`, `CmdPoseHeader`, `CmdHighlight`, `format_pose_time()` |
| `world/utils/highlighting.py` | `highlight_names()` — verbatim, already source-agnostic |
| `typeclasses/characters.py` | `last_pose_time`/`pose_status`/`last_pose_text` AttributeProperty fields, `record_pose()`, `at_say()`, `at_post_move()` (pose-timer slice only), `at_post_puppet()` (pose-timer slice only), `at_post_unpuppet()` (pose-timer slice only), `msg()` (header + highlight slice only) |
| `typeclasses/rooms.py` | `get_characters_by_pose_time()`, `get_display_characters()`, `format_appearance()` (highlight slice only) |
| `commands/tests.py` | `TestCmdHighlight` — verbatim port |
| `commands/tests_posing.py` | `TestCmdSemipose` — verbatim port |
| `world/utils/tests.py` | `TestHighlightNames` — verbatim port |

## Rename map

| Source name | Contrib name |
|---|---|
| Direct `capture_to_scene()` / `record_rp_activity()` calls inside `record_pose()` | Replaced with `pose_recorded.send(...)` — a Django signal. Downstream wiring moves to the consuming game's glue code (see README "Integration recipe" step 4). |
| `Character(ObjectParent, DefaultCharacter)` | `PosingCharacterMixin` — a bare mixin, no `ObjectParent`/`DefaultCharacter` coupling. The consuming game composes the full MRO. |
| `Room(ObjectParent, DefaultRoom)` | `PosingRoomMixin` — same pattern. |

## New code (not in source)

- `signals.py` — `pose_recorded = Signal()`. Did not exist in the source;
  the source called scene/rptracker functions directly from `record_pose()`
  because those systems lived in the same codebase. The signal is the
  decoupling seam a standalone contrib requires.
- README "Integration recipe" step 4 documents a **single ordered listener**
  pattern rather than multiple independent `@receiver` connections, because
  Django does not guarantee delivery order across receivers and at least one
  known consumer (the scene bridge in `evennia_rptracker`) depends on
  ordering (scene state must be current before RP-session tracking reads
  room state).

## Deliberately omitted

Everything below is **later-phase or leaf-feature territory**, not part of
the foundational pose pipeline. Extracting it here would recreate the
producer/consumer coupling this contrib is designed to avoid.

- **Ignore-filtering** (`msg()`'s ignore-list block) — belongs to
  `evennia_social` (a leaf consumer layered on top via cooperative `msg()`
  chaining; see README "Layering with evennia-social").
- **`_record_visit()` / `visited_rooms`** — feeds `@tel`'s "visited rooms"
  access mode, a leaf feature (`evennia_social`).
- **`get_display_name()`'s `short_desc` suffix** — part of the `+finger`
  profile system (`evennia_social`), not the pose pipeline.
- **`_notify_unread_pages()` / `_notify_xp_summary()`** — page-system and
  XP-system concerns respectively; neither belongs in posing (the former is
  `evennia_social`'s; the latter is the consuming game's own).
- **`room_type` attribute** — read by multiple unrelated systems
  (`evennia_rptracker`, `evennia_scenes`, `+where`) and owned by none of
  them. Stays a game-level Room attribute; this contrib never references it.
- **Dedicated command tests for `CmdPose`/`CmdEmit`/`CmdPot`/`CmdLastPose`/
  `CmdPoseHeader`** — the source project did not have these (only
  `CmdHighlight` and `CmdSemipose` were covered). `tests.py` in this contrib
  adds coverage for the previously-untested commands and for the
  `pose_recorded` signal and mixin cooperative-`msg()` behavior, since a
  standalone contrib needs to be verifiable without the source game's test
  suite around it.
