---
key: crafting
title: Making things
category: Making & trading
requires: RP_CRAFTING_REVEALED
aliases: [workshops, craft]
principles: [breadth-not-quality, nothing-decays]
order: 30
summary: Workshops and crafts, drafting and finishing an item, what crafted things can do, hallmarks, details and senses.
---
Crafting turns your character's [[resources]] into things others can wear, read, use and see. You open **crafts** in your [[glossary-workshop|workshop]], then make items in them: a cloak, a book, a cake that fills the room with the smell of spice. Crafted things are for the story. They never change a check or make anyone stronger.

- `+workshop/catalog` lists the crafts your game offers, and `+workshop` shows yours and what the next one costs.
- `+workshop/unlock <craft>=<amount> <resource>` selects one material. Repeat per resource, then `+workshop/unlock <craft>` previews the cost and prints a token confirmation to pay and open it.
- `+craft/new <craft>/<kind>=<name>` starts a draft. The other `+craft` switches describe it.
- `+craft` previews the draft and its cost, and `+craft/finish` makes the item.
- `use <item>` uses something made to be used.

## Your workshop

Each craft, such as Weaver or Scribe, lets you make certain kinds of things from certain kinds of resource. Opening one costs resources, and money too if your game has an economy. Each craft you open costs more than the one before, and there's a limit to how many you can hold at once. `+workshop/abandon <craft>` closes one to free its place. Nothing is refunded, and opening it again later costs the full price.

Every craft you hold raises the cap on what your weekly income and gathering can bring in, so you can save up for the next one.

:::insight[Breadth, never quality]{breadth-not-quality}
Your first item in a new craft is as good as anyone's. There's no skill to grind and no waiting time, and no item is better than another. What a craft gives you is more kinds of thing you can make.
:::

## Making an item

`+craft/new` starts a draft: the craft, the kind of item and its name. Then write it: `+craft/desc` for its description, and whatever else that kind needs, such as `+craft/line` for a worn line. `+craft/resources <amount> <resource>` chooses one resource to pay with. Repeat for another key; the same key replaces its quantity, and `+craft/unresource <resource>` removes it. `+craft` shows what it still needs. The craft decides which kinds of resource count; you choose which ones from your stores.

Drafts are kept until you finish or `+craft/cancel` them, even across logins. Previewing costs nothing. Your game may also charge a small fee for each craft. `+craft/finish` checks everything again, takes the cost and makes the item once, so finishing twice can't make two.

## Kinds of item

What a craft can make is set by your game. The usual kinds are:

- **Wearables:** gear with a worn line, if your game has gear. A wearable can carry the same requirements as other gear, and an optional **aura** line that shows with it.
- **Readables:** books, notes and letters. See [[crafting-letters]].
- **Consumables:** one to three lines of prose that play out in the room when you `use` it, after which it's gone.
- **Broadcasts:** like a consumable, but heard in the neighbouring rooms too. Players who'd rather not see effects from other rooms can mute them.

Your game may also open fixtures and things you use again and again ([[crafting-fixtures]]), companions ([[companions]]), and items that combine kinds, such as a locket with a note inside.

:::insight[For the story, not the sheet]
Using a crafted thing shows prose, labelled with who's using it. It never rolls dice, heals, harms or grants anything, so making things is open to everyone without changing how anyone plays.
:::

A room only shows so many effects in a short time, and the limit holds however many items are used. If an effect can't play yet, the item isn't used up.

:::insight[Made to last]{nothing-decays}
Crafted things don't wear out, break or need repairing. Only a consumable is used up, because that's what it's for, and an item you made stays yours to keep, give or sell however long you're away.
:::

## Hallmarks

Every crafted item shows a **Craft hallmark (OOC)** line, such as "Made by Morgan (Weaver)". It comes from the record the game kept when the item was made, so nobody can edit or fake it, and it stays the same when the item changes hands. See [[glossary-hallmark]].

## Details and senses

An item can have named details and its own smell, sound and feel, added to the draft with `+craft/detail <name>=<text>` and `+craft/sense <smell|sound|touch>=<text>`. Each one adds a little to the cost. Whoever carries the item, or anyone in a room where it's lying, can look closer with `look <item>=<detail>`, `smell <item>`, `listen <item>` or `touch <item>`. Only the person looking sees the result, and the room isn't told.

## Wearables with variants

A wearable can have a few named **states**, such as a cloak with its hood up or down: `+craft/state <name>=<worn line>`. Whoever has it switches with `+adjust <item>=<state>`, even long after it was made. Only the wearer sees the change confirmed. Like other gear changes, it waits while your sheet is locked during a scene.

## Selling and giving

Crafted items are ordinary things to give, trade or sell, if your game has trading. The maker's hallmark goes with them. Some crafts can also offer services on things that already exist; see [[crafting-modifiers]].
