---
key: combat-staff
title: "Staff: combat and recovery"
audience: staff
category: Staff
summary: Storytelling consent, deliberate automation, whole-fight rollback and audit limits.
---
## What it's for

Staff support a consenting table and recover a fight when an accepted mechanical result needs correction. Players' tools are on [[combat]] and [[combat-storytelling]]. Staff rollback uses `RP_COMBAT_STAFF_LOCK`, Builder by default; ordinary storytelling is open to everyone.

Combat must be revealed for its commands, including staff recovery, to work. Freezing blocks new progress while inspection and safe cancellation remain available. The staff guide itself stays readable before reveal.

## Tasks and commands

- **Support the table:** anyone can `+combatstory/pause [reason]`. Changes to another PC's Vitality, Spirit, conditions, cap or return are requests they accept or decline. Ending waits for the active players' agreement. Staff status does not enroll unwilling PCs or grant control of someone else's NPC.
- **Automation:** `+combat/auto on|off` controls the character's incoming reactions; `+combat/act` deliberately invokes one outgoing exchange. A tactics preset alone enables neither. `+combatstory/auto <NPC>=on|off` and `/act <NPCs>` work only for NPCs the caller may direct. Neither creates scheduled actions, RP poses or RP credit.
- **Read before repairing:** `+combat/journal` lists sequence summaries, including superseded operations. `+combat/result <exchange>` recovers committed public outcomes after reconnect without applying them again. An unaccepted packet can be canceled; accepted or resolved results need staff recovery.
- **Restore the whole fight:** in its room, `+combat/rollback <sequence>=<reason>` restores the checkpoint immediately before that retained, unsuperseded sequence. It rewinds the entire fight, including partner state, not one participant or hit. The reason is public, later operations remain recorded as superseded, and pending tokens change. Players must inspect their new queues before acting.
- **Reconcile:** rollback does not rewind poses, XP, external ignore changes or edits to the live sheet. If builds differ or a character is missing, the fight pauses for reconciliation. Repair the mismatch and have staff `+combatstory/resume`; a normal player cannot resume that reconciliation pause.

## What's safe to change

Use combat services and commands, never direct edits to fight state, frozen builds or journal rows. For a live build correction, clear queues, use the announced unlock/relock workflow and check the new build. Shelving preserves a fight for later; it is not erasure. Explain the checkpoint's scope to the whole table before a rollback.

## Privacy

Public sequence summaries and results omit pending private bets and draws. A staff role does not turn another player's reaction queue or tactics into public information. Preserve the distinction when handling a report, and do not treat combat audit data as permission to publish a private scene.

## Review jobs

Combat files no automatic review jobs. Use the host's support process for recovery requests, recording the fight, checkpoint and public reason. Keep the append-only journal as the mechanical record and answer the support ticket after checking the recovered state.
