---
key: building-frontier
title: Growing the public world
category: Places & travel
requires: BUILDING_REVEALED
aliases: [frontier, settlements]
summary: Proposing new public places, building them together, mixed settlements, and stewards.
order: 51
---
Players can grow the public world as well as their own [[building|homes]]: a new street, a square, a village with homes along it. A frontier project is drafted and reviewed like a home, and once approved its rooms belong to everyone.

- `+build/new frontier=<name>` starts a frontier project.
- `+build/collaborator/add <project> <character>` invites someone to build it with you.
- `+build/interior <project> <street room> <owner>=<name>;<entrance>` adds someone's home to it.
- `+build/frontier` lists public places that have grown this way.

## Proposing a place

Attach a frontier project to a public room with a compass direction, so it joins the map where it belongs. Its compass doors have to agree with where its rooms sit on the map. A frontier never connects to nearby rooms by itself: to join a draft room to an existing room, add `+build/connect <project> <draft room> <existing room>=<direction>` before review.

## Building together

The project's lead invites collaborators, and each one accepts. Collaborators can enter the draft, dig rooms and write their descriptions. The lead manages who's on the project, where it attaches, and submitting or discarding it. The whole project counts against the lead's building limits. Being in the same group as someone gives no building rights.

## Mixed settlements

A settlement can include private homes along its public streets. The lead adds each one with `+build/interior`, naming its future owner.

Before review, everyone agrees to exactly what's being proposed. `+build/ack/show <project>` shows it. Each collaborator acknowledges it as a contributor with `+build/ack/contributor`, and each future home owner accepts their own home with `+build/ack/ownership`. Any change to the project needs fresh agreement. An agreement can be withdrawn until staff approve, and a collaborator who leaves still keeps credit for what they wrote.

Staff approve the whole settlement at once. After that each home belongs to its owner, who manages it like any other home.

:::insight[Everyone agrees to the same thing]
A shared project is only reviewed once every contributor and every future owner has agreed to the exact version in front of staff. Changing it asks everyone again, so nobody ends up committed to something they never saw.
:::

## Stewards

Each public room has a **steward**, at first the project's lead. A steward can describe the room with `+build/frontier/desc <room>=<text>` and set a temporary mood with `+build/frontier/mood`. A steward can't lock the room, let people in or keep them out, install things or change its settings. `+build/frontier/steward` lets a steward hand the room back to staff.

A quiet street may be flagged for staff to look at, but it's never taken away automatically. Who built a place shows in its room details and in the website's Frontier page, never as a byline in its description.
