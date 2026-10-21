# Changelog - evennia-rp-party

## [Unreleased]

## 0.2.4 — 2026-10-20

- Require combat 0.2.5 so the linked combat staff guide is available.
- Add the staff-only `party-staff` guide: tasks and command permissions, safe changes, privacy and review queues. Package it for discovery by evennia-guides.

## [0.2.3] - 2026-10-18

- Rewrote the player guide in the guide format and split it into three pages,
  all hidden while `RP_PARTY_REVEALED` is off: `party` (forming a party,
  Formation and Cover, support), `party-surge` (Synergy and Team Surge) and
  `party-boss-checks`. The pages give no exact values.

## [0.2.2] - 2026-10-13

- Party OOC chat honors shared communication restrictions, including when
  directing an NPC. A mute cannot be bypassed through private party chat.

## [0.2.1] - 2026-10-13

### Changed

- Boss Check status details only the viewer's own pending Checks (or every
  Check the viewing boss issued), lists other Parties' pending Checks in one
  line each and collapses finished Checks into one summary line plus the
  viewer's latest result. Full history stays in `+combat/journal`.
- Issue journal entries name each raid instance once and print the shared
  Special requirement/hint, Contest approaches and setup warnings once.
  Special Checks no longer show "requirement None"; response-pacing warnings
  wait for preview and status.
- Resolve journal entries list damage in one bounded line by character name
  and cause instead of one line per raw participant identity.
- Automatic cancellation names its cause: fight ended, boss incapacitated,
  boss withdrew or boss left the fight.

### Fixed

- Issuing a Check prunes that boss's issuance markers from earlier personal
  turns, so saved state and journal snapshots no longer grow with every
  Check. The once-per-personal-turn rule is unchanged.

## [0.2.0] - 2026-10-12

### Added

- Manual Tank, DPS, Support, Pressure, Special and optional Contest Boss
  Checks, including simultaneous independent raid Party targets, frozen
  cohorts, bounded size adjustment, membership locks and two cancellation scopes.
- Tokened consequence previews, explicit warning acknowledgment and
  permission-checked NPC control. Committed consequences require staff recovery.
- Ordinary damage/resource accounting, complete-Front-collapse failure waves,
  direct DPS attribution and a nonstacking full-turn Stagger/Burst opening.
- Frozen, once-only, transaction-bound Contest attempts without room-test
  matching, with individual failure damage and group Backlash/Stagger.
- Schema 3 read upgrades, guides/reference seams, seeded calibration and
  populated provider removal/reinstallation coverage with a pending Check.

## [0.1.1] - 2026-10-11

### Added

- Exact shared Synergy, capped by counted membership; exchange, hostile
  damage and once-per-exchange outgoing Empower earning with replay guards.
- Team Surge reserves 100 for +25% primary output against one target in one
  packet. Cancellation refunds it; execution spends it. A personal-turn
  marker survives party movement, Fade, reload and rollback.
- Surge declarations/pressed Burst hits, attributed notices, read-only
  status, schema-1 upgrade and physical uninstall/reinstall settlement.
- Configurable provisional values, real engine calibration, command and
  reference seams, and populated/optional-partner continuity checks.

Requires combat 0.2.2+. Boss Checks remain Party 0.2 work.

## [0.1.0] - 2026-10-11

### Added

- Fight-scoped optional parties, stable invitations, member renaming,
  agreement-based dissolution and transient private OOC chat.
- Front/Back/Flex, opt-in atomic Cover, Burst continuation and per-recipient
  Pinpoint resistance using combat's shared contracts.
- Frozen Party Damage Boost, independent Rally/Rattle with personal-action
  and final-use expiry, and Spirit-only Encore with repeat tracking.
- Saved-state eligibility, recovery integration, retained data when absent,
  commands, guide, reference-game integration and configurable calibration.
- Personal-clock markers prevent expired support returning after progress
  while the package is absent; Burst handoffs cannot be repeated.

Synergy is deferred to a point release; Boss Checks to Party 0.2.
