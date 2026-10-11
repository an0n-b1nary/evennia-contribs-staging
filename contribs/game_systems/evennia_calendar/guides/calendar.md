---
key: calendar
title: Events and RSVPs
category: The world
order: 30
summary: Scheduling an event, the three ways to RSVP, and how lotteries and priority tokens work.
---
The calendar holds upcoming events: a festival, a trial, a hunt. Anyone can schedule one, and the website shows them as a month grid or a list.

- `+calendar` lists upcoming events, and `+calendar/view <id>` shows one with its RSVPs.
- `+calendar/create <title>` schedules an event.
- `+rsvp <id>` signs you up, and `+rsvp/cancel <id>` takes you off.
- `+rsvp/confirm <id>` confirms a place you've been offered.

## Three ways to RSVP

| Kind of event | What `+rsvp` does |
|---|---|
| **Open** | You're in straight away. There's no limit. |
| **Capped** | First come, first served up to the cap. After that you join a waitlist, and the host can offer a place to the next person on it. |
| **Lottery** | Staff events. Everyone who signs up goes into a random draw shortly before the event. If you're drawn, you have a limited time to confirm. |

The host of a capped event can invite people ahead of time. A staff event can't be pre-invited, so nobody gets a place by knowing the right person.

## Priority tokens

If you sign up for a lottery event and aren't drawn, you get a **priority token**. `+rsvp/token/use <id>` spends it on a later staff event to be seated before the draw. `+rsvp/token` shows the tokens you have.

:::insight[Losing a draw counts for something]
A lottery is fair once, but bad luck can repeat. The token means losing a draw this time puts you first in line next time, so the same people don't miss out week after week.
:::

## Event groups

Sometimes several events run at the same time, such as three parts of one plot night. Staff group them, and you rank them in order of preference with `+rsvp/cluster <group>=<first>,<second>,...`. The draw gives each person the highest-ranked event that still has room. Anyone left without a place gets a token that seats them by first preference next time that group draws.

## Tags and clashes

Events have an emphasis, such as combat, skill, social or freeform, and can carry thematic tags. An event can be marked as clashing with another, so you can only sign up for one of the two.
