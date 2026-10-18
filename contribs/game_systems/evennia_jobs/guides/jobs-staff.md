---
key: jobs-staff
title: "Staff: the jobs queue"
audience: staff
category: Staff
summary: Triaging tickets, deciding structured requests, staff discussions, automated flags and guide questions.
---
Jobs is where players reach staff, and where other systems send things that need a person to decide. Players' side of it is on [[requests]].

## Tasks and commands

- **The queue:** `+jobs` lists every ticket that isn't closed, and `+jobs <id>` shows one with all its comments. `+jobs/list <type>` filters by request, bug, issue or discuss, and `+jobs/form <key>` by structured form. The website's staff queue shows the same.
- **Triage:** `+jobs/assign <id>=<character>` hands a ticket to someone. `+jobs/status <id>=<status>` moves it between open, in review, answered and closed, and `+jobs/priority <id>=<priority>` marks it normal, high or urgent. `+jobs/close` and `+jobs/reopen` close and reopen it.
- **Replying:** `+jobs/comment <id>=<text>` writes to the player. `+jobs/staffonly <id>=<text>` adds a note only staff can read. Leave out `=<text>` to write in an editor.
- **Structured requests:** a form ticket shows its answers by revision. Decide the revision you read: `+jobs/approve <id> <revision>=<reason>`, `+jobs/decline <id> <revision>=<reason>`, or `+jobs/revise <id> <revision>=<reason>` to ask for changes. The web review page offers the same choices. A form may allow only some of these outcomes.
- **Staff discussions:** `+discuss <title>=<text>` opens a staff-only ticket, and `+discuss` lists them. Players never see these.

## How decisions work

- **A decision is separate from status.** Closing or reopening a ticket never approves anything, and approving doesn't close it.
- **Every decision records its reason, reviewer and time.** Approval and decline are final for that ticket. After "changes requested", the player sends a new revision, which keeps the earlier answers and decision.
- **Stale decisions are refused.** If the player revised or withdrew the request after you read it, your decision is turned down, and you read the newer revision instead. The player can withdraw a pending revision at any time.
- **Some forms belong to another system.** An application to join, a building project or a Pattern proposal is decided here, but the owning system does the work on approval. Its review page shows what approval would do, or what blocks it. If approval is refused, nothing is decided; request changes instead.

## Automated flags

Systems that watch for gaming, such as activity tracking and boards, file what they find as staff discussions with no author. Read them with `+discuss`. The flagged player can't see them. A flag is a prompt for a person to look, not a verdict.

## Guide questions

Every guide page has an "Ask about this page" link that opens a request titled "Guide question:" and the page's name. Answer it like any request. When an answer would help everyone, the game's staff can add it to the page itself, so the queue becomes the page's questions and answers.

## Privacy

- **Issue reports** name another player, so their author is hidden from everyone but staff. Never reveal who reported.
- **Staff-only notes** and staff discussions are invisible to players, on the website and through the API. Write anything about other players there, not in a comment.
- **Comments** are visible to the ticket's author. Keep them about the author's own request.

## What's safe to change

Use the commands or the website for every decision, so each has its reason and reviewer. Don't edit decisions, revisions or answers in the admin; a revision a player has submitted stays exactly as they sent it.
