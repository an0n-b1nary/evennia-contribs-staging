---
key: economy-staff
title: "Staff: the economy"
audience: staff
category: Staff
summary: The weekly run and stipends, adjusting purses, audits and review flags, shops, stalls, freezing and revealing.
---
Economy staff keep the books straight: they see what's been minted and spent, correct a purse when something went wrong, look into flagged exchanges, and open or close storefronts. Players' side of it is on [[economy]]. Every staff command here needs `RP_ECONOMY_STAFF_LOCK`, Builder by default.

## Tasks and commands

- **Checking the totals:** `+economy` shows money held, minted and spent, the figures other systems contribute (such as resources held), and each account's balances and income across all its characters.
- **The weekly run:** income is paid automatically once per period, including to offline characters. A character whose payment fails is retried on its own. `+economy/run dry` previews a run, and `+economy/run` pays one by hand. A period is never paid twice.
- **Stipends:** `+economy/stipends` makes sure every eligible character has had its starting stipend, and, after a reveal, its reveal stipend. It's safe to run again; it never pays twice.
- **Adjusting a purse:** `+economy/credit <character>=<amount> # <note>` and `+economy/debit <character>=<amount> # <note>` correct a balance. Always give a note: it goes in the journal. Credits ignore the income cap.
- **Reading the record:** `+economy/audit [character]` lists recent journal entries, overall or for one character.
- **Review flags:** `+economy/flags` lists what's waiting for a look: something sent to a player that soon came back to another character on the sender's account, an item dropped by one character and picked up by another on the same account, stalls that have gone quiet, and upkeep shortfalls. `+economy/reviewed <number>` marks one done. If the game sets `RP_ECONOMY_FLAG_REVIEW_HOOK`, for example to jobs, each flag also files a review job.
- **Shops:** a shop opens when staff approve a property as a shop in building. `+shop/reconcile <property>` opens the storefront for a property already approved as a shop that doesn't have one yet. It's safe to repeat, and never reopens a shop its owner closed.
- **Closing a stall:** `+stall/close <number>` closes any stall from anywhere, even while the economy is frozen. Everything on it goes back to its owner without fees, and the place in the market is freed. Close stalls before deleting their owner or their market room.
- **Freezing and revealing:** `+runtime RP_ECONOMY_FROZEN=true` stops money and other assets changing hands. Reading balances, cancelling offers and giving items still work, and income periods that end while frozen are paid in order once it's lifted. `RP_ECONOMY_REVEALED=false` hides the economy's commands and its player page. Income still builds up while it's hidden, and revealing a game that ran hidden pays the reveal stipend once.

## What's safe to change

- **Runtime settings:** income, the cap and its taper, offer limits, stall numbers and fees are runtime settings. Changing them affects what happens next, never what's already been paid.
- **The journal:** every change of money is a journal row, and minted minus spent always equals what's held. Don't edit balances or journal rows in the admin. Use credit and debit, with a note, so the books still add up.
- **Reserved stock:** items and resources on a stall or in a shop belong to the storefront until they're sold or returned. Don't move them by hand; close the stall or unlist the item.
- **Deleting characters:** deleting a character with money writes a journal row that removes it, so the totals stay right.

## Privacy

Players see their own purse and offers. Staff see every balance, every exchange and which characters share an account. A flag is a question for staff, never an accusation: it doesn't block, confiscate or tell anyone. Look before you act, and keep what you find within staff.

## Review jobs

With the review hook set, each review flag files a staff job as well as appearing in `+economy/flags`. Settle it in the jobs queue, then mark the flag reviewed. If filing a job fails, the flag still waits in `+economy/flags`.
