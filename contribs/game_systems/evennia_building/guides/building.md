---
key: building
title: Building a home
category: Places & travel
requires: BUILDING_REVEALED
aliases: [homes, property]
summary: Drafting a home, staff review, and deciding who can come in.
order: 50
---
You can build a home of your own: draft its rooms, send it to staff for review, and once it's approved, decide who can come in. Building costs nothing, and it never gives you general building powers. You can also build an apartment inside someone else's home, with their agreement, or help [[building-frontier|grow the public world]].

- `+build/new interior=<name>` starts a project, and `+build/list` lists yours.
- `+build/enter <project>` walks into your draft, and `+build/leave` takes you back out.
- `+build/dig`, `+build/name` and `+build/desc` add and describe rooms.
- `+build/check <project>` shows your rooms, the current version and any warnings.
- `+build/submit <project> <version>=<acknowledgement>` sends it for review.

The website's Building pages offer the same steps.

## Drafting

A draft starts as one room. `+build/dig` adds connected rooms or floors, and `+build/door` joins two rooms you've already made. `+build/attach <project> <room>=<entrance name>` chooses where in the world your front door will go. A project is a home unless you make it a shop with `+build/purpose <project>=shop`. Whether a shop can sell depends on your game.

## Review

`+build/check` shows the version number and the content reuse wording. Submit that exact version, with that wording as your acknowledgement. Submitting freezes the rooms, doors, descriptions and entrance exactly as they are. To change anything after that, withdraw the submission first.

Staff approve it, ask for changes or decline it, with a reason. A decline keeps your draft and its history, and you can propose it again later. `+build/history` shows the whole record. To abandon a draft, `+build/discard` asks you to confirm with a token, then returns anyone inside to safety. A home that's live can't be discarded.

:::insight[What you submit is what's approved]
Submitting freezes the exact version you checked, so nothing can change between your acknowledgement and staff's decision. If you want to change it, withdraw and submit again, so the review always matches the home.
:::

## Your home

Approval keeps your rooms as they are, and adds an entrance from the world and an `outside` exit back. `+build/property` lists your homes.

- **Locking:** `+build/lock <property>` keeps out anyone you haven't let in. A lock never stops anyone leaving.
- **Residents:** `+build/resident/add <property> <character>` makes someone a resident. Residents can enter locked common rooms. They can install things in the home, such as fixtures, only if you add them with `+build/resident/install`.
- **Guests:** `+build/invite <property> <character>` invites someone, and they accept or decline with `+build/invite/accept` or `/decline`. An invitation can also let them see the floor plan.
- **Private rooms:** `+build/override <room>=<characters>` limits one room, such as a bedroom, to the people you name. `+build/override/reset` goes back to the home's defaults.

Nobody you let in can edit, transfer or own your home, and being able to walk in never shows anyone the floor plan. Taking someone's access away never throws them out. A home that sits quiet for a long time may be flagged for staff to look at, but it's never taken from you automatically.

## Apartments

An apartment is a home inside someone else's, reached through their rooms. Choose the entrance and the rooms of theirs you'll pass through with `+build/attach`, then ask with `+build/consent/request <project>`. The other owner looks at exactly what you're proposing with `+build/consent/list` and `+build/consent/show`. They agree with `+build/consent/grant`, using the wording shown, or decline. They can withdraw their agreement until staff approve it. If you change the project afterwards, ask again.

Once approved, the other owner can't lock the rooms you pass through against you, your residents or the guests you let in. That's all the agreement gives: you get no other rooms of theirs, and no right to edit or furnish anything. A guest needs an invitation that includes entry to pass through a locked home. An apartment can't have its own apartments inside it.
