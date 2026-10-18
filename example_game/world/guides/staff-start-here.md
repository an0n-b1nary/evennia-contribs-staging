---
key: staff-start-here
title: "Staff: start here"
audience: staff
category: Staff
summary: Where staff tools are, grouped by the job you're doing.
order: 1
---
These pages are for staff only. In this sandbox anyone can try the staff side with `+sandbox/builder on`, and switch back with `+sandbox/builder off`.

Each system's staff tools are listed below by task. Where a contrib has its own staff page, its line links to it; the rest will be linked as they arrive. Until then, `help <command>` in the game has the full usage for each command.

## Moderation and safety

- **Admissions:** `+admissions` reviews applications to join. See [[moderation-staff]] for bans, mutes, notes and referrals.
- **Problem accounts:** `+softban` for a timed ban, `+mute` to silence every alt, and `+notes` for staff-only notes on an account. `ban` and `unban` are Evennia's permanent bans.
- **Activity:** `+rptracker/review` and `+report activity` show how roleplay is being counted, and let you flag sessions that look wrong. See [[rptracker-staff]].
- **Presence:** staff can go fully dark with `+unfindable dark`. [[social-staff]] covers what else staff see and can do.

## Requests and review queues

- **The queue:** `+jobs` lists open tickets. `+jobs <number>` shows one, and its switches assign it, set its status and priority, and close it. The web queue is at `/jobs/all/`. See [[jobs-staff]].
- **Forms:** structured requests are approved, declined or sent back for changes with `+jobs/approve`, `+jobs/decline` and `+jobs/revise`. Each takes the revision number, so you always decide on the version you read.
- **Jobs from other systems:** boards, building, lore, plots and moderation file jobs when something needs a staff decision, and Pattern proposals arrive as a request form. Work them like any other ticket. Automated flags, such as activity tracking's, arrive as staff discussions with no author; read them with `+discuss`.
- **Guide questions:** every guide page has an "Ask about this page" link that files a request. See [[requests]] for how players see it.

## Story and events

- **Plots:** `+arc` groups plots into arcs and sets the current one, and `+hook` suggests a plot to a particular player.
- **Lore:** `+lore/queue` lists submissions; `+lore/approve` and its siblings decide them. `+tome` writes and publishes a book whose pages cite lore entries.
- **Scenes:** `+log/rollback` returns a log entry to an earlier version.
- **Calendar:** `+calendar/staff` turns lottery mode on or off for a staff event.
- **Boards:** boards are created in the Django admin; `+bb/archive` archives old posts.
- **XP:** `+xp/grant` makes a one-off award.

## World and places

- **Building:** `+build/review` works through submitted building projects.
- **The map:** `+map/place`, `+map/move` and `+map/check` lay rooms out and check the layout.
- **Regions:** `+region/create`, `+region/add-room` and `+region/primary` set where rooms belong.
- **NPCs:** `+npc/approve` and `+npc/deny` decide requests for shared NPCs.
- **Reveal switches:** `+runtime` lists the runtime switches. Turning one on publishes that system's commands and its guide pages together.

## Characters and conflict

- **Character sheets:** `+chargen` lists, approves and reopens sheets; `+sheet <character>` reads anyone's.
- **Tests:** `+test/review` is the staff view of a test's history.
- **Combat:** `+combat/rollback` returns a whole fight to a consistent checkpoint.
- **Gear:** `+gear/audit` lists worn gear whose requirements no longer hold. See [[equipment-staff]].

## Economy and making

- **Money:** `+economy` shows the money totals; `/run` pays weekly income, `/credit` and `/debit` adjust a purse, and `/audit` and `/flags` show what to review. `+shop/reconcile` opens a shop that was approved earlier.
- **Resources:** `+resources/grant` hands out resources by hand, and `+resources/payoutapprove` approves plot payouts.
- **Crafting:** `+crafting` seeds and archives the catalogue, and `+crafting/review` shows a crafted item's permanent record. The `+pattern` staff switches create and curate Patterns.

## Writing and checking guide pages

[[writing-guides]] explains how pages like this one are written, hidden until their system opens, and checked.
