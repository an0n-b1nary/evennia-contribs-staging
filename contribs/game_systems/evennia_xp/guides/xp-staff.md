---
key: xp-staff
title: "Staff: XP awards"
audience: staff
category: Staff
summary: Manual grants, the weekly batch, audit records and failed award investigation.
---
## What it's for

Staff explain XP awards and make explicit one-off grants when needed. See [[xp]] for the player view. `+xp/grant` uses `XP_STAFF_LOCK`, Builder by default; inspecting records in the Django admin requires admin access separately.

## Tasks and commands

- **Manual awards:** `+xp/grant <character>=<amount> # <reason>` awards a positive amount and records your identity and reason. An online recipient is told. Repeating it makes another award, so check the record before retrying an uncertain grant.
- **Reading the weekly run:** the batch script checks for the completed week and normally pays after the Monday UTC boundary. It runs the configured anti-gaming sweeps, then collectors, then the post-batch hooks. Check the server log for the week, award totals and errors; a collector or hook failure is logged separately from per-character write failures.
- **Checking a disputed award:** `+xp/sources` lists registered sources, and players can inspect their own `+xp/log`. Staff with admin access can inspect XPLog by character, week and source, including the multiplier and grant attribution, alongside CharacterXP totals and XPSpend records. There is no `+xp/log <character>` staff switch.
- **Repairing a failed batch:** ask the host operator to inspect its collector and batch errors before rerunning a particular week. The batch API supports source selection and a dry run. Dry run skips award writes and post-batch hooks, but still runs anti-gaming sweeps and collectors, which may write their own records. It is not a promise of no database changes.

## What's safe to change

Use grants for justified additional awards, with a reason players can understand. Keep balances, award rows, spending and refund records consistent; never alter totals or delete history in the admin. Ordinary awards are deduplicated by source type and source reference, even across weeks; rerunning a different week does not repay the same source record. Manual grants intentionally remain repeatable. Changes to collector registration or pacing belong to the host's configuration and require review before a backfill.

## Privacy

A player's award and spending history is their own. Staff audit access does not make other characters' history public. Explain the relevant award to its recipient without exposing another player's activity or private scene.

## Review jobs

XP files no automatic review jobs itself. Individual source systems may flag activity for staff and send it to Jobs through their own hooks. Resolve the source finding there, and inspect the XP log before making a compensating grant.
