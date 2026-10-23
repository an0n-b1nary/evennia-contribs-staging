---
key: contest-staff
title: "Staff: tests and challenges"
audience: staff
category: Staff
summary: Private breakdown review, challenge corrections, voided attempts and room history.
---
## What it's for

Staff inspect disputed tests without exposing a character's private numbers or erasing an attempt. See [[tests]]. Detailed review and staff challenge management use `RP_CONTEST_STAFF_LOCK`, Builder by default. Opening a challenge uses the separate `RP_CONTEST_CAN_SET_CHALLENGE` policy; a challenge's setter can manage their own.

## Tasks and commands

- **The room, not every test in the game:** `+challenge/review [#challenge]` shows recent records in your current room, optionally limited to one challenge, with their full stored breakdown. `+challenge/history` is the public account of those outcomes. Move to the appropriate room before reviewing a report.
- **Correct a challenge:** staff or its setter can `+challenge/edit #challenge=<prompt>`, change `/difficulty #challenge=<difficulty>` or `/suggest #challenge=<stat>[/<tag>]`, mark `/once #challenge` or `/close #challenge`. Changes affect the challenge; they do not reroll earlier results. Suggested approaches guide play rather than forbidding alternatives.
- **Void an attempt:** `+challenge/void #challenge.<attempt id> # <reason>` marks a mistaken attempt void. Use the attempt ID from history, not its retry count. The attempt remains visible, but no longer blocks a once-only challenge.

## What's safe to change

Use edits, closure and voiding to preserve the record. Never rewrite a stored result, roll or ruleset snapshot to make a past test look different. Tests award no XP or resources, and voiding is not an award refund or a combat rollback.

## Privacy

Public narration gives outcomes without revealing grades. Staff review includes stored mechanical detail; keep it in staff discussion and explain a correction without publishing the sheet. Being the storyteller or challenge setter does not by itself unlock the staff breakdown.

## Review jobs

Contest files no automatic review jobs. Reports arrive through the game's support tools. Ask for the room, challenge and attempt ID; inspect the stored record, apply an appropriate correction and explain it in the ticket.
