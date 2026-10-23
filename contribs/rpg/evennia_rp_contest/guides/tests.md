---
key: tests
title: Testing your stats
category: Your character
order: 30
principles: [defaults-with-override]
summary: Rolling a stat with +test, and setting a challenge for the room.
---
`+test` rolls a [[checks|check]] in front of the room: one of your stats, sometimes with a subject such as Performance or an element such as Fire. The room sees who tested what and how it went. Unless your game shows more, your grades and the dice stay between you and staff.

- `+test <stat>` tests a stat, and `+test <stat>/<subject>` adds a subject.
- `+test <stat> # <comment>` adds a short note on what you're trying.
- `+challenge/new <difficulty>=<prompt>` sets a challenge for the room, and `+challenge` shows the open ones.
- `+test #2=<stat>` takes on challenge #2.
- `+challenge/history` shows the room's recent attempts.

Tests give no XP or other reward. They decide what happens in the story.

## Challenges

By default, anyone can set a challenge for the room: a difficulty and a short prompt saying what's at stake, such as `+challenge/new <difficulty>=The gate is rusted shut.` A difficulty is a grade, or a name your game defines, such as "hard". Add a suggestion separately with `+challenge/suggest #n=Strength` or `+challenge/suggest #n=Strength/Athletics`. Challenges are numbered within the room.

A test without a number uses the game's usual difficulty. Name a challenge with `+test #n=<stat>[/<tag>]` to answer it.

:::insight[Suggestions, not rails]{defaults-with-override}
A challenge can suggest a stat, but you can meet it any way you like. Charm the guard instead of fighting them. The room is told it's an alternative approach, so it's out in the open, and the story gets the version of your character you meant.
:::

## Retries, once-only challenges and mistakes

You can usually try again. Each retry shows its attempt number, so the room knows. A challenge marked once-only (`+challenge/once #n`) allows each character one attempt.

Whoever set a challenge can edit or close it with `+challenge/edit` and `+challenge/close`, and staff can too. If an attempt shouldn't count, they can **void** it with `+challenge/void`. A voided attempt stays in the history, marked, and no longer counts against a once-only challenge. A challenge nobody touches for a while closes on its own.

Use `+challenge/edit #n=<prompt>`, `+challenge/difficulty #n=<difficulty>` or `+challenge/suggest #n=<stat>[/<tag>]` to change one field at a time. To void an attempt, use `+challenge/void #n.<attempt id> # <reason>`, taking the attempt ID from history.
