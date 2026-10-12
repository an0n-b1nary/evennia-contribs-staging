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
Withdraw first. Live homes cannot be discarded. Frontier building comes later.

To propose an apartment inside another home, choose the attachment and passage
route, then `+build/consent/request <project>`. The parent owner uses
`+build/consent/list` and `/consent/show <request>` to inspect the exact candidate.
They grant it with `/consent/grant <request>=<displayed agreement wording>`, or
decline it. They may revoke before approval. Changes invalidate consent, so ask
again after editing. The website provides the same inspection and answers.

The agreement means the parent owner cannot lock the named passage rooms
against your apartment, its residents or guests you admit. You control your own
home and guests; the parent controls theirs. Passage grants no other parent
rooms, floor plans, editing or installation rights. A guest must accept an
invitation with entry scope before gaining passage through a locked parent.
Room overrides and parent locks never prevent departure. Apartments cannot
contain further separately owned apartments in this release.

Staff can archive/restore a live property while preserving rooms, belongings
and history. Parent archival cannot strand active apartments; staff must handle
affected homes together or arrange replacement passage with both owners.
Quiet-property flags after about five weeks without character play are for
staff review only. They never automatically reclaim or transfer a home.
