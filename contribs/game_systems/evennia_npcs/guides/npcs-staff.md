---
key: npcs-staff
title: "Staff: shared NPCs"
audience: staff
category: Staff
summary: Permission requests, ownership, hidden NPCs, portrayal and preserved history.
---
## What it's for

Staff help players share NPCs and recover missing ownership without losing attribution. See [[npcs]]. `NPCS_STAFF_LOCK`, Builder by default, gives staff management access; an NPC's owner can also manage that NPC and decide its permission requests.

## Tasks and commands

- **Permission to play, not ownership:** `+npc/requests` lists pending requests, across NPCs for staff and only owned NPCs for an owner. Inspect the requested blueprint and reason; `+npc/approve <request id>` grants player permission, while `/deny <request id>` declines it. These commands do not approve a character sheet or transfer ownership.
- **Manage sharing:** `+npc/permit <name>=<character>` grants portrayal access, `/revoke` removes it, and `/transfer <name>=<character>` deliberately changes the owner. `/history <name>` shows the record. Deleted or ambiguous owners need explicit staff recovery; an idle-owner rule, if configured, grants play access rather than ownership.
- **Prepare hidden NPCs:** `NPCS_REVEALED=false` hides the system from players while staff can inspect and prepare blueprints. `NPCS_COMBAT_PROFILES_REVEALED` separately gates combat profiles. `NPCS_FROZEN=true` stops writes and portrayal for everyone, including staff, while release and despawn remain available.
- **Combat profiles:** once revealed, `+npc/profile <name>/<field>=<value>` edits one field. For example, `/profile Guard/target_policy=random` or `/profile Guard/action_weights.standard=3`. Lists such as `boss_check_schedule` use comma-separated values. An empty value clears a list or mapping entry. Ownership and freeze checks still apply.
- **Archive instead of erasing:** `+npc/archive <name>` retires a blueprint and `/restore` reopens it. `/despawn <object #id>` removes an instance while keeping its record. Check unique NPCs for an existing spawn before trying to create another.
- **Directing play:** ordinary portrayal stays on the controller's character and labels NPC poses with that player. Full puppeting requires the host's explicit opt-in; it does not grant access to PC economy or building commands.

## What's safe to change

Edit through NPC commands to validate stats and ability identifiers and retain history. Preserve blueprints, permission history and spawn records; never transfer ownership by deleting an old owner row. Removing permission or moving ends virtual portrayal. Keep cleanup available when hiding or freezing the system.

## Privacy

NPC portrayal is always attributed to its responsible player. Hidden-system preparation is not anonymous play, and a plot link grants no NPC permission by itself. Staff request access is for adjudication; do not publish request reasons or private plot details when explaining a decision.

## Review jobs

NPC requests live in `+npc/requests`, not the Jobs queue. Owners and requesters receive NPC notices; resolving a request updates that request and tells its requester. If a separate support ticket prompted the decision, answer it after changing permission through NPC commands.
