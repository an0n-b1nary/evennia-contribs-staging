---
key: plots-staff
title: "Staff: plots and arcs"
audience: staff
category: Staff
summary: Arcs, hooks, major tags, conclusions, archives and plot review requests.
---
## What it's for

Staff connect stories, invite people into them, and help owners bring them to a close. The player side is on [[plots]]. Staff tools use `PLOTS_STAFF_LOCK`, Builder by default. Plot owners can manage their own plots; `+arc`, `+hook`, major tags and archiving need staff permission.

## Tasks and commands

- **Arcs:** `+arc/create <name>[=<tagline>]` groups a larger story; `+arc/link <arc>=<plot>` adds a plot. `/type <arc>=story|downtime` chooses its type, and `/current <arc>` makes it the global current arc. `/uncurrent` clears that choice; `/conclude <arc>` ends it and clears current if needed.
- **XP pacing:** `+arc/xp <arc>` shows per-source multipliers; `+arc/xp <arc>/<source>=<value>` overrides one, and `+arc/xp <arc>/<source>=default` clears the override. Downtime defaults to pausing the supported XP sources. Check the displayed sources before changing the pace. `+arc/award <arc>=<amount> # <reason>` makes a manual award to its participants; concluding an arc does not automatically make that award.
- **Hooks:** `+hook <plot>=<character>` privately suggests a public or invite-only plot to a player. It refuses private plots and keeps a staff-visible record. A hook does not make someone a participant.
- **Major tags:** `+plot/major <plot>=<tag>` creates a major theme or promotes an existing tag. Ordinary owners can add tags, but only staff choose which are major.
- **Concluding or archiving:** `+plot/conclude <plot>` intentionally wraps up a plot and computes its bonus from advance calendar notice, linked scenes and an IC board post. With the XP integration registered, participants receive it through the weekly batch, subject to arc pacing. Ownership alone earns nothing, and the smaller story threads never add XP. `+plot/archive <plot>` retires a stale plot without a conclusion bonus.
- **Loose ends:** inspect threads before concluding. Resolution and dropping leave sealed answers sealed unless explicitly revealed; use `+thread/answer <plot.thread>` to inspect one and `+thread/reveal` only when it should be shared.

## What's safe to change

Use commands to edit arc prose, tags, ownership and pacing. Keep plot numbers, participant credits and version history intact; never edit award flags or credit rows to force a payment. An arc's manual award is a separate decision: repeating the command can pay again.

## Privacy

Staff can inspect private plots, participant OOC notes, sealed answers and hook records. Keep those details with their intended audience. Concluding a thread is not permission to publish its answer; revealing it is an explicit action.

## Review jobs

With Jobs installed, `+plot/request-conclude <plot>` files a request ticket. Review the plot, conclude or archive it through the plot command, and answer the ticket. Changing the ticket's status alone does not conclude the plot. Without Jobs the command reports that ticket submission is unavailable.
