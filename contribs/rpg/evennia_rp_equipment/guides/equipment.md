---
key: equipment
title: Gear and outfits
category: Your character
requires: RP_EQUIPMENT_REVEALED
aliases: [gear, outfits]
order: 40
summary: Making and wearing gear, worn lines, requirements that commit your build, and outfits.
---
Gear is what your character wears or carries for others to see. While you wear an item, its **worn line** appears in your description, such as "a cloak of deep indigo". Gear never makes your character stronger. What it can do is ask you to commit part of your [[character-sheet|build]].

- `+gear` lists the gear you carry, and which of it you're wearing.
- `+gear/make <name>` makes a plain item. `+gear/desc`, `+gear/line` and `+gear/slot` describe it.
- `+wear <item>` and `+remove <item>` put it on and take it off. The room sees you do it.
- `+worn` shows what you're wearing, and `+worn <character>` what someone here is wearing.
- `+outfit/save <name>` saves what you're wearing as an outfit, and `+outfit <name>` changes into it.

## Making your own

Anyone can make plain gear. You can only have so many items of your own making in the world at once. Only the maker can change an item, and only until someone else has held it. After that it's **sealed**: its description, worn line and requirements stay as they are. If you've been given an item you don't like, you don't have to wear it.

**Slots** are only for the order worn lines appear in. Wear as many things in one slot as you like. Some games let an outer layer cover an inner one: a cloak can hide what's worn on the body from an ordinary look. `+worn/all` looks closely and shows covered gear too. Covered gear still counts as worn.

## Requirements

A requirement ties wearing an item to your build: `+` pips or a weakness on a stat, an equipped ability, or a flaw you hold. `+gear/require <item>=<requirement>` adds one to an item you made, and `+gear/info <item>` shows each requirement and whether you meet it.

- **To wear it,** you need to meet every requirement. The one exception is an ability you don't have at all: you can still wear the item, and you're told you're "not fully attuned" to it. That changes nothing mechanically.
- **While you wear it,** the build it needs can't change. If an item needs `+` pips on a stat, you can't move those pips away until you take it off. The refusal names the item. This holds for staff too, so your gear and your build always agree.
- **While your sheet is locked** in the middle of a scene, you can't put gear on or take it off, just as you can't change your pips.

:::insight[Gear commits, it doesn't grant]
Anyone can say their character carries a sword. Gear is for players who want that sword to mean something about who they are, so it asks for a commitment rather than giving a bonus. Because it never adds anything to a check, nobody is pushed to wear the best gear just to keep up.
:::

## Wearing and moving

Worn gear stays on you. You can't drop it or give it away while you're wearing it; take it off first. Only the person holding an item can destroy it, and only once it's off.

## Outfits

An outfit is a private, named set of everything you're wearing, covered gear included. `+outfit <name>` takes off everything else and puts the set on in one go. If anything in the set is missing, or you don't meet a requirement, or your sheet is locked, nothing changes. Saving an empty outfit gives you a way to take everything off at once. `+outfit` lists your outfits, and `+outfit/show` and `+outfit/delete` look at one or remove it.

:::insight[All or nothing]
Changing outfits checks every item first, so you never end up half-dressed because one piece was missing. And it never adjusts your build to fit the clothes.
:::

## How it connects

Gear reads your [[character-sheet]], and its requirements use the same stats, pips and abilities as [[checks]]. If your game has crafting, crafted gear is worn the same way and follows the same requirements.
