---
key: crafting-fixtures
title: Fixtures and things to use
category: Making & trading
requires: [RP_CRAFTING_REVEALED, RP_CRAFTING_WAVE_TWO_REVEALED]
aliases: [fixtures, furnishing]
order: 31
summary: Crafted fixtures that add to a room's description and senses, decorating for a scene, and items you use again and again.
---
Some crafted things change a place. A **fixture** is installed in a room, and adds a line to its description, a smell, a sound or something that happens now and then. Others are made to be played or used again and again, such as a flute with several tunes.

- `+fixture/install <item>` installs a fixture you're carrying in the room you're in.
- `+fixture` lists the room's fixtures and any temporary decorations.
- `+fixture/decorate <item>` shows a fixture in the room for a while without installing it.
- `+smell` and `+listen` with no target take in the room: its own prose, then each fixture's lines.
- `use <item>=<mode>` plays one of an item's modes.

## Installing

You can install a fixture where you're allowed to: a room you own, or one whose owner has given you permission. Each room holds a limited number. An installed fixture can't be picked up, given away or destroyed. Only the room's owner or staff can `+fixture/uninstall` it, and it goes back to the owner, even when someone else installed it. In a public room, it goes to the staff member who removes it. If the property changes hands, its fixtures stay with it.

Every line a fixture adds is labelled with who made it, and never replaces what the room's owner wrote.

:::insight[Furnishing pays you back]
A fixture installed in a place you own raises the cap on your weekly income while it stays installed. Uninstalling it removes the raise, and installing it again restores it. Making your home your own is worth something in play, not just in description.
:::

## Decorating for a scene

`+fixture/decorate` puts a fixture's lines up for a while without installing it, and its decoration ends when the scene there closes or its time runs out. You can decorate where you could set the room's mood: a room you own, a public scene you're taking part in, or a private scene you started. Decorating doesn't let you install or remove anything, and earns no cap raise. A fixture can only decorate one place at a time, and can't be installed while it's up. The person who put it up, the owner or staff can take it down with `+fixture/clear <number>`.

## Things that happen on their own

A fixture can have an ambient line that plays now and then. Ambient lines only play while someone is there, pause during a fight, and follow anyone's choice to mute effects.

## Things to use again

A reusable item has one or more named **modes**, each with a few possible readings. `use <item>=<mode>` plays one at random. Each item can only be used so often, and a room only shows so many effects at once. A fixture can be usable too, by anyone visiting the room. Using it doesn't let them move or change it.

Like everything crafted, these are for the story: a fixture or a tune never changes a check, grants lore or takes a turn in a scene.
