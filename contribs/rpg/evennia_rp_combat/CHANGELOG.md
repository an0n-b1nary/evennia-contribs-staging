# Changelog - evennia-rp-combat

## [Unreleased]

## 0.3.0

### Breaking

- Dedicated action commands and persistent armed modifiers replace combined action switches. Pass replaces recovery, recovers Resist pressure without exchange rewards, and preserves modifiers. Tactics field edits, selection and deletion are separate. Cross-room fight discovery and shared explicit build corrections honor NPC puppet state.

## [0.2.6] - 2026-10-22

### Changed

- Accept Chargen 0.5 and NPCs 0.2 in optional dependency ranges. Live combat rehearsals configure NPC stats with individual `/stat` edits.

## 0.2.5 — 2026-10-20

- Add the staff-only `combat-staff` guide: tasks and command permissions, safe changes, privacy and review queues. Package it for discovery by evennia-guides.

## [0.2.4] - 2026-10-18

- Rewrote the player guide in the guide format and split it into three pages,
  all hidden while `RP_COMBAT_REVEALED` is off: `combat` (joining, turns, going
  down, stepping out, corrections), `combat-moves` (tiers, reactions, hidden
  bets, resources, stances) and `combat-storytelling` (storyteller requests,
  NPCs, ending and shelving). The pages give no exact values.

## [0.2.3] - 2026-10-12

- Add reusable idempotent encounter damage and mandatory Resist operations,
  plus nonstacking next-full-turn skips with execution-expiring reaction penalties.
- Freeze optional partner subject snapshots at enrollment/relock; resolution
  providers remain pure. Read-upgrade schema 3 fights to schema 4 without
  changing shipped migrations or replaying resources/history.

## [0.2.2] - 2026-10-11

### Added

- Explicit partner declaration/pressed-hit reservation hooks run before
  frozen modifiers and automatic execution, within the fight transaction.
  Failed explicit spends leave pure engine inputs unchanged too. The
  announced journal line names the request and its target, never raw ids,
  and still distinguishes a spend from a plain retry of the same operation.
- Typed partner transition notices are journaled and announced in the
  operation that produced them, including saved-state reconciliation.
- Attributed hostile Poison damage events on ordinary completed actions;
  recovery still grants no partner resource reward.

No model migration or core state-schema change is required.

## [0.2.1] - 2026-10-11

### Added

- Validated pure support-spread contract: incidental allies receive ordinary
  Spirit with their own repeat tracking, without copied healing or riders.
  Host ignore/room checks filter recipients inside the coordinator transaction.
- Partner declarations include the selected domain; recovery emits its own
  lifecycle event without claiming a completed exchange or granting rewards.
- Party-aware fallback messages; revival acceptance rechecks direct consent.
- Read-only public interception odds use the same detached handoff validation.
  Retained Burst redirect history prevents another handoff after Formation changes.

No model migration or core state-schema change is required.

## [0.2.0] - 2026-10-11

### Added

- Consented revival: a Heal may name one incapacitated, present ally. The
  offer waits in their incoming queue until they `+combat/accept` or
  `/decline` it; `+combat/revive accept` accepts allies' revivals at once;
  the healer may `+combat/retract` an unaccepted offer. Every path that
  doesn't resolve refunds the healer.
- One recovery action after revival (`+combat/recover`, or Auto-Act): it
  spends one action, ticks Poison and expires conditions once, and grants no
  Reserves, Spirit, Transcendence or Resist recovery. Until then the
  participant can neither act nor be targeted. Medicine's Treat on the
  reviving Heal may instead waive recovery (`;waive`), without cleansing.
- The `combat_rule` effect kind: fourteen bounded conditional rules for
  Abilities and Flaws, validated at every level and frozen into fight
  builds. Deflect, Stoneskin, Finesse and Desperate Counter apply inside the
  shared arithmetic, so previews and Auto-Resolve match resolution; RPS
  specialisations and Flaws, Calling the Shot (`;public`), Tactician,
  Measured Tempo, Explosive, Flowing Guard, Braced Support, Taunting Opener,
  Bait and Blood Price apply in the engine.

### Changed

- Domain Resistance now blocks a domain effect working against its owner:
  riders on a hit or Dispirit target (checked before Ward), Ambush for the
  defender, and Slip Inside and Read against the countered or read attacker.
  Helpful effects are never blocked. A blocked effect still spends the
  exchange's single use and its surcharge, and the result says so.
- Reaching 0 Vitality voids every incoming attack the participant hasn't
  answered, refunding the attacker; accepted reactions still resolve. A
  voided Burst opener refunds the ante; a voided later hit ends the chain as
  a stop.
- A Faded participant at 0 Vitality may rejoin, still incapacitated, so an
  ally can offer a revival. Withdrawal still needs a storyteller return.
- Reaction views carry a bet only when its attacker called it publicly.
- Fight state schema 3 (read-time upgrade from 2) adds each participant's
  pending recovery, revival preference and Measured Tempo charges.

## [0.1.1] - 2026-10-11

### Added

- Pure, validated partner contracts for frozen packet modifiers, versioned
  partner state, engine events and plain-text status/help extensions.
- Read-time state upgrades, including old journal rollback, preserving
  stored snapshots and content-addressed builds.
- Retained partner data and visible unavailable notices when a provider
  is absent; new declarations never acquire modifiers retroactively.
- Atomic interception primitive: a queued attack and the rest of its Burst
  can move to a replacement defender with a legal Resist/Overpower in the
  same operation. No interception command or Party rules ship here.
- Shared exact damage/support modifier inputs for manual results, neutral
  odds and Auto-Resolve. Party damage boosts are excluded from Burst's
  Spirit-transfer basis; paid output modifiers remain distinct.

## [0.1.0] - 2026-10-10

### Added

- Exact combat score mapping, damage/reaction/resource arithmetic and
  damage-based Resist pressure with recovery per own exchange.
- Consent-based persistent room coordinator, personal turns, queued/shared
  reactions, cancellation, immutable fight builds and announced corrections.
- Signatures/Effects, three Stances, domains, focus traits, support, Burst,
  Empower, fixed-opening-denominator assessment, Boss allowances and Fade.
- Durable Tactics; opt-in Auto-Resolve and deliberately invoked Auto-Act
  with capability-limited views and random RPS guesses.
- Attributed player storyteller controls, optional permission-checked NPC
  profiles/templates/batches, SYSTEM Scene capture and pose completion.
- Transaction checkpoints, idempotent service retries, retained operation
  history, staff whole-fight rollback, result recovery and membership signals.
- Plain-text commands, player guide, reference-game demonstrations and tests.
- Storyteller-requested returns with explicit participant acceptance or refusal,
  retained personal progress and assessment exposure for restored Vitality.
- Fights stored as `Fight` rows with an append-only `FightEntry` journal and
  content-addressed `FightBuild` rows (migration 0002); nothing is rewritten
  over a long fight and snapshots never repeat builds.
- Storyteller changes to a player character are numbered requests the player
  accepts or declines; ending a fight needs the present players' agreement.
- Fade releases the sheet and rejoin restores the fight's frozen build; one
  active fight per character; shelving and unshelving whole fights.
- Connection-based idle detection (default one hour); join announcements of
  Vitality, Turn Limit and Boss Mode; private invitations and refusals.
