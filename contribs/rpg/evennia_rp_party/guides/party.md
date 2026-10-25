---
key: party
title: Party tactics
category: Playing together
requires: RP_PARTY_REVEALED
aliases: [parties]
order: 20
summary: Teaming up within a combat side, Formation and Cover, and making support count.
---
A side in a [[combat|fight]] says who is on whose team. A **Party** is a smaller team inside a side, for players who want to coordinate. It has no leader and no roles, and it lasts only as long as the fight. You can stay unpartied, and one side can have several parties.

- `+party` shows your party: its members, Formation, boosts and Synergy.
- `+party/create <name>` starts a party, and `+party/join <party>` joins one.
- `+party/formation front|back|flex` chooses where you stand.
- `+cover/resist <defender>=<token>` (or Overpower) takes a hit for a teammate.
- `+party/chat <message>` talks privately with your party, out of character.

## Getting together

Join the fight first, then create or join a party. `+party/invite <character>` invites someone, and they accept or decline. Nobody is moved into a party. `+party/leave` leaves once you've no attacks waiting on you and none of your own unanswered. Any member can `+party/rename` it.

To break a party up, a member proposes `+party/dissolve` and everyone answers `+party/agree` or `+party/veto`. Everyone has to agree. Members stay in the fight, unpartied. Anyone in the fight can clean up an empty party, or one whose members are all unavailable.

:::insight[A team without a boss]
Any member can rename, spend or propose, and nobody can be moved or removed by someone else. A party is a way to coordinate, not a hierarchy, so it never gives one player power over another's character.
:::

## Position and Cover

- **Front** protects the Back row of its own party.
- **Back** trades some attacking accuracy for that protection, as long as a Front member can still protect it. Long-range moves soften the trade.
- **Flex** is neutral, and it's where everyone starts.

A downed, recovering or unavailable Front member can't protect anyone.

**Cover** lets a Front member take a hit meant for a Back teammate. It's off until the Back member allows it with `+party/formation back`, then `+party/coveron`, and `+party/coveroff` withdraws it. With it on, attacks on you wait for a Front teammate to decide before your automatic reactions answer them. A coverer takes the hit and reacts at once with Resist or Overpower, but can't Evade. If the hit opens a Burst, the rest of the chain targets the coverer. `+party/coverodds` estimates it first.

## Making support count

A party hits harder when its members' Spirit is high. A successful assist or heal adds **Rally** to the recipient's party, and a dispirit adds **Rattle** to the opponent's. Each supporter's contribution lasts until their own next exchange, and their next support replaces it. Support still works across parties and on unpartied allies.

Parties also build **Synergy** together, and spend it on a [[party-surge|Team Surge]]. A boss may challenge a party with a [[party-boss-checks|Boss Check]].

## Out of character

`+party/chat` reaches the members in this room, downed ones included. It isn't saved and doesn't count as RP. Your party, Formation and Cover permission survive fading, shelving and reloads, and moving between parties never resets your turns.
