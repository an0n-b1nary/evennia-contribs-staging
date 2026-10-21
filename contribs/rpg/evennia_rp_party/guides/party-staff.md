---
key: party-staff
title: "Staff: Party and Boss Checks"
audience: staff
category: Staff
summary: Manual Boss Checks, fair previews, committed consequences and fight recovery.
---
## What it's for

Staff help tables run fair Party challenges and recover mistakes already committed to combat. See [[party]], [[party-boss-checks]] and [[party-surge]]. Party has no separate staff override for membership or Boss Checks. Recovery uses combat's `RP_COMBAT_STAFF_LOCK`, Builder by default, through [[combat-staff]].

## Tasks and commands

- **Offer a Check:** an enrolled character in Boss Mode x2 or above, with clear queues, can `+bosscheck <parties>=<type>[;difficulty=<preset>]`. It addresses opposing Parties, not a whole side or unpartied players. Issuing does not require staff status. Types include Tank, DPS, Support, Pressure, Special and, with the compatible Contest partner, Contest.
- **Preview, then commit:** `+bosscheck/preview <id>` shows the current cohort, progress, consequences and resolution token. `/resolve <id>=<token>` commits that preview. Changed state invalidates the token. Read warnings about incomplete or unreachable requirements; an explicit `;ack=<public reason>` is needed where required. Accepted unresolved exchanges cannot be bypassed.
- **Judgment calls:** Special Checks need a stated requirement and hint, an explicit `;pass` or `;fail` on preview and resolve, and a public explanation on resolution. Judge the play generously. For Contest, allow an alternative approach with `/allow` before its player rolls; the bound response is free and keeps its audit record.
- **Cancel before commitment:** `/withdraw <id>` withdraws your participation, while `/cancel <id>` cancels your Party's pending Check; the issuing boss may cancel too. Neither applies failure damage. Pending Checks restrict membership; leaving cannot replace a withdrawn participant in the same Check.
- **Committed consequences:** canceling a finished Check cannot refund damage, Stagger or an executed Surge. Inspect `+combat/journal` and use staff `+combat/rollback <sequence>=<reason>` if correction is warranted. It restores the whole fight before that sequence, including Party and Check state. It does not restore a single Party independently.

## What's safe to change

Check presets belong to host configuration; issued Checks retain their preset. No scheduler automatically issues or resolves Checks. Pause or shelve to defer play rather than manually editing Synergy, reservations, cohorts or results. A canceled unexecuted Surge refunds its reservation, while an executed miss spends it; cancellation of an unrelated packet does not refund it. Keep those records together with combat's journal.

## Privacy

Party chat is transient OOC for connected roster members in the room and has no saved searchable history. Do not promise staff can recover it. Boss Check status shares progress and outcomes; Contest rolls retain private audit detail. Keep support reports separate from public claims about another character's build.

## Review jobs

Party files no automatic review jobs. Resolve table questions through the host's support tools and record any recovery checkpoint and reason there. Pending cancellation is a player tool; a request to reverse committed consequences needs combat staff review.
