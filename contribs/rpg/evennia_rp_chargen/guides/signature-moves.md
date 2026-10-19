---
key: signature-moves
title: Signature moves
category: Your character
requires: RP_CHARGEN_MOVES_REVEALED
aliases: [moves, signatures]
order: 25
summary: Designing your own moves, your library, and the loadout you equip.
---
A **Signature** is a move you design yourself: an attack, a spell, a way of helping an ally or of shaking an opponent. You keep your Signatures in a library and equip the ones you want ready. They cost nothing, and staff don't approve them. If your game has combat, it uses the moves you've equipped.

- `+moves` shows your library and which moves are equipped.
- `+moves/create <name>=<fields>` designs a new move.
- `+moves/edit <key>=<fields>` changes one.
- `+moves/equip <key>` and `+moves/unequip <key>` change what's equipped.
- `+moves/archive <key>` retires a move.

## Designing a move

A move's fields are written as JSON, for example `+moves/create Ready Guard={"power":1,"accuracy":1,"effects":["resist_stance"]}`. `help +moves` lists the fields.

- **Action:** attack, spell, assist or dispirit. Attack is the default.
- **Power and Accuracy:** an attack or spell shares a fixed budget between them, so a harder hit is a less certain one. Assist and Dispirit don't use them.
- **Effects:** up to two different effects, such as a stance or a longer reach. Each effect suits only some actions.
- **Wording, element and domain** describe the move and what it draws on. Your game may limit elements and domains to its own list.

A move that breaks a rule is refused, with the reason. The move's key is its name in lower case, with hyphens for spaces: `Ready Guard` becomes `ready-guard`.

## Your library and loadout

Your library holds many moves, and only so many can be equipped at once. Editing a move gives it a new revision, so a fight that started with the old one isn't changed under anyone. Archiving takes a move out of your library for good, and its key can't be used again.

## When moves lock

Equipped moves lock with the rest of your loadout while you're playing, as [[character-sheet]] explains, and while you're in a fight if your game has combat. You can still design, edit and archive moves you haven't equipped.

:::insight[Free to design, fixed in play]
Moves cost nothing, so you can try ideas without spending anything you'd miss. Only the moves you've equipped are locked, and only while you're playing, so the people you're playing with know what they're facing.
:::
