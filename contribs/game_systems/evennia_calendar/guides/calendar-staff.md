---
key: calendar-staff
title: "Staff: events and lotteries"
audience: staff
category: Staff
summary: Staff-event mode, ranked event clusters, locking and fair lottery administration.
---
## What it's for

Staff schedule events with fair allocation when places are limited. See [[calendar]] for attendance and priority tokens. Staff-event toggles and cluster locking use `CALENDAR_STAFF_LOCK`, Builder by default; ordinary event editing is available to its creator or staff.

## Tasks and commands

- **Lottery mode:** `+calendar/staff <event>` toggles an event between normal and staff-event mode. Staff-event means lottery admission, not a private event. Check its time, participant cap and description with `+calendar/view <event>` before opening it to players.
- **Related events:** `+calendar/cluster <title>` creates a cluster. `/cluster/add <event>=<cluster>` and `/cluster/remove <event>` arrange membership before locking. Events in a cluster use ranked-choice `+rsvp/cluster`, rather than separate event RSVPs.
- **Locking a cluster:** `+calendar/cluster/lock <cluster>` opens cluster RSVPs and arms the draw. It refuses an empty cluster, mixed staff-event modes, or events whose draw time has already passed. Lock while there is still ample notice. Membership cannot be changed after locking; inspect it first with `/cluster/view <cluster>`.
- **After the draw:** selected players must confirm; unselected players receive priority tokens, and declined or expired places can pass to the waitlist. Players receive notices for draws, waitlist moves and reminders. `+rsvp/list <event>` and `/waitlist <event>` show the current state. Staff cannot pre-invite players to staff events to bypass the draw.

## What's safe to change

Use the commands to edit event descriptions, caps and tags before a draw. Avoid changing the rules or membership after people have ranked their choices. Never hand-edit RSVP status, priority tokens or lottery flags to choose a winner or replay a draw. A locked cluster has no command to unlock it; investigate an incorrect one before making further changes.

## Privacy

Events and their RSVP lists are meant to help players coordinate. The staff-event marker does not hide either. Treat account-based lottery information as staff information; do not publish which characters share an account when explaining a result.

## Review jobs

Calendar files no automatic review jobs. Attendance notices go to the affected characters, not the staff queue. Handle questions through the game's request tools, checking the event or cluster record before replying.
