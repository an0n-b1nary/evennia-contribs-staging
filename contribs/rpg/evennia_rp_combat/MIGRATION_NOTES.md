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

Fight state is stored on a persistent room Script with schema version 1.
Keep Script Attributes and journal together in backups. Restore a complete
consistent backup; never restore only a participant's resources. Staff
rollback restores combat checkpoints but cannot undo authored prose or
external XP, ignore or catalog edits. Review its reconciliation notice before
resuming. Future schema changes must migrate retained fights explicitly.
