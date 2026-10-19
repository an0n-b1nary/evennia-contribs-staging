---
key: patterns
title: Patterns
category: Making & trading
requires: [RP_CRAFTING_REVEALED, RP_CRAFTING_PATTERNS_REVEALED]
principles: [breadth-not-quality]
order: 35
summary: Crafting knowledge your character learns, uses in a hallmark, and teaches others in a scene.
---
A [[glossary-pattern|Pattern]] is something a crafter knows: a recipe, a weaving method, a way of binding books. It belongs to your character, not to an item. Working an item in a Pattern you know names it in the item's hallmark, such as "Worked in Verse Embroidery by Kael (Weaver, Scribe)", and some Patterns open kinds of item that can't be made otherwise.

- `+pattern` lists the Patterns you know and any offers to teach you.
- `+pattern/all` lists the Patterns known in the game, and `+pattern/info <Pattern>` describes one.
- `+craft/pattern <Pattern>` works your draft in a Pattern you know.
- `+pattern/teach <character>=<Pattern>` offers to teach one.

## Using a Pattern

Add `+craft/pattern` to a draft for a craft the Pattern belongs to, and `/unpattern` takes it off again. An item can be worked in one Pattern. It costs nothing extra.

:::insight[Different, never better]{breadth-not-quality}
A Pattern changes what an item is and who it's credited to, never how good it is. Anyone can write any style of prose: knowing a Pattern only lets the game confirm that you worked in it.
:::

The name in the hallmark is the one the Pattern had when the item was made. Copies and services never carry a Pattern.

## Stages

| Stage | What it means |
|---|---|
| **Recovered** | Newly found. Those who know it can use it, but can't teach it yet. |
| **Spreading** | It can be taught. A Pattern spreads when the story it came from concludes, or when staff say so. |
| **Common** | After a while, a spreading Pattern becomes common. It's still learnt by teaching. |

Stages only ever move forward.

## Learning and teaching

You can learn a Pattern by taking part in the story it's tied to: when that plot thread concludes, its active participants learn it. Otherwise, someone who knows it teaches you.

To teach, you and your student must both have posed in the same logged scene, one still running or recently closed. The teacher offers with `+pattern/teach`, and the student answers with `+pattern/accept <Pattern>` or `+pattern/decline <Pattern>`. Whether a lesson costs anything is for your characters to settle. You can't teach another character of your own, and guests can't teach or learn.

`+pattern/info` shows how you learnt a Pattern and from whom. Only staff can see how anyone else did.

:::insight[Learnt in play]
A Pattern passes from one character to another through a scene they shared, so every piece of crafting knowledge has a story of who taught whom.
:::

Players only see Patterns that somebody knows, so a Pattern staff are preparing stays a surprise.

## Proposing a Pattern

Where your game offers it, you can propose a new Pattern with `+request/form pattern=<title>`. The form asks for its name, a description, where it comes from in the setting, the crafts it belongs to and what makes work in it recognisable. If staff approve it, you know it from the start, and it begins as Spreading. Staff decide separately whether it opens any new kinds of item.
