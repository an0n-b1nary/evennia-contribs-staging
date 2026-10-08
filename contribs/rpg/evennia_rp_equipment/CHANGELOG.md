# Changelog — evennia-rp-equipment

All notable changes to `evennia-rp-equipment` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
