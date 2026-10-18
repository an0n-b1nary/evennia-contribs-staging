# Changelog — evennia-rp-equipment

All notable changes to `evennia-rp-equipment` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.2] - 2026-10-18

### Added

- `RP_EQUIPMENT_REVEALED`, an `evennia-links` runtime setting (default `True`).
  While it's `False`, players don't see `+gear`, `+wear`, `+remove`, `+worn` or
  `+outfit`; staff (`RP_EQUIPMENT_STAFF_LOCK`) keep them. Worn gear, its
  descriptions and the build-change guard are unaffected. `evennia-links` is
  now a direct dependency (chargen already required it).
- Guide pages for `evennia-guides`: a player page, `equipment`, hidden while
  `RP_EQUIPMENT_REVEALED` is off, and a staff page, `equipment-staff`.

### Fixed

- Invalid, ambiguous or combined `+outfit` switches leave worn gear and saved
  sets unchanged instead of accidentally applying or modifying an outfit.

## [0.2.1] - 2026-10-17

- Add a keyed item-display provider API for descriptions and worn lines. Remove Equipment's imports of Crafting; optional providers preserve ordinary gear behavior and fail independently.


## [0.2.0] - 2026-10-15

### Added

- Private named outfits for plain and crafted gear: save everything worn,
  inspect saved references, replace or delete a set, and change in one command.
  Changes validate every item before writing and roll back together on failure.
  Missing items and build locks refuse the whole change; wear requirements,
  unattuned notices and build-change guards keep their existing behavior.
- Optional host-configured slot covering hides inner worn lines from ordinary
  looks and `+worn`. `+worn/all` shows covered gear on close inspection. Covered
  items remain worn for requirements, build guards, movement and audits.
- Reference-game cloak/body layering, saved demonstration outfits, mixed
  plain/crafted gear seams and command wiring. No models or migrations added.

## [0.1.5] - 2026-10-15

### Added

- Render optional lore recognition through the item's viewer-sensitive hook in
  detailed inspection, without exposing gated text in names or worn rosters.

## [0.1.4] - 2026-10-15

### Fixed

- Label verified craft hallmarks as OOC in equipment inspection, matching the
  crafted item's appearance and keeping them distinct from IC maker's marks.

## [0.1.3] - 2026-10-14

### Added

- Display optional crafting layers on plain gear and worn lines without
  changing sealed prose or requirements. Equipment remains independent
  when Crafting is absent.

### Changed

- Accept chargen 0.4 while retaining compatibility with chargen 0.3.

## [0.1.2] - 2026-10-09

### Added

- `+gear/info` displays an optional item's `get_display_provenance(looker)`
  line, allowing independently installed crafting packages to show verified
  hallmarks without importing them into equipment.

## [0.1.1] - 2026-10-09

### Fixed

- An item now seals before later `at_post_move` hooks run, so a failing host
  hook (or an exchange's post-commit hook chain) can't leave an item that
  changed hands editable by its maker.

## [0.1.0] - 2026-10-08

### Added

- Plain items anyone can make (`+gear/make`), with a description, a worn line,
  a flavour slot and a per-character cap on items in the world.
- Requirements on the wearer's evennia-rp-chargen build: `+` pips or weakness
  on a stat, an equipped ability, a held flaw. They're stored by key and
  checked when set. An unowned ability only marks the item "not fully
  attuned".
- A receiver on chargen's `build_change_requested` that refuses any build
  change breaking a met requirement of worn gear, staff changes included.
- Wearing and removing freeze whenever `locks.frozen()` does. Worn items
  refuse `get`, `drop` and `give`.
- Only the maker edits an item, until another character has held it.
- `EquipmentCharacterMixin` and `display` helpers: worn lines in the
  description, in slot order, and worn items out of "You see".
- `audit.problems()`, `+gear/audit` and `evennia rp_equipment_audit` for worn
  gear whose requirements no longer resolve.
- Commands: `+gear`, `+wear`, `+remove`, `+worn`.
