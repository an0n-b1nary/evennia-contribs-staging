---
key: notices
title: Personal notices
category: Communication
summary: Read alerts, choose source preferences and resolve pending decisions.
order: 40
---

Your inbox keeps account notices and notices for the one character you are
currently playing or have explicitly selected on the website. It never uses
another simultaneous session's character to grant access. Staff cannot read
someone else's inbox. Disposable guests receive connected messages only.

Use `+notices` for unread alerts and outstanding decisions, `+notices/read <notice>`
to acknowledge an alert, `+notices/clear <notice>` to dismiss it, and
`+notices/history` for retained history. The website's **My Notices** has the
same state. Opening a page does not mark it read; use **Mark read**.

Reading an alert does not read a board post or conversation, accept an invitation,
or resolve a decision. Only a currently outstanding sought lottery selection or
waitlist offer prevents clearing. Follow its source instructions to confirm or
decline; expiry or cancellation removes it from pending decisions automatically.
Ordinary invitations remain dismissible.

`+notices/settings` shows account-wide source choices. Set one with
`+notices/set <source>=summary`, `=immediate` or `=off`. Routine alerts default to
quiet summary storage. Immediate stores them and sends an eligible connected
session a hint. Off suppresses new routine activity. Decisions always persist:
their default is immediate, and explicit off or summary keeps them in summaries.
Changing preferences neither replays old activity nor changes source read state.

Every count, summary and rendered notice rechecks current source visibility,
validity and ignore boundaries. Missing context or unavailable sources expose
neither names nor counts and remain retryable. Hidden or invalid content leaves
the active inbox. Social treats notices as OOC contact: hidden/full boundaries,
legacy full boundaries and posts exceptions suppress their activity completely.
Staff sender/viewer bypass follows Social's existing rules.

Older routine activity may combine within one source. Combined notices keep
their separate read state and show only activity you may currently see. Read,
cleared and replaced history is normally removed after 30 days from its first
acknowledgement or replacement. Unread alerts and pending decisions survive. Retrying old
activity never recreates a notice you already dismissed.
