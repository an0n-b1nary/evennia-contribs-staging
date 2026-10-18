---
key: rptracker-staff
title: "Staff: roleplay activity"
audience: staff
category: Staff
principles: [rp-never-a-quota]
summary: Reviewing and flagging RP sessions, the activity report, and alt co-presence notices.
---
Activity tracking notices roleplay on its own, and games usually pay XP for it. Staff work here is keeping that fair: looking at sessions that seem wrong, and reading activity across the game. Players' side of it is on [[rp-sessions]].

## Tasks and commands

- **Reviewing sessions:** `+rptracker/review` lists flagged sessions and the past week's completed sessions.
- **Flagging:** `+rptracker/flag <id>=<reason>` flags a session that looks like gaming, and `+rptracker/unflag <id>` clears it. A flagged session earns no XP until the flag is cleared. A flag covers that one session; the player's other sessions are unaffected.
- **Automatic flags:** the tracker also flags some patterns by itself, such as pose spam and repeatedly ending sessions by hand. With jobs installed, each automatic flag arrives as a staff discussion for someone to review.
- **The activity report:** `+report activity [days]` totals sessions, characters and time across the game for the past week, or up to a few months. It groups them by region, or by room in a game without regions, and channels separately. Flagged sessions are shown apart and left out of the totals. Reading the report changes nothing.

:::insight[Read activity, never ration it]{rp-never-a-quota}
The report shows where play is happening, so staff can see quiet corners and busy ones. It isn't a target for anyone to meet, and it never decides who earns what.
:::

## Alt co-presence notices

When characters from the same account keep turning up in the same room or channel sessions, the tracker sends one advisory notice per account for the window, through the same review route as automatic flags. It never flags a session or withholds XP. Decide whether a conversation is needed; often there's an innocent reason.

## Privacy

Sessions record which accounts took part, so staff can tell when one player's characters are partnering each other. Players can't see that. Keep it within staff, and raise it with the player privately if it needs raising.

## What's safe to change

Flag and unflag through the commands, so each change carries a reason and your name. Don't edit sessions in the admin; flags decide XP, and the weekly batch reads them.

## Review jobs

Automatic flags and co-presence notices arrive as staff discussions. Read them with `+discuss`, check the session with `+rptracker/review`, and flag or unflag it.
