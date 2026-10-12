# Adoption and upgrades

## Upgrade from 0.2.0 to 0.2.1

No model migration or fight-schema change is added. Optional partners can
now request validated support recipients and preview an atomic interception;
recovery emits its own transition event. Without an installed provider,
support and revival keep their ordinary behavior. Party 0.1 requires this
version rather than approximating combat 0.2's recovery state.

This is a contrib-native implementation of a consent-based RP combat design.
No source-project tables or Python modules are imported. Install hard
partners first, configure stat-role/content mappings, migrate, register the
cmdset, then reveal combat in a staging game for playtesting.

Chargen 0.4 adds migration 0004 (SignatureMove), preserving 0001-0003.
Combat 0.1 adds its initial Tactics table. Existing sheets, abilities,
equipment and XP are unchanged by migration. Back up a populated database,
apply migrations, compare preserved rows, then rehearse through the real
command path. Do not replace a live database with the demonstration snapshot.
The reference golden database is rebuilt from fresh synthetic content.

Fights live in three tables (migration 0002): `Fight` holds each fight's JSON
state (schema version 1) and status (open, shelved or ended, with at most one
open fight per room); `FightEntry` is its append-only journal, one row per
operation with the state before it; `FightBuild` stores each frozen build
once, which stored state and snapshots reference by digest. Back up all three
together with Character rows. Restore a complete consistent backup; never restore only a
participant's resources. Staff rollback restores combat checkpoints but
cannot undo authored prose or external XP, ignore or catalog edits. Review
its reconciliation notice before resuming. Future schema changes must migrate
retained (including shelved) fights explicitly.

Pre-release sandboxes that ran an earlier 0.1 build kept fight state on a
`rp_combat_coordinator` room Script. That state is not carried over: end
those practice fights, or reset to the golden database, and delete leftover
`rp_combat_coordinator` Scripts. A single global `rp_combat_maintenance`
Script is created on first setup.

## Upgrade from 0.1.0 to 0.1.1

No model migration is added. The in-memory fight schema advances from 1 to
2 through `evennia_rp_combat.state.upgrade` whenever a fight or rollback
checkpoint is loaded. Old stored journal snapshots and FightBuild rows are
never rewritten. Existing queued packets have no partner modifiers and
retain their original mechanics. Unknown core versions fail visibly.

Partner state lives under `partners` in individually versioned envelopes.
Removing a provider preserves its envelope and saved packet modifiers;
its modifiers are inactive while absent and status explains that fact.
Reinstalling applies only already stored inputs to existing declarations,
and samples new inputs for future declarations. Provider owners must keep
their upgrade functions pure and idempotent. See [PARTNERS.md](PARTNERS.md).

## Upgrade from 0.1.1 to 0.2.0

No model migration is added. `state.upgrade` advances fights from schema 2
to 3 on load, giving every participant 0.2's defaults: no pending recovery,
revival offers asked for rather than accepted, and no Measured Tempo
charges. Retained fights, including shelved fights and old rollback
checkpoints, load unchanged otherwise; exchanges recorded before 0.2 simply
lack the new exchange fields and resolve as before. Stored snapshots and
FightBuild rows are never rewritten. Hosts using the new conditional
Abilities register `combat_rule` in `RP_RULES_EFFECT_KINDS` before seeding
catalog entries that use it; existing `combat_bonus` entries are unchanged.
Domain Resistance now takes effect in combat for builds that already carry
it.
