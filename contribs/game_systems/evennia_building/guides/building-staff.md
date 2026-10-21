---
key: building-staff
title: "Staff: building and property"
audience: staff
category: Staff
summary: Frozen submissions, environment decisions, ownership, policies, passage and geometry.
---
## What it's for

Staff review player-built homes and public growth without taking over owners' rights. See [[building]] and [[building-frontier]]. Staff operations use `BUILDING_STAFF_LOCK`, Builder by default.

## Tasks and commands

- **Review the frozen revision:** inspect the submission on the Building website and compare its revision, rooms, entrances, warnings and agreements. `+build/review <submission> <revision> <outcome>=<reason>` accepts `approved`, `changes_requested` or `declined`. Review the exact submitted candidate; changes requested allows revision, while decline needs a new linked submission.
- **Environment:** `+build/environment/approve <submission> <revision>=<reason>` explicitly approves a requested terrain or region change before ordinary approval. It is separate from approving the build. The requested region must still exist and be active; the anchor's later environment edits do not retune an existing property.
- **Ownership and policies:** `+build/transfer <property> <expected owner> <new owner>=<reason>[;return|transfer]` records an intentional transfer, including stock disposition where the shop integration requires it. `+build/policy <room>=open|residential|commercial|closed|reset` sets a room rule; `/policy/region <region>=<policy>` manages its regional default. Room policy wins over the primary region's default. Closed blocks approval; purpose mismatches warn.
- **Archive and restore:** `+build/archive[/children] <property>=<reason>` preserves rooms, possessions and history while detaching access and moving characters to safety. Active children block parent archival unless explicitly included. `/restore <property>=<reason>` rechecks policy, geometry, entrances and passage. Restore the parent before each apartment.
- **Passage:** `/passage/propose <agreement>=<room dbrefs>;<reason>` proposes a replacement route. Inspect it with `/passage/show`; both current owners must accept the exact displayed wording before staff `/passage/apply`. Staff cannot substitute for an owner's agreement. Established passage grants access along that route, not the parent's floor plan or editing rights.
- **Geometry and frontier:** approval checks cells, ports and connections with Maps installed. Without Maps, `/geometry <submission> <revision>=<reason>` certifies the exact candidate manually. Adjacency never creates an exit on its own. `/frontier/steward` records the expected current steward, replacement and reason; frontier archive/restore additionally protects connected homes and streets. Consult `help +build` for its affected-group syntax.
- **Quiet review:** `+build/quiet` checks and lists inactive properties and stewards for staff attention. It never automatically reclaims a home, changes its owner or removes a steward.

## What's safe to change

Use Building's commands and review services for property text, policies, transfers and lifecycle changes; admin is for inspection. Preserve frozen snapshots, fingerprints, agreements, room identities and audits. A stale revision or changed candidate needs fresh review and agreements. Removing a collaborator cannot erase a contributor's required acknowledgement.

## Privacy

Drafts, private homes and their maps have distinct permissions. Entry does not grant publication, remote presence, teleport or editing rights. Invited guests accept their scope individually; alts inherit no invitation. Staff inspection is for the review, not permission to publish a private floor plan.

## Review jobs

With the Building request form registered in Jobs, a submission files a linked request pointing to its authoritative frozen snapshot. Building review and the bound Jobs decision use the same promotion services; an invalid approval rolls back rather than leaving a green ticket and an unbuilt property. Linked reviews also need the relevant Jobs review permission, and promotion still requires Building staff. Without Jobs, native submissions and history remain. Quiet-review flags stay in Building even without Jobs.
