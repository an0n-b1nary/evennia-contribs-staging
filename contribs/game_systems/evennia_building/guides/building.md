---
key: building
title: Building a home
category: Places & travel
requires: BUILDING_REVEALED
summary: Draft an interior, request staff review, and manage private home access.
order: 50
---

Start with `+build/new interior=My home`, then `+build/enter <project>`.
Use `+build/check <project>` to see room numbers, the current version, attachment
warnings and content reuse wording. `+build/dig` adds connected rooms or floors;
`+build/name` and `+build/desc` edit them. `+build/leave` returns you safely.
Choose an attachment with `+build/attach <project> <room>=<named entrance>`.
Building costs nothing and grants no general Builder powers.

Submit the displayed version with `+build/submit <project> <version>=<acknowledgement>`.
Submission freezes the exact rooms, doors, content and attachment. Withdraw the
displayed submission/revision before editing. Staff may approve, request changes
or decline with an explanation. A decline preserves your draft and history; a
later proposal opens a new review cycle. `+build/history` shows the record.

Approval preserves your room identities and creates an unlocked entrance plus
an `outside` exit. `+build/lock` prevents unauthorized entry, never departure.
Residents can enter locked common rooms and install only when explicitly allowed.
Invitations require the named guest to accept. Neither residents nor guests can
edit, transfer or own your home. Room overrides can restrict a bedroom; use reset
to inherit the home defaults again. Physical access does not publish floor plans.

Use `/property` to list homes. The Building website offers the same actions and
exact submission pages. Staff transfer preserves rooms and belongings and clears
ordinary access grants by default. Draft discard displays a confirmation token;
it refuses stale confirmations and safely returns occupants and loose belongings.
Withdraw first. Live homes cannot be discarded. Apartment attachments, staff
archival and frontier building will arrive in later releases.
