---
key: chargen-staff
title: "Staff: character sheets"
audience: staff
category: Staff
summary: Reviewing sheets, reopening, stat corrections, grants, refunds, allowance and tags.
---
## What it's for

Staff review and repair sheets while preserving what a character actually owns and paid for. See [[character-sheet]]. `+chargen` and `+sheet <character>` use `RP_CHARGEN_STAFF_LOCK`, Builder by default.

## Tasks and commands

- **Reviewing a sheet:** `+chargen` lists drafts and sheets awaiting approval; `/list [draft|finalized|approved|all]` narrows the list. `+chargen <character>` or `+sheet <character>` reads a sheet. `/approve <character>[=<note>]` approves a valid sheet, while `/reopen <character>[=<note>]` returns it to draft so the player can change rungs.
- **Correct a rating:** `+chargen/setstat <character>/<stat>=<rating>` sets the whole rating, including pips. It bypasses allocation and pip limits and reports anything it breaks. Read that report rather than treating the successful edit as approval.
- **Grant or revoke:** `+chargen/grant <character>=<ability>[/<tag>]` gives an ability or flaw free at level 1. `+chargen/level <character>=<level>` changes the last copy you granted, naming it in the reply. Another grant replaces that selection; a server reload clears it. `+chargen/revoke <character>=<ability>[/<tag>]` removes it; `+chargen/refund <character>=<ability>[/<tag>]` removes it and returns recorded payments where the relevant ledger is available. A free grant is not a purchase and does not manufacture refundable spending.
- **Allowance:** `+chargen/allowance <character>=<amount>` overrides the character's starting allowance; `=default` restores the configured allowance. It changes the budget, not the history of purchases already made.
- **Vocabulary:** `+chargen/tag <name>[=<kind>]` adds a stable tag, defaulting to domain. Check existing vocabulary first; ability templates and integrations refer to these identifiers.

## What's safe to change

Use staff commands so validation, payment records and audit attribution survive. Keep ruleset, ability and tag keys stable; change display prose or archive obsolete definitions through their supported maintenance tools instead of replacing referenced keys. Combat can hold a frozen build independently of the live sheet. Agree an announced correction with the player and clear combat queues before its unlock/relock workflow; a staff sheet edit does not silently update a fight.

## Privacy

Players can read their own sheet; staff can read others through the named command. Treat weaknesses, ability choices, spending and review notes as private character information, even if a public test or fight reveals an outcome.

## Review jobs

Chargen files no automatic Jobs ticket when a sheet is finalized. The sheet status and `+chargen/list` are its review queue. If the host also asks for an application or support ticket, decide the sheet through chargen and answer that ticket separately.
