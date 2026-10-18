---
key: equipment-staff
title: "Staff: gear"
audience: staff
category: Staff
summary: The gear audit, hiding gear until it's revealed, and what staff can and can't change.
---
Gear is cosmetic: it never changes a check. Staff work is mostly keeping worn gear consistent with the builds it depends on, and choosing when players first see it. Players' side of it is on [[equipment]].

## Tasks and commands

- **Finding broken gear:** `+gear/audit` lists worn gear whose requirements no longer hold, or that names a stat, ability or flaw the game no longer has. It changes nothing. The same list is available as `evennia rp_equipment_audit`, and a game can log it at startup.
- **Hiding gear until it opens:** `RP_EQUIPMENT_REVEALED` is a runtime setting. `+runtime RP_EQUIPMENT_REVEALED=false` hides `+gear`, `+wear`, `+remove`, `+worn` and `+outfit` from players, along with this system's player page. Staff keep the commands, so gear can be made and tested before the reveal. Gear that is already worn stays worn and keeps showing in descriptions.
- **Taking gear off someone:** `+remove` only works on your own gear, so ask the wearer. If they can't, a staff teleport moves the item away and takes it off.

## What's safe to change

- **Builds:** a staff change to someone's build, through `+chargen` or any other chargen tool, is refused when it would break a requirement of worn gear, exactly as a player's change is. There is no override. Take the item off first, then make the change. Granting or raising anything never conflicts with gear.
- **The ruleset and catalogue:** renaming a stat, ability or tag is safe, because requirements are stored by key. Removing one, or editing sheets outside the chargen commands, goes around the guard. Run `+gear/audit` afterwards and settle each case by hand.
- **Sealed items:** once someone other than the maker has held an item, nobody can change its description, worn line or requirements in the game. Don't edit those by hand to get around a seal; make a new item instead.

## Privacy

Covered gear is hidden from ordinary looks but still worn, and anyone can see it with `+worn/all`. Outfits are private to the character that saved them.

## Review jobs

Gear files no jobs. When the audit finds a problem, contact the player, agree on whether to take the item off or adjust the build, and make the change in that order.
