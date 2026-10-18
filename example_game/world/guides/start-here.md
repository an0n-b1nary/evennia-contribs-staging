---
key: start-here
title: Start here
category: Getting started
summary: What this sandbox is, and where to look first.
aliases: [sandbox]
order: 1
---
This is a sandbox game that installs every contrib in the repository, so each one can be tried next to the others. Nothing here is a finished game: the rooms, characters and values are examples.

:::insight[One game, every contrib]{penalize-dont-forbid}
Contribs are tested on their own, but most problems show up only when they meet. The sandbox is where they meet.
:::

## Where to look

- **The map** shows every room, its terrain and what's happening there.
- **Scenes** and **Happening Now** list the scenes being played.
- **Lore**, **Plots** and the **Calendar** hold the world's memory and what's coming.
- [[trading]] covers money in this sandbox.

## In the game

New characters arrive in the **Arrival Hall**. Every room off it is a workshop for one set of commands, with a plaque to read. Each is one step from the hall, and `back` returns you to it.

- **Posing Studio:** posing and the pose order.
- **Scene Room:** recording scenes, and activity tracking.
- **Social Commons:** finding people and getting to them.
- **Story Office:** plots and the calendar.
- **Lore Archive:** discovering and sharing lore.
- **Help Desk:** boards, requests and bug reports, and XP.
- **Proving Grounds:** character sheets, tests, gear, and trading.
- **Drafting Room:** digging your own rooms on a scratch map.

The in-character world is through `grid`, the hall's one exit that isn't a workshop. `+ooc` brings you back to the hall from anywhere. `+sandbox` explains the rest, and `+sandbox/builder on` gives you Builder, so you can see the staff side of every system and the staff guide pages. `+sandbox/builder off` drops it again.

## Visiting as a guest

`connect guest` at the login screen gives you a disposable character in the **Guest Lounge**, with the **Guest Practice Room** next door. You can talk to other guests and welcoming players with `guest <message>`, and page staff. In the practice room, build a trial sheet with `+stats`, `+stats/finalize` it and try `+test`. `+stats/reset` starts again. Nothing a guest does earns rewards, and the character and its sheet are deleted when you disconnect. A request you sent staff still reaches them. To stay, apply with `+apply`, as [[joining]] explains.

## What do you want to do?

Each system has its own page. Pages for systems this game hasn't opened yet show as plain text.

- **Join:** [[joining]] covers applying for an account, referral codes and what staff can see.
- **Make a character:** [[character-sheet]], [[checks]] and [[tests]]. Design [[signature-moves]], and dress them with [[equipment|gear and outfits]].
- **Roleplay:** [[posing]], [[scenes]], [[social]] and [[npcs]].
- **Grow:** [[rp-sessions]] and [[xp]].
- **Follow the story:** [[plots]], [[lore]] and [[calendar]].
- **Find your way around:** [[map]] and [[regions]]. For a place of your own, see [[building]]. To add to the public world, see [[building-frontier]].
- **Make and trade:** [[trading]].
- **Fight, or play as a team:** [[combat]], with [[combat-moves]] for the choices in an exchange and [[combat-storytelling]] for running a fight. Team up with a [[party]], build toward a [[party-surge]], and take on [[party-boss-checks]].
- **Talk to the community or ask staff:** [[boards]] and [[requests]].
- **Change how the game reads to you:** [[accessibility]].

[[numbers]] explains why these pages describe values in broad strokes.

## Words you'll see

The [[glossary-coin|coin]] is this sandbox's currency. The [glossary](/guide/glossary/) has the rest.

## How these pages work

Each page here is a Markdown file in `world/guides/`. Some pages come from the contribs themselves; a page in this folder with the same key replaces a contrib's page.
