---
key: building-frontier
title: Growing the public world
category: Places & travel
requires: BUILDING_REVEALED
aliases: [frontier, settlements]
summary: Proposing new public places, building them together, mixed settlements, and stewards.
order: 51
---
Players can grow the public world as well as their own [[building|homes]]: a street, square, or village with homes along it. A frontier project is drafted and reviewed like a home. Once approved, its public rooms belong to everyone.

- `+frontier/new <name>` starts a frontier project.
- `+build/enter <project>` enters it. Building commands use the room where you stand.
- `+collab/add <character>` invites someone to help.
- `+build/interior <name>` adds a home to the current proposed street.
- `+frontier` lists approved public growth.

## Proposing a place

Choose a public anchor and compass direction with `+build/attach <room>=<direction>`. `+build/dig north=The Square` adds a neighbouring street. Doors take destination names and direction aliases, so The Square is reached by its name, `north` or `n`. Room placement and declared directions must agree.

Frontier rooms never connect to nearby existing rooms automatically. From the draft street, propose an additional connection with `+build/connect <existing room>=<direction>`. Remove one with `+build/disconnect <direction>`, even if its former target has disappeared. Approval creates destination-named exits in both directions with the appropriate direction aliases. `+build/check` shows the proposal and warnings.

## Building together

The lead invites collaborators with `+collab/add`. Each collaborator lists invitations with `+collab` and accepts with `+collab/accept <invitation>`. They can enter, dig and describe draft rooms. The lead manages invitations, attachment, proposed ownership, submission, withdrawal and discard. All rooms count against the lead's limits. Group membership grants no rights.

`+collab/remove <character>` removes a collaborator from the current project. Collaborators can leave with `+collab/leave <invitation>`. A removed or departed author's contribution still requires their agreement before promotion.

## Mixed settlements

Standing in a proposed public street, use `+build/interior The Bakery`. Its initial proposed owner is the lead. The command prints its entry room reference; use `+build/room <room>` to enter that interior. Set its proposed owner with `+build/owner <character>`, its name with `/title`, its home or shop purpose with `/purpose`, and its entrance label with `/entrance`. Its rooms have independent local coordinates. `+build/room <street>` returns to the public draft.

Everyone agrees to the same exact candidate before review. `+collab/candidate <project>` shows it. Every collaborator previews their acknowledgement with `+collab/contributor <project>`. Every proposed home owner separately previews ownership with `+collab/ownership <project>`. Repeat each printed token command to agree. Tokens carry the version, fingerprint and wording; players do not type those fields.

Any change needs fresh agreement. `+collab/revoke <agreement>` withdraws an unconsumed acknowledgement. The lead uses `+build/submit` and its printed confirmation command once all required agreements are ready. Staff approve the whole project atomically. Each resulting home belongs to its owner, who manages it with `+property`.

:::insight[Everyone agrees to the same thing]
Changing a shared proposal asks everyone again. Nobody ends up committed to a different home or contribution from the one they reviewed.
:::

## Stewards

Each public room has a **steward**, initially the project's lead. Standing in it, a steward uses `+frontier/desc <text>` and `+frontier/mood <text>` to maintain its description and temporary atmosphere. Stewardship grants no locking, admission, installation or general configuration rights.

`+frontier/relinquish # <reason>` previews giving up that room's stewardship. Repeat the printed token command to hand it back to staff. Only staff can assign a replacement steward. Quiet streets may be flagged for review, but inactivity never changes rights automatically.

Room details and the website's Frontier page show who built a place; descriptions gain no attribution byline.
