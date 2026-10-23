---
key: crafting-modifiers
title: Changing finished things
category: Making & trading
requires: [RP_CRAFTING_REVEALED, RP_CRAFTING_WAVE_THREE_REVEALED]
aliases: [modifiers, modify]
order: 34
summary: Crafters' services that add a dye, mark, engraving or aura to an item or a character, by agreement, without erasing what was there.
---
Some crafts offer services on things that already exist: dyeing a cloak, engraving a ring, putting a mark on a character, or adding an aura. Each adds a **layer**: a line shown after the original description, labelled with who made it. The original text never changes.

- `+modify/new <customer>/<target>=<craft>/<service>` starts your service draft.
- `+modify/line <prose>` sets the line to add.
- `+modify/resources <quantity> <resource key>` selects one material; repeat for other keys. Repeating a key replaces its quantity; `/unresource <key>` removes it.
- `+modify/price <amount>` sets the commission (zero by default).
- `+modify/offer` sends the completed draft for the customer's agreement.
- `+modify/cancel` alone discards your draft.
- `+modify/accept <number>` accepts one, and `+modify/cancel <number>` calls it off.
- `+modify/layers <target>` shows an item's layers and their history.
- `+modify/hide <layer>` and `+modify/show <layer>` hide or show a layer on something of yours.
- `+modify` previews your draft and lists recent services.

## Agreeing a service

Drafts survive reconnects and reserve or spend nothing. A failed `/offer` leaves your draft editable; a successful one clears it. Starting a new draft replaces your previous draft.

The crafter makes an offer naming the exact item, the line to add, the materials they'll use, and the price. The crafter supplies the materials. Nothing is set aside while the offer waits, and if the item or terms change, the crafter has to make a new offer. Accepting checks everything again, then pays the crafter and adds the layer together, or does nothing at all. You can offer a service on your own things too; you still accept it, at no price.

The usual trading rules apply: you both need to be in the same room, offers lapse, and you can't do business with another character of your own.

## Replacing and undoing

An item has at most one dye, one engraving and one aura at a time; marks can stack. To change one, use `+modify/replace <layer number>` before offering; `/replace` alone clears that choice. Some crafts can also undo a layer, with the owner's agreement. Start `+modify/undo <customer>/<target>=<craft>`, select `/replace <layer number>`, set resources and price, then `/offer`. Undo drafts have no `/line`. Either way, the old layer and who made it stay in the history.

:::insight[Added, never overwritten]
A service adds to what the maker wrote instead of rewriting it. The original description and the hallmark always stay, and every change keeps its history, so a much-altered heirloom still shows how it came to be.
:::

Hiding a layer is free and out of character: it only changes what others see. Undoing is an in-character service.
