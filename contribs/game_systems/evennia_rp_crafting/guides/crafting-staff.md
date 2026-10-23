---
key: crafting-staff
title: "Staff: crafting"
audience: staff
category: Staff
summary: The craft catalogue, craft records, Patterns and proposals, fixtures, and the reveal and freeze switches.
---
Crafting staff keep the catalogue of crafts, read the permanent record of anything made, curate Patterns and decide proposals for new ones. Players' side of it starts at [[crafting]]. Every staff tool here needs `RP_CRAFTING_STAFF_LOCK`, Builder by default; `+crafting` doesn't appear for anyone else.

## Tasks and commands

- **The catalogue:** the crafts and what each can make live in the game's settings. `+crafting/seed` loads them, updating listed crafts and keeping any that are left out. `+crafting/archive <craft>` stops new crafts and unlocks in one; existing items keep working, and players who hold it keep the place until they abandon it. `+crafting/restore <craft>` reopens it.
- **Craft records:** `+crafting/review` lists recent crafts, and `+crafting/review <number>` shows one record in full: the maker, their accounts at the time, every contributing craft, what was spent, and the prose. For letters, editions, journals and used items it adds the seal, the copy's sources, every journal revision and who used it where. Records never change, and they outlive the item and its maker.
- **Patterns:** `+pattern/create <key>=<name>` makes one, then `/describe`, `/rename` and `/niches` set it up. `/combo <Pattern>/<lifecycle>=<verb>` adds one verb to the lifecycle’s complete combination for crafts worked in it, and `/uncombo <Pattern>/<lifecycle>=<verb>` removes one; only open combinations your game has tested. `/grant <Pattern>=<character>` teaches one directly, and `/roster <Pattern>` shows who knows it and how they learnt it. `/archive` and `/unarchive` stop and restart new crafts, grants and teaching. See [[patterns]].
- **Stages:** a Pattern starts Recovered. With plots installed, `+pattern/thread <Pattern>=<plot>` attaches it to a whole plot (`+plot #N`), rather than a question (`+thread #N.T`). When an attached plot concludes, its active participants learn the Pattern, and the first plot attached also moves it to Spreading. `+pattern/advance <Pattern>=<reason>` moves it on early. Stages never move back, and every change is logged.
- **Proposals:** where your game offers the Pattern form, proposals arrive as ordinary request tickets. The review page shows what approving would create, or what blocks it: a key or name already taken, an unknown craft, or a proposer who has gone or isn't a playable character. Approving needs someone who is both jobs staff and crafting staff. It creates the Pattern at Spreading, known to the proposer, and opens no combinations; add tested ones afterwards with `/combo`. If anything blocks approval, the decision is rolled back so you can ask for changes.
- **Fixtures:** `+fixture/uninstall <item>` removes an installed fixture from any room. It goes to the property's owner, or to you in a public room. `+fixture/clear <number>` takes down a temporary decoration. See [[crafting-fixtures]].
- **Reveal and freeze:** `RP_CRAFTING_REVEALED` hides crafting from players while staff keep every command for testing. `RP_CRAFTING_WAVE_TWO_REVEALED`, `RP_CRAFTING_WAVE_THREE_REVEALED` and `RP_CRAFTING_PATTERNS_REVEALED` hide fixtures and reusable items, companions and services, and Patterns on their own; each hides its player pages too. `RP_CRAFTING_FROZEN` stops crafts, unlocks, abandoning and using items, while drafts, reading and existing items keep working.

## What's safe to change

- **Craft and Pattern keys are permanent.** Archive instead of deleting, and rename only the display name.
- **Combinations:** closing one stops new crafts of it, without touching items already made. Open one only after testing it.
- **Costs and caps:** craft costs, unlock prices, the number of crafts a character can hold and cap raises are settings. Changes apply to new crafts and unlocks; what was spent stays recorded.
- **Records and hallmarks:** never edit craft records, journal revisions or seal states in the admin. They're the proof of who made and wrote what.
- **Rooms with fixtures:** if your game's rooms use crafting's room mixin, deleting a room returns its fixtures to the owner. Otherwise, uninstall fixtures before deleting a room, or they're left with no location.

## Privacy

Craft records show which account made each item, and `+pattern/roster` shows how everyone learnt a Pattern; players see only their own. Keep both within staff. A signet design proves nothing out of character, so never treat a seal as evidence of who sent a letter.

## Review jobs

Crafting files no review jobs of its own. Pattern proposals arrive through the jobs queue as request forms, and spending draws on economy and resources, whose records are covered by their own staff pages.
