---
key: combat-storytelling
title: Running a fight
category: Playing together
requires: RP_COMBAT_REVEALED
order: 12
summary: The storyteller's tools, NPCs, ending a fight, and shelving one for later.
---
Anyone can run a [[combat|fight]]. The storyteller sets the scene, plays the opposition and keeps things moving, with tools under `+combatstory`. Everything a storyteller does is announced with their name.

- `+combat/setup [reason]` starts a fight in the room.
- `+combatstory/pause` and `+combatstory/resume` pause and resume it. Anyone can pause at any time.
- `+combatstory/vitality <name>=<value>` and `+combatstory/condition <name>=<condition>` tell the story's effects on a character.
- `+combatstory/end` proposes ending the fight.
- `+combatstory/shelve` sets it aside for another day.

## Changing a character

A storyteller can't change another player's character directly. Damage, healing, Spirit, conditions, a lower Turn Limit or a return to the fight arrive as a numbered request in that player's `+combat`. They answer with `+combat/accept <n>` or `+combat/decline <n>`. Changes to NPCs the storyteller controls apply at once.

:::insight[The storyteller asks, the player decides]
Running a fight gives you the opposition, not anyone else's character. Every change to a player's character goes through that player, so anyone can run a fight without anyone handing over control.
:::

`+combatstory/imbalance <description>` puts a note at the top of everyone's `+combat`, such as a mismatch between the sides that the table agreed to. A character who withdrew, or one the table agrees to bring back after a mistake, returns through `+combatstory/requestreturn <name>=<Vitality>`, which they accept. Returning keeps their turns and resources, and the Vitality they had lost still counts.

## NPCs

`+combatstory/enrollnpc <name>=<side>` brings in an NPC you're allowed to direct, and `+combatstory/template <blueprint>=<side>` brings in one from a template. `+combatstory/act <names>` takes one action for each NPC you name, and `+combatstory/auto <name>=on` lets an NPC react on its own. To act as an NPC yourself, add `/npc` to a `+combat` command. Your own character stays separate. Nothing here can enrol another player's character.

## Ending and shelving

A fight ends when every player still in it agrees: `+combatstory/end` proposes it, and one decline withdraws the proposal. The fight's assessment then suggests outcomes for the RP. It imposes none.

To stop for a few days, `+combatstory/shelve` sets the fight aside. Everyone steps out with their place kept, sheets unlock, and the room is free. `+combatstory/shelved` lists shelved fights you were in, or that were set aside in this room. `+combatstory/unshelve <n>` brings one back here, everyone rejoins with `+combat/join`, and anyone can `+combatstory/resume`.
