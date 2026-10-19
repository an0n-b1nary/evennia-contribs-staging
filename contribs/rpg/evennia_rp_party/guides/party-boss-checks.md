---
key: party-boss-checks
title: Boss Checks
category: Playing together
requires: RP_PARTY_REVEALED
aliases: [boss-checks]
order: 22
summary: Dramatic challenges a boss offers a party, the kinds of Check, and what success opens up.
---
A **Boss Check** is a challenge a boss's player offers one or more [[party|parties]] in a fight: hold the line, deal enough damage, keep each other going. It's an optional storytelling beat with no deadline. Each party has its own Check, its own progress and its own outcome, and a Check never targets a whole side.

- `+bosscheck` shows the Checks you're part of.
- `+bosscheck <parties>=<type>` offers a Check, as a boss.
- `+bosscheck/preview <id>` shows its progress and what passing or failing would mean.
- `+bosscheck/roll <id>=<stat>` answers a Contest Check.
- `+bosscheck/withdraw <id>` takes you out of one.

## Offering a Check

Only a boss can offer a Check, and offering one costs no action. Choose a type, and optionally easy, balanced or hard. Pick a challenge the party can meet, and explain what's at stake.

- **Tank:** the Front takes hits it must Resist. Every Front member has to survive.
- **DPS:** the party's direct damage, Bursts and counters included.
- **Support:** how far the party's boosts rise.
- **Pressure:** how low the boss's Spirit falls.
- **Special:** a requirement the boss writes, with a hint, read generously.
- **Contest:** each member gets one free roll of an allowed stat, from the sheet they joined with. A boss can approve another approach before someone rolls, never after.

The boss resolves a Check by previewing it and then committing the result, with a public explanation. Nothing resolves on its own.

## During a Check

The party's members can't change while its Check is pending, but Formation can. A Tank Check is a chance to reorganise the Front and spread the hits. `+bosscheck/withdraw` takes only you out: you can't rejoin that Check or be replaced. `+bosscheck/cancel` cancels your party's Check entirely. Neither does any harm.

:::insight[A challenge, not a trap]
A Boss Check asks the boss to pick something the party can meet and to say what it means. Its result is previewed before it's committed, and every Check is explained in public.
:::

## Passing and failing

A party that passes staggers the boss: its reactions weaken, and it loses its next whole personal turn, which is the moment for a Burst. Passing a Tank or Contest Check also deals the boss some backlash. Several parties passing don't stack the stagger, but each keeps its own backlash.

Failing usually damages every member of the party. A Tank Check does that only if the entire Front falls, and a Contest Check damages only the members whose rolls failed. The preview says which applies before anything is committed.
