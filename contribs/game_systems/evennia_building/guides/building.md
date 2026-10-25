---
key: building
title: Building a home
category: Places & travel
requires: BUILDING_REVEALED
aliases: [homes, property]
summary: Drafting a home, staff review, and deciding who can come in.
order: 50
---
You can build a home of your own: draft its rooms, send it to staff for review, and decide who can come in once it is approved. Building costs nothing and grants no general building powers. You can also build an apartment inside someone else's home, with their agreement, or help [[building-frontier|grow the public world]].

- `+build/new The Bakery` starts an interior project. `+build` lists yours.
- `+build/enter The Bakery` takes you into its draft. Edits use the project and room where you stand.
- `+build/dig north=Kitchen` adds a neighbouring room and a door in each direction. `+build/room Kitchen` moves you there.
- `+build/name <text>` and `+build/desc <text>` change the current room. `+build/title <text>` names the project.
- `+build/attach Market Street=The Bakery` chooses the world room and entrance name.
- `+build/check` shows the whole proposal and review warnings.
- `+build/submit` previews the exact candidate and content reuse agreement. Repeat the printed command with its token to submit.

The website's Building pages offer the same steps.

## Rooms and doors

A draft starts as one room. Directional digging accepts compass names and abbreviations, including up and down. A new door is named after the room it leads to; its direction is an alias. The Kitchen door going north responds to `Kitchen`, `n` and `north`. Default names follow later destination renames. Custom names stay as you wrote them. Direction tags, when supplied by Maps, are display labels: do not copy `<N>` into a door name.

To set explicit coordinates or custom door names, start a room plan with `+build/dig Quiet Study`. Set its fields one command at a time: `+build/x 2`, `+build/y 0`, `+build/floor 1`, `+build/doorname a narrow staircase`, and `+build/back the landing`. Coordinates initially match the source room; `+build/direction north` instead picks its neighbouring cell and direction aliases. Finish with `+build/finish`, or abandon the plan with `+build/cancel`. The plan survives a reconnect. If someone edits the project, cancel the stale plan and start again.

`+build/door Kitchen` joins the current draft room to an existing draft room, using its destination name. `+build/door Kitchen=a serving hatch` sets a custom name. `+build/aliases Kitchen=n,north` sets a door's aliases; commas list aliases only. Door names and aliases must be unambiguous. The entry room reserves the world anchor's name and `out`, `o`, `outside` for its eventual departure.

`+build/purpose shop` proposes a shop instead of a home. Whether it can sell depends on your game. `+build/terrain urban,garden` and `+build/region <region>` request environment changes for staff to approve. `+build/region none` requests no region; `+build/inherit terrain` or `+build/inherit region` restores inheritance for that field.

## Review

Submission previews show what you are agreeing to, followed by a confirmation token. Tokens expire and stop working when the candidate or terms change. You never type version numbers, fingerprints or agreement wording. Submitting freezes rooms, doors, descriptions and attachment exactly as shown. `+build/withdraw # <reason>` previews withdrawal; repeat the printed command to make the draft editable again.

Staff approve, ask for changes or decline, with a reason. A decline keeps the draft and its history, and you can propose it again. `+build/history` shows the record. `+build/discard` previews abandoning a draft; confirmation returns occupants and belongings to safety before removing its geometry. Live homes cannot be discarded.

:::insight[What you submit is what's approved]
Staff review the exact candidate you acknowledged. Changes require withdrawal, a fresh preview and fresh agreements from everyone affected.
:::

## Your home

Approval adds your named entrance from the world with an `in` alias. The departure is named after its destination, such as Market Street, and responds to `out`, `o` and `outside`. `+property` lists the homes whose rooms you may inspect. Stand inside a property to manage it:

- **Descriptions:** `+property/name <text>` and `+property/desc <text>` change the current room.
- **Locking:** `+property/lock` keeps out anyone you have not admitted. `+property/unlock` reopens it. A lock never prevents departure.
- **Residents:** `+property/resident <character>` grants residence without installation rights. `+property/installer <character>` also permits installation. Using `/resident` again removes installation permission; `/unresident` removes residence.
- **Guests:** `+property/invite <character>` invites someone with entry and map rights. `/entry` invites with entry only, and `/maps` with map access only. `/uninvite` revokes the invitation. The invited character uses `+property/invitations`, then `+property/accept <invitation>` or `/decline`.
- **Private rooms:** `+property/override <characters>` restricts the current room to the comma-listed characters and its owner. An empty list means owner only. `+property/reset` restores normal access.

Entry never grants floor-plan access. Residents and guests cannot edit, transfer or own the home. Revocation never ejects someone already inside. Quiet homes may be flagged for staff review but are never reclaimed automatically.

## Apartments and passage

An apartment is an independent home inside another home. Choose its attachment with `+build/attach <room>=<entrance>`. Building uses the parent's outward tree as its passage route; `+build/route <rooms>` can select an explicit comma-listed route from the parent's entry to the attachment room. You need entry or preview rights to those rooms first.

While standing in your apartment draft, use `+consent/request`. The parent owner lists requests with `+consent`, inspects one with `+consent <request>`, and previews agreement with `+consent/grant <request>`. Repeating the printed token command grants consent. `/decline` refuses a pending request; `/revoke` withdraws a grant before promotion. Changing the project requires fresh consent.

After approval, the parent cannot block the agreed passage against the apartment owner, its residents or its admitted entry guests. This grants no other parent rooms, floor plans, editing or installation rights. Apartments cannot have their own apartments.

Staff may propose replacement passage. Each owner inspects it with `+passage <change>` and previews acceptance with `+passage/accept <change>`, then repeats the printed token command. Both current owners must agree before staff applies it. Renaming an automatically named door preserves passage and archive restoration: agreements identify the exit, its endpoints and its permissions.
