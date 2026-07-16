# Migration notes — evennia_social v0.1.0

Audit trail for the initial extraction. Useful for upstream reviewers,
downstream adopters reconciling vendored copies, and future drift detection
against the source. Companion to `evennia_posing/MIGRATION_NOTES.md` — read
that one first for the shared background (producer/consumer asymmetry,
signal-based decoupling).

## Source inventory

| Source file | What we took |
|---|---|
| `commands/social/finger.py` | `CmdFinger` — profile view/edit, `EvEditor` bio callbacks |
| `commands/social/discovery.py` | `CmdWhere`, `CmdHangouts` |
| `commands/social/filtering.py` | `CmdIgnore` — verbatim, already source-agnostic |
| `commands/social/messaging.py` | `CmdPage` |
| `commands/social/teleportation.py` | `CmdSummon`, `CmdJoin` |
| `commands/social/navigation.py` | `CmdOocTeleport`, `CmdHome` |
| `commands/social/ooc.py` | `CmdOoc` (with the scene-log coupling severed — see below) |
| `commands/social/roulette.py` | `CmdRoulette` (already a stub in source) |
| `commands/building.py` | `CmdRoomConfig` only (the hangout slice — `+roomconfig`, `/hangout`, `/hangout/clear`, and the config display). `CmdBuild`, its room-creation sibling in the same file, is a building-tools concern and stays behind. |
| `commands/staff.py` | `CmdTel` only — `CmdSoftBan` in the same file is a moderation command, not a teleportation feature, and stays behind (see report §10) |
| `world/utils/search.py` | `find_room()`, `find_room_for_player()` — generalized (see below) |
| `world/utils/social.py` | `is_staff()`, `get_connected_characters()` — verbatim |
| `typeclasses/characters.py` | `visited_rooms`/`_record_visit()`, `short_desc`/`get_display_name()`, `profile_*`/`followed_themes`, `last_pager`/`last_page_seen`/`_notify_unread_pages()`, `pending_summon_requests`, `home_room`, `msg()` (ignore-filter slice only), `at_post_move`/`at_post_puppet` (visit-tracking slice only) |
| `typeclasses/rooms.py` | `hangout_type`, `HANGOUT_TYPES`, `allow_teleport` |

## Rename map

| Source name | Contrib name |
|---|---|
| `search_object(name, typeclass="typeclasses.characters.Character")` (messaging.py, teleportation.py) | `evennia_social.social.find_character(name)` — matches by `isinstance(obj, DefaultCharacter)` instead of a game-specific typeclass dotted path, so it works against whatever Character subclass the consuming game defines |
| `caller.search(query, typeclass="typeclasses.rooms.Room")` / `db_typeclass_path__contains="typeclasses.rooms.Room"` (search.py) | `evennia_social.search.find_room()` — same `isinstance(obj, DefaultRoom)` generalization |
| `from typeclasses.rooms import Room as RoomClass; RoomClass.objects.get_by_attribute(...)` (discovery.py, `+hangouts/all`) | `ObjectDB.objects.get_by_attribute(key="hangout_type")` — typeclass-agnostic; matches any object carrying the attribute rather than one exact Room subclass |
| `from typeclasses.rooms import HANGOUT_TYPES` | `evennia_social.typeclasses.HANGOUT_TYPES` — moved into this contrib alongside `SocialRoomMixin.hangout_type`, its owner |
| `from commands.posing import format_pose_time` | `from evennia_posing.highlighting import format_pose_time` — posing is now the hard dependency that owns this function |
| `from world.utils.accessibility import uses_screenreader` | soft `try/except` import of `evennia_accessibility`, mirroring `evennia_posing`/`evennia_boards` |

## New code / behavior changes (not a straight port)

- **`CmdOoc`'s scene-log coupling.** The source's `ooc` command called
  `world.scenes.capture.capture_to_scene()` directly — a hard import into a
  Phase-3-later system. This was **not** listed in the original extraction
  scoping report's "Entanglements to sever" section (that section covered
  `record_pose()`, `msg()`, `at_post_puppet`, the Room mixins, `room_type`,
  and the `+finger` placeholders — `ooc.py` was missed). It surfaced during
  this extraction and was severed the same way: `CmdOoc` now fires
  `evennia_posing.signals.pose_recorded` directly with `pose_type="ooc"`,
  bypassing `record_pose()` so pose order/timer stay untouched (matching
  the source's documented "OOC messages do not affect pose order"
  behavior), while still giving the game's single ordered `pose_recorded`
  listener a chance to log OOC chat if it wants to. See README "The severed
  +ooc scene-log coupling".
