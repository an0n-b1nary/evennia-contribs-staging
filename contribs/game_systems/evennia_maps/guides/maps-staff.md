---
key: maps-staff
title: "Staff: map layout"
audience: staff
category: Staff
summary: Placing rooms, pins, reflow previews, layout checks and map privacy.
---
## What it's for

Staff keep room geometry readable and repair placement conflicts. See [[map]] for the player view. Placement, pinning, reflow and checks use `MAPS_STAFF_LOCK`, Builder by default; ordinary map viewing is open to players.

## Tasks and commands

- **Place or move:** `+map/place <#room>=<plane>` puts a room at the plane's origin; a new name creates an interior plane. `+map/move <#room>=<x>,<y>` changes its mapped position. `/unplace <#room>` removes its tile, not the room or exits.
- **Protect a landmark:** `+map/pin <#room>` keeps automatic placement and reflow from moving its tile; `/unpin` releases it. A pin is a layout constraint, not a privacy flag.
- **Preview before reflow:** `+map/reflow <#room>` walks the connected layout and reports proposed moves and conflicts without applying them. `+map/reflow <#room>=<token>` applies the allowed moves atomically using the token from that preview. The token is valid for 15 minutes and only for the staff character and origin that requested it; if the layout changes, request a new preview. Pinned or conflicting tiles stay put; a blocked move does not stop unrelated moves. Read the fresh report and check the result afterwards.
- **Find drift:** `+map/check` reports unmapped neighbours, missing terrain snapshots and tiles on room types declared off-map. Correct the underlying exits, terrain or placement rather than repeatedly moving a symptom.

## What's safe to change

Use the map commands to preserve placement checks and cache invalidation. Keep planes and room identities stable. Changing a tile does not repair an exit or move a physical room; inspect both geometry and traversal when fixing a conflict. Automatic placement follows newly created exits and will not invent the intended layout when exits disagree.

## Privacy

Mapped is not the same as public. Host room-visibility rules filter the website and feeds; a pin or a plane name does not hide a private room. With a property integration installed, check its map permissions as well as entry access before publishing a floor plan.

## Review jobs

Maps files no automatic review jobs. `+map/check` and the reflow report are its diagnostic lists. If someone reports a broken map through the game's request tools, record the room and plane, repair the underlying problem, and check the player's view before replying.
