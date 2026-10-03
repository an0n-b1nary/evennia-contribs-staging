# Changelog — evennia-rp-chargen

All notable changes to `evennia-rp-chargen` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
