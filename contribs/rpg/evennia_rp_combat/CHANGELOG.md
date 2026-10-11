# Changelog - evennia-rp-combat

## [Unreleased]

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
