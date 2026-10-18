---
key: moderation-staff
title: "Staff: moderation and admissions"
audience: staff
category: Staff
summary: Reviewing applications, timed bans and mutes, private notes, referrals, and what the records keep.
---
Moderation gives staff account-wide tools: reviewed applications, timed bans, mutes and private notes, each with a reason and a history. Every restriction covers all of an account's characters. Players' side of it is on [[joining]].

## Tasks and commands

- **Reviewing applications:** `+admissions` lists applications waiting for a decision, and `+admissions <job>` shows one. `+admissions/approve <job>=<reason>` creates the account; `+admissions/decline <job>=<reason>` declines it. Add `/share` to decline with the reason shown to the applicant; otherwise the reason stays private. Applications are also ordinary tickets, so `+jobs/form admission` and the web review page work too. Only approve and decline are offered.
- **Reading the review checks:** an application shows the account name, the referrer, and whether the address matches an existing ban or an earlier declined or lapsed application. These are advice, not automatic declines. The password is never shown to anyone.
- **Timed bans:** `+softban <account>=<reason>` bans an account for the default length, and `+softban/ip <address or range>=<reason>` bans an address. `+softban/duration <account>=<hours>` changes the length afterwards, and `+softban/lift` ends it early. A ban disconnects the account's sessions straight away, in the game and on the website.
- **Mutes:** `+mute <account>=<reason>` stops the account talking to other players: pages, channels, boards and OOC chat. In-character posing, `+request` and pages to staff still work. A mute with no duration lasts until `+mute/lift`. Use a timed ban instead when in-character play must stop too.
- **Notes and history:** `+notes <account>` shows the private notes and every moderation action on an account, and `+notes <account>=<note>` adds a note. `+notes/actions` lists recent actions.
- **Permanent bans:** Evennia's own `ban` and `unban` keep their usual behaviour and confirmation, and moderation records each change in the history.
- **Referrals:** `+admissions/tree <account>` shows who referred whom. `/backfill <account>=<referrer>` records a referral for a player admitted by hand. `/reset` starts a new invitation period; decide pending applications first.
- **Seats:** if the game caps the number of players, `+admissions/retire <account>` frees an inactive account's seat without closing it, and `/restore` gives it back.

Intake settings, such as closing applications, the player cap and the referral mode, are runtime settings changed with `+runtime`.

## What's safe to change

- **Order of operations:** apply a restriction with a reason first, then change its duration.
- **Records:** the history and notes are the record of what staff did and why. Don't edit or delete them in the admin; add a note that corrects the record instead.
- **Bans outside the commands:** editing the server's ban list directly skips the history. Use `ban`, `unban` and `+softban` so every change is recorded.

## Privacy

- **Players never see** another player's notes, the referral tree, or which characters share an account. Keep those within staff.
- **Addresses** from an approved application are deleted at once. Addresses from declined or lapsed applications, and those attached to a restriction, are kept only for a limited time after it ends. Notes and history stay.
- **Reasons** for a decline stay private unless you choose to share them.

## Review jobs

Each application is a ticket on the jobs queue. Decide it with `+admissions` or the jobs tools. Players who are muted can still reach you with `+request` and pages, so watch for questions about a restriction and answer them there.
