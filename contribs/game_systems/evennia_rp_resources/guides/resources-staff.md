---
key: resources-staff
title: "Staff: resources"
audience: staff
category: Staff
summary: The weekly run, the catalogue, grants and spending, audits, and approving and retrying plot payouts.
---
Resource staff keep the catalogue up to date, correct holdings when something went wrong, and approve the rewards plots promise. Players' side of it is on [[resources]]. Every staff command here needs `RP_RESOURCES_STAFF_LOCK`, Builder by default.

## Tasks and commands

- **The weekly run:** gathering is paid automatically once per period, including to offline characters, and a character whose payment fails is retried on its own. `+resources/run dry` previews a run without changing anything, and `+resources/run` pays one by hand. A period is never paid twice, even after a spend.
- **The catalogue:** the game's catalogue lives in its settings. `+resources/seed` loads it, updating listed resources and never deleting any that are left out.
- **Grants and spending:** `+resources/grant <character>=<amount> <resource> # <note>` and `+resources/spend <character>=<amount> <resource> # <note>` adjust a character's stores. Grants ignore the gathering cap. Always give a note.
- **Reading the record:** `+resources/audit [character]` lists recent ledger rows, overall or for one character.
- **Plot payouts:** a plot's owners propose a per-participant reward with `+resources/payout #<plot>=<amount> <resource>`, and `+resources/payouts #<plot>` shows the budget. `+resources/payoutapprove #<plot>` approves it; only staff can. Changing a resource in the budget clears its approval, and a plot with an unapproved budget can't conclude. When the plot concludes, each active participant is paid, offline or not. If that's interrupted, `+resources/payoutretry #<plot>` finishes it, and never pays anyone twice.
- **Revealing:** `+runtime RP_RESOURCES_REVEALED=false` hides the commands, the profile line and the player page. Gathering continues while hidden and stops at the cap, and plot rewards are paid quietly and shown at the next login after the reveal. A reveal sends no announcement, so tell players through your usual channels.

## What's safe to change

- **Resource keys are permanent.** Change a resource's name or archive it; never rename or delete its key. Archived resources stay in players' stores and can still be traded or spent, but stop being gathered.
- **Runtime settings:** the weekly amount, the cap, its taper and the lean multiplier affect future runs only. Changing the period's length starts a new run of period labels, so account for the change-over.
- **Holdings and the ledger:** never edit holdings or ledger rows in the admin. Use grant and spend, with a note.
- **Frozen awards:** a concluded plot's award is fixed, along with who receives it. Correct a mistake with a grant or spend, not by editing the award.

## Privacy

Players see their own stores, their lean and last week's gains. Staff see every holding and the full ledger, so keep individual players' records within staff.

## Review jobs

Resources files no review jobs. Payout budgets wait in `+resources/payouts` for approval; check each plot's budget before it's due to conclude.