- **Ignored-sender placeholder was leaking into posing's header/highlight
  pass — found and fixed via the standalone test suite, not by inspection.**
  The source's monolithic `Character.msg()` did ignore-filtering, pose
  headers, and highlighting as sequential blocks in *one* method, so an
  early `return` after building the ignore placeholder skipped the
  header/highlight code further down in the same function by construction.
  Splitting `msg()` across two cooperative mixins broke that: `msg_opts`
  passed with the placeholder to `super().msg()` still carried
  `"type": "pose"`/`"say"`, so `PosingCharacterMixin.msg()` (which gates its
  header/highlight logic on exactly that type) applied a pose header *and*
  name highlighting to the muted `[An ignored player posed.]` placeholder —
  a `+finger`-style regression invisible from reading the code, only
  caught by the standalone test suite (`TestCooperativeMsg`) run against a
  real Evennia bootstrap. Fixed in `SocialCharacterMixin.msg()` by retagging
  the placeholder's `type` to `"system"` before handing it to
  `super().msg()`, so downstream pose-aware mixins no-op on it.
- **`+hangouts/all` now skips rooms whose `hangout_type` was cleared —
  fixing a latent bug carried over from the source.** `+hangouts/all` finds
  candidate rooms with `get_by_attribute(key="hangout_type")`. Clearing a
  hangout assigns `hangout_type = None`, which leaves the Attribute row in
  place (holding `None`) rather than deleting it, so the lookup still
  returns the room. The source then only filtered on `filter_type`, so a
  cleared room would be listed as an *empty hangout* forever. This contrib
  adds an `if not hangout: continue` guard. The same bug is still live in
  the source's `discovery.py` and is a candidate for backporting.
- **Unread-pages notice: closed an unterminated color code.** The source
  read `"|wYou have N unread pages. Use |wpage/last N|n to view."` — the
  first `|w` is never closed, so the whole sentence rendered highlighted
  and only `" to view."` came out plain, the inverse of the obvious intent
  (highlight just the command). Now `"...unread pages.|n Use |wpage/last
  N|n to view."`. Fixed in the source too.
- **`_get_all_rooms()` (fuzzy-match fallback) uses
  `DefaultRoom.objects.all_family()`.** The source filtered on its own
  typeclass path in SQL (`db_typeclass_path__contains="typeclasses.rooms.Room"`),
  which is not portable to a contrib. The naive portable rewrite —
  `ObjectDB.objects.all()` + an `isinstance` pass — would be correct but
  would table-scan every object in the game and force a typeclass
  resolution per row on each failed `@tel` lookup. `all_family()` keeps
  both properties: it expands DefaultRoom's subclass tree to typeclass
  paths and filters on them in SQL.
- **`+finger` profile display drops `lore_lean_value`/`resource_lean_value`**
  (Phase 4/9 placeholders) and the `plot_follows` field entirely, per the
  scoping report's explicit instruction — only `followed_themes` (this
  contrib's own theme-follow feature) is kept.
- **`_notify_xp_summary()` is not ported** — XP-batch summary display is a
  distinct game-side concern (per the scoping report) and was never part of
  `commands/social/`'s own responsibility in the source; it lived in
  `Character.at_post_puppet()` alongside the code this contrib *does* pull
  from that method.

## Deliberately omitted

- **`+screenreader` (`commands/social/accessibility.py` in the source).**
  This command is a thin toggle for the `screenreader_mode` account option
  that `evennia_accessibility` itself owns. It is not listed in the
  original scoping report's Phase 2A–2P feature table, so it was out of
  scope for this extraction. It conceptually belongs with
  `evennia_accessibility` (which currently ships the option and its utility
  functions but no command) rather than with either posing or social — left
  as a future addition to that contrib, not silently folded into this one.
- **`CmdSoftBan`** — a moderation command that happened to share a source
  file with `CmdTel`. Unrelated to teleportation or any Phase 2 feature;
  explicitly flagged as staying behind in the scoping report §10.
- **2D (editing framework)** — `+finger`'s bio editor uses plain `EvEditor`
  callbacks, not the source's version-tracked editing mixin, so no editing
  framework was pulled in (confirmed during the scoping pass, `finger.py`).
