---
key: lore-staff
title: "Staff: lore"
audience: staff
category: Staff
summary: Publication review, affirmation, sealed truths, flags, major tags and staff tomes.
---
## What it's for

Staff review what enters the compendium and distinguish a character's account from what players can rely on out of character. See [[lore]] for reading and sharing. These staff tools, including `+tome`, use `LORE_STAFF_LOCK`, Builder by default.

## Tasks and commands

- **The queue:** `+lore/queue` lists submissions awaiting publication and published entries awaiting affirmation. Read each with `+lore/read <entry>`. When the game requires approval, `+lore/approve <entry>` publishes a submission; `+lore/reject <entry>=<reason>` rejects it.
- **Affirmation is separate from publication:** `+lore/affirm <entry>` marks the entry as canon as described, including its OOC notes. Affirming a rumor says it really circulates, not that its IC claim is true. `+lore/decline <entry>=<note>` declines affirmation; the author and staff see the note. Later edits display as edited since affirmation until staff review again.
- **Sealed truths:** `+lore/seal <entry>[=<text>]` sets staff-only OOC notes. Accuracy must stay open while notes are sealed. `+lore/unseal <entry>=<accuracy>` publishes those notes and settles accuracy, notifying characters who hold the entry. Treat this as a publication decision.
- **Tags and flags:** `+lore/tag/major <entry>=<tag>` makes a theme major. A player's `+lore/flag` stores a review reason; staff see it when reading the entry and can filter flagged entries in the admin. After review, `+lore/unflag <entry>` clears it. A flag alone does not reject or unpublish the entry.
- **Staff tomes:** `+tome/new <name>`, `/desc = <description>` and repeated `/page [title] = <text>` build a fixed book. `/cite [page] = #<entry>` attaches published lore to a page; inspect with `+tome`, then `/publish` or `/cancel`. A tome needs no crafting Workshop. Reading a cited page can teach its lore: check restricted citations before handing the book out.

## What's safe to change

Use the lore commands for IC prose, OOC truth, kinds, accuracy and tags so revisions and affirmation state stay meaningful. `+lore/history` and `/diff` explain changes. Never rewrite history or acquisition records by hand. Staff tomes are fixed publications; proofread their pages and citations before publishing.

## Privacy

IC content may be wrong; OOC notes must not be. Sealed notes stay staff-only until unsealed. Restricted lore and acquisition records reveal what individual characters know. Keep those distinctions when answering a guide question or quoting an entry outside its audience.

## Review jobs

`LORE_STAFF_REVIEW_HOOK` can forward affirmation requests and reminders about sealed lore on player-concluded plots to a staff-review reporter, including Jobs. Later edits show as edited since affirmation; they do not automatically file another request. Without the hook, affirmation requests remain in `+lore/queue`. The queue is not a list of every flagged entry; inspect flags separately. Decide on the lore entry itself, then answer any related ticket.
