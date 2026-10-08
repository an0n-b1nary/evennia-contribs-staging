# Changelog — evennia-rp-chargen

All notable changes to `evennia-rp-chargen` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Documentation

- Updated the preview version and documented the pilot origin, dependency
  boundaries and pose/session lock lifecycle.

## [0.2.0] - 2026-10-07

- Added the optional `EvenniaXPLedger` adapter (`[xp]` extra): allowance
  pays first, then earned XP, with full database rollback on failure.
- Upgrade writes reject stale levels and roll back their debits.
- Added live `budget_cost_overrides` per template tag (migration `0003`),
  resolved by equip, auto-equip, loadout totals and `+abilities/info`.
  Rebalances keep existing loadouts equipped, flag over-budget sheets and
  block new equips until the budget permits them. Flaws cost zero.

## [0.1.0] - 2026-10-02

### Added

- **Sheets.**
  - `CharacterBuild` tracks the life cycle: draft, finalized, and approved
    when approval is required.
  - `StatHandler` stores rung keys and pip counts in one Attribute, never
    scores.
- **Allocation.** `FreeAllocation`, `PointBuyAllocation` and
  `ArrayAllocation`, chosen by `RP_CHARGEN_ALLOCATION`.
  - Changes that break the allocation are refused.
  - Finalizing waits until nothing is left to do.
- **Pip policy.** An edge budget and per-stat caps; weakness is free, capped,
  and never buys edge.
- **Services.**
  - Every sheet change goes through `services`, which applies policy and
    raises a player-readable `ChargenError`.
  - Staff can approve, reopen, and set ratings directly.
- **Build locks.**
  - Triggers: pose (`note_ic_action`), resolved checks, and manual
    `+lock`/`+unlock`.
  - Release on RP session end (with evennia-rptracker installed) or after an
    idle TTL.
  - Manual changes are announced to the room.
- **`ChargenSubject` and `subject_adapter`** expose playable sheets to
  evennia-rp-rules checks.
- **Commands:** `+sheet`, `+stats`, `+pips`, `+lock`, `+unlock`, and staff
  `+chargen`.
- **System checks** E001 (allocation) and E002 (pip settings).
- **Ability catalog.**
  - `AbilityDefinition` stores abilities and flaws with their effects as
    data. A template (`tag_kind`) is acquired once per tag.
  - `CharacterAbility` holds a character's copies, each with a level and
    whether it's equipped.
  - `AbilityTransaction` is the audit trail of every acquisition, upgrade,
    grant, revoke and refund.
- **Tag vocabulary.** `TagDefinition` and `DBVocabulary`: the ruleset's tags,
  overlaid by rows that staff add, rename or archive.
- **Spending.**
  - `acquire` and `upgrade` pay from the starting allowance first, then
    through the `RP_CHARGEN_XP_LEDGER` seam (`NullLedger` by default).
  - Everything happens in one transaction, and the allowance can't be
    overspent concurrently.
- **Loadout.** A budget (`RP_CHARGEN_LOADOUT_BUDGET`), frozen by the build
  lock; new abilities are equipped automatically when they fit.
- **Flaws.** Free and self-service, always in effect, refund nothing;
  staff-only flaws can't be shed.
- **Staff tools.** Grant (at any level), revoke with an exact refund, set a
  sheet's allowance, and add tags.
- **Checks.** `ChargenSubject` turns equipped abilities and flaws into
  modifiers.
- **Seeding.** `rp_chargen_seed` seeds tags from the ruleset and abilities
  from `RP_CHARGEN_CATALOG_SEED`, idempotently, with `--update` to refresh.
- **Commands** `+abilities`, `+spend`, `+upgrade`, plus `+chargen/grant`,
  `/revoke`, `/allowance` and `/tag`.
