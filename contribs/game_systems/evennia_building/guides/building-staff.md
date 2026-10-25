---
key: building-staff
title: "Staff: building and property"
audience: staff
category: Staff
summary: Frozen submissions, environment decisions, ownership, policies, passage and geometry.
---
## What it's for

Staff review player-built homes and public growth without taking over owners' rights. See [[building]] and [[building-frontier]]. Staff operations use `+buildadmin` and `BUILDING_STAFF_LOCK`, Builder by default. The old staff forms under `+build` are refused.

## Review the frozen revision

`+buildadmin` lists pending submissions. `+buildadmin <submission>` shows its frozen rooms, entrances, warnings and agreements. Choose `+buildadmin/approve <submission> # <reason>`, `/changes` or `/decline`. Each previews the decision and prints a complete confirmation command. Copy that command to apply it. Changes requested permits editing and resubmission; decline requires a new linked submission.

`+buildadmin/environment <submission> # <reason>` separately previews and approves requested terrain or region changes before ordinary approval. The requested region must still be active. Without Maps, `+buildadmin/geometry <submission> # <reason>` explicitly certifies the exact compass geometry. With Maps, promotion validates cells, ports and connections. Adjacency alone never creates an exit.

Tokens expire after fifteen minutes. They bind the acting character, decision, reason and current affected records. Changed candidates or permissions still pass through the authoritative review checks. A changed owner or steward requires a fresh draft. No one types expected owners, revisions, fingerprints or agreement wording.

## Transfer a property

Start `+buildadmin/transfer <property>=<character> # <reason>`. Access grants clear by default; use `+buildadmin/grants retain` to keep them. A shop requires an explicit `+buildadmin/stock return` or `+buildadmin/stock transfer` choice. Returning stock sends it to the former owner; transferring includes it with the shop, subject to Economy's normal restrictions.

`+buildadmin/draft` inspects your private, persistent draft. `+buildadmin/reason <text>` sets its reason. `+buildadmin/finish` previews affected owners, rooms and choices and prints a confirmation command. Copy it to apply the draft. Changes to the draft, access grants or merchandise require another preview. `/cancel` abandons the draft. Only one staff draft may be open per character; it survives reconnects.

## Archive and restore

`+buildadmin/archive <property> # <reason>` starts an archive draft. Active apartments block it until you explicitly choose `+buildadmin/children yes`. Inspect the complete group and owners with `/finish`, then confirm. Archival preserves rooms, possessions and history while detaching access and moving characters to safety.

`+buildadmin/restore <property> # <reason>` previews restoration and prints its confirmation command. Restoration rechecks current ownership, policy, environment, geometry, entrances and passage. Restore the parent before each apartment.

## Retire public growth

`+buildadmin/retire <frontier> # <reason>` starts a coordinated retirement draft. `+buildadmin/frontiers <areas>` sets a comma-separated list of additional frontier areas; `+buildadmin/properties <homes>` sets the affected properties. Empty lists clear those fields. All dependent homes and streets must be covered, or replacement connections must preserve public access.

Add each bypass with `+buildadmin/replacement <room>/<direction>=<room>`. `+buildadmin/unreplace <room>/<direction>` removes it. These are bidirectional public connections between surviving rooms, with the same port and Maps geometry checks as other connections. `/finish` checks connectivity without creating exits, lists the complete affected group and prints its confirmation command.

`+buildadmin/frontierrestore <frontier> # <reason>` previews restoration of the complete preserved frontier group, even when you select another member of that group. Confirm it to reopen the streets, then restore homes separately. No retirement or restoration bypasses connectivity and lifecycle checks.

`+buildadmin/steward <room>=<character> # <reason>` starts a stewardship draft; use `none` for no individual steward. Preview and confirm with `/finish`. A steward may still relinquish their own room through `+frontier`.

## Passage and policies

`+buildadmin/passage <agreement>=<rooms> # <reason>` starts a replacement passage draft, with a comma-separated list of parent rooms. Preview and confirm with `/finish`. Both current owners must then inspect `+passage <change>`, preview `+passage/accept <change>` and confirm their own tokens. Staff cannot substitute for either owner's agreement. After both accept, `+buildadmin/apply <change>` previews the application and prints its confirmation command.

Passage grants access along the agreed route, not the parent's floor plan or editing rights.

`+buildadmin/policy <room>=<policy>` sets a room rule. `+buildadmin/region <region>=<policy>` manages a regional default when Regions is installed. Policies are `open`, `residential`, `commercial`, `closed` or `reset`. An optional audit reason follows ` # `. Room policy wins over the primary region's default. Closed blocks approval; purpose mismatches warn.

`+buildadmin/quiet` refreshes and lists inactive properties and stewards for staff attention. It never reclaims a home, changes an owner or removes a steward automatically.

## What's safe to change

Use Building's commands and review services for policies, transfers and lifecycle changes; admin is for inspection. Preserve frozen snapshots, fingerprints, agreements, room identities and audits. A stale candidate needs fresh review and agreements. Removing a collaborator cannot erase a contributor's required acknowledgement. Automatic door names follow destination renames; blocked renames appear as review warnings.

Drafts, private homes and their maps have distinct permissions. Entry does not grant publication, remote presence, teleport or editing rights. Invited guests accept their scope individually; alts inherit no invitation. Staff inspection is for review, not permission to publish a private floor plan.

## Review jobs

With the Building request form registered in Jobs, submission files a linked request pointing to its authoritative frozen snapshot. Building review and the bound Jobs decision use the same promotion services; invalid approval rolls back the ticket and property together. Linked reviews also require the relevant Jobs review permission. Without Jobs, native submissions and history remain. Quiet-review flags stay in Building even without Jobs.
