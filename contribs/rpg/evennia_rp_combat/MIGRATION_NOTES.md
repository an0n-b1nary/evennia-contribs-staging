# Adoption and upgrades

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

Fights live in two tables (migration 0002): `Fight` holds each fight's JSON
state (schema version 1) and status (open, shelved or ended, with at most one
open fight per room); `FightEntry` is its append-only journal, one row per
operation with the state before it. Back up both together with Character
rows. Restore a complete consistent backup; never restore only a
participant's resources. Staff rollback restores combat checkpoints but
cannot undo authored prose or external XP, ignore or catalog edits. Review
its reconciliation notice before resuming. Future schema changes must migrate
retained (including shelved) fights explicitly.

Pre-release sandboxes that ran an earlier 0.1 build kept fight state on a
`rp_combat_coordinator` room Script. That state is not carried over: end
those practice fights, or reset to the golden database, and delete leftover
`rp_combat_coordinator` Scripts. A single global `rp_combat_maintenance`
Script is created on first setup.
