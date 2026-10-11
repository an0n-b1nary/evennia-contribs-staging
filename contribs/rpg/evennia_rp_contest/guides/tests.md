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
- `+test <stat>~<comment>` adds a short note on what you're trying.
- `+test/set <difficulty>~<prompt>` sets a challenge for the room, and `+test/list` shows the open ones.
- `+test #2=<stat>` takes on challenge #2.
- `+test/history` shows the room's recent attempts.

Tests give no XP or other reward. They decide what happens in the story.

## Challenges

By default, anyone can set a challenge for the room: a difficulty and a short prompt saying what's at stake, such as `+test/set <difficulty>=Strength~The gate is rusted shut.` A difficulty is a grade, or a name your game defines, such as "hard". The stat after `=` is a suggestion. Challenges are numbered within the room.

If you test without a number and exactly one open challenge fits what you're testing, it applies. Otherwise your test is against the game's usual difficulty.

:::insight[Suggestions, not rails]{defaults-with-override}
A challenge can suggest a stat, but you can meet it any way you like. Charm the guard instead of fighting them. The room is told it's an alternative approach, so it's out in the open, and the story gets the version of your character you meant.
:::

## Retries, once-only challenges and mistakes

You can usually try again. Each retry shows its attempt number, so the room knows. A challenge marked once-only (`+test/set/once`, or `+test/once #n` later) allows each character one attempt.

Whoever set a challenge can edit or close it with `+test/edit` and `+test/close`, and staff can too. If an attempt shouldn't count, they can **void** it with `+test/void`. A voided attempt stays in the history, marked, and no longer counts against a once-only challenge. A challenge nobody touches for a while closes on its own.
