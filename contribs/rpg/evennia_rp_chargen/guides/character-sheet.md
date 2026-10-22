---
key: character-sheet
title: Your character sheet
category: Your character
order: 20
summary: Choosing stats, setting pips, abilities and flaws, and when your sheet locks.
---
Your sheet holds your character's stats, their [[glossary-pip|pips]], and the abilities and flaws you've chosen. Checks read it, as [[checks]] explains. Only you and staff can see it, and it never shows the numbers behind a grade.

- `+sheet` shows your sheet.
- `+stats <stat>=<grade>` picks a stat's grade while the sheet is a draft.
- `+pips <stat>=<count>` sets `+` pips, and `+pips/weakness <stat>=<count>` sets `-` pips.
- `+abilities` lists yours. `+abilities/list` shows what's available.
- `+spend/ability <ability>` buys one, and `+upgrade <ability>` raises it a level.

## Drafting and finalizing

A new sheet starts as a **draft**. Pick a [[glossary-grade|grade]] for each stat within your game's allocation: a pool of build points, a fixed set of grades to hand out, or a free choice. A change the allocation doesn't allow is refused, with the reason.

When every stat is set, `+stats/finalize` makes the sheet playable. After that, only staff can change grades. Some games also ask staff to approve a sheet before it can be used. Otherwise it's playable straight away, and staff can look it over afterwards.

## Pips

`+` pips come from a limited budget. `-` pips, **weakness**, are free. You can add or move pips after finalizing, except while your sheet is locked (below).

:::insight[Why weakness is free]
A `-` pip doesn't buy you anything: it never earns extra `+` pips. So nobody takes a weakness to get ahead, and a stat with a weakness is a choice about who the character is.
:::

## Abilities and flaws

Abilities help with checks. Some are chosen per subject, so the same ability for performance and for stealth is two separate copies, each with its own level.

- **Equipped abilities** count against your **loadout**, which has room for only so many, and only equipped abilities apply to checks. `+abilities/equip` and `+abilities/unequip` change what's equipped.
- For a tagged ability, use `<ability>/<tag>`, for example `+spend/ability Proficiency/Performance`. The same address works for info, equip, unequip, flaws and upgrades.
- **Buying and upgrading** use your starting allowance first. A new ability is equipped straight away if your loadout has room. Once that's gone, they use XP if your game has it. Each level costs more than the last, and `+abilities/info <ability>` shows the costs.
- **Flaws** are free and always in effect, and they give nothing back. Take one with `+abilities/flaw` and drop it with `+abilities/unflaw`. Some flaws are set by staff, and only staff can remove those.

## Locking

While you're playing, your pips and loadout are **locked**, so they can't change in the middle of a scene. Your first IC pose locks them, and so does a check. `+lock` locks them straight away.

To change something mid-scene, `+unlock`. The room is told, so everyone knows you're adjusting. Your next IC pose locks them again. They also unlock on their own when your RP session ends, or after a while with no IC activity. A draft sheet never locks.

:::insight[Out in the open, not behind a gate]
Nothing stops you from adjusting mid-scene. It's just announced. Openness keeps it fair without making anyone wait for staff, and the announcement is enough for the people you're playing with.
:::

## How it connects

Checks read your sheet, as [[checks]] explains. If your game offers them, [[signature-moves]] are moves you design yourself, and they lock with your loadout.
