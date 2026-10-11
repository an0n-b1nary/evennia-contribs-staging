# Changelog - evennia-rp-combat

## [Unreleased]

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
