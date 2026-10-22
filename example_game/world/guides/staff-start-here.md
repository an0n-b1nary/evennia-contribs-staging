---
key: staff-start-here
title: "Staff: start here"
audience: staff
category: Staff
summary: Where staff tools are, grouped by the job you're doing.
order: 1
---
These pages are for staff only. In this sandbox anyone can try the staff side with `+sandbox/builder on`, and switch back with `+sandbox/builder off`.

Each system's staff tools are listed below by task, with a link to its staff page. `help <command>` in the game has the full usage for each command.

## Moderation and safety

- **Admissions:** `+admissions` reviews applications to join. See [[moderation-staff]] for bans, mutes, notes and referrals.
- **Problem accounts:** `+softban` for a timed ban, `+mute` to silence every alt, and `+notes` for staff-only notes on an account. `ban` and `unban` are Evennia's permanent bans.
- **Activity:** `+rptracker/review` and `+report/activity` show how roleplay is being counted, and let you flag sessions that look wrong. See [[rptracker-staff]].
- **Presence:** staff can go fully dark with `+unfindable dark`. [[social-staff]] covers what else staff see and can do.

## Requests and review queues

- **The queue:** `+jobs` lists open tickets. `+jobs <number>` shows one, and its switches assign it, set its status and priority, and close it. The web queue is at `/jobs/all/`. See [[jobs-staff]].
- **Forms:** structured requests are approved, declined or sent back for changes with `+jobs/approve`, `+jobs/decline` and `+jobs/revise`. Each takes the revision number, so you always decide on the version you read.
- **Jobs from other systems:** boards, building, lore, plots and moderation file jobs when something needs a staff decision, and Pattern proposals arrive as a request form. Work them like any other ticket. Automated flags, such as activity tracking's, arrive as staff discussions with no author; read them with `+discuss`.
- **Guide questions:** every guide page has an "Ask about this page" link that files a request. See [[requests]] for how players see it.

## Story and events

- **Plots:** `+arc` groups plots into arcs and sets the current one, and `+hook` suggests a plot to a particular player. See [[plots-staff]].
- **Lore:** `+lore/queue` lists submissions; `+lore/approve` and its siblings decide them. `+tome` writes and publishes a book whose pages cite lore entries. See [[lore-staff]].
- **Scenes:** `+log/rollback` returns a log entry to an earlier version. See [[scenes-staff]].
- **Calendar:** `+calendar/staff` turns lottery mode on or off for a staff event. See [[calendar-staff]].
- **Boards:** boards are created in the Django admin; `+bb/archive` archives old posts. See [[boards-staff]].
- **XP:** `+xp/grant` makes a one-off award. See [[xp-staff]].

## World and places

- **Building:** `+build/review` works through submitted building projects. See [[building-staff]].
- **The map:** `+map/place`, `+map/move` and `+map/check` lay rooms out and check the layout. See [[maps-staff]].
- **Regions:** `+region/create`, `+region/add-room` and `+region/primary` set where rooms belong. See [[regions-staff]].
- **NPCs:** `+npc/approve` and `+npc/deny` decide permission requests to play shared NPCs. See [[npcs-staff]].
- **Reveal switches:** `+runtime` lists the runtime switches. A reveal opens the system's player commands and the guide pages gated on that check; ungated pages remain public. See [[links-staff]].

## Characters and conflict

- **Character sheets:** `+chargen` lists, approves and reopens sheets; `+sheet <character>` reads anyone's. See [[chargen-staff]].
- **Tests:** `+test/review` is the staff view of a test's history. See [[contest-staff]].
- **Combat:** `+combat/rollback` returns a whole fight to a consistent checkpoint. See [[combat-staff]].
- **Party:** `+bosscheck` offers manual Party challenges; committed consequences use combat staff recovery. See [[party-staff]].
- **Gear:** `+gear/audit` lists worn gear whose requirements no longer hold. See [[equipment-staff]].

## Economy and making

- **Money:** `+economy` shows the money totals; `/run` pays weekly income, `/credit` and `/debit` adjust a purse, and `/audit` and `/flags` show what to review. `+shop/reconcile` opens a shop that was approved earlier. See [[economy-staff]].
- **Resources:** `+resources/grant` hands out resources by hand, and `+resources/payoutapprove` approves plot payouts. See [[resources-staff]].
- **Crafting:** `+crafting` seeds and archives the catalogue, and `+crafting/review` shows a crafted item's permanent record. The `+pattern` staff switches create and curate Patterns, and Pattern proposals arrive as request forms. See [[crafting-staff]].

## Writing and checking guide pages

[[writing-guides]] explains how pages like this one are written, hidden until their system opens, and checked.
