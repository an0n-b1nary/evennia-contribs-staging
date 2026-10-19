---
key: party-surge
title: Synergy and Team Surge
category: Playing together
requires: RP_PARTY_REVEALED
order: 21
summary: How a party builds Synergy, and spending it on one boosted action.
---
A [[party]] builds **Synergy** as its members fight, and any member can spend it on a **Team Surge**: one action with a boost to its main effect.

- `+party` shows the party's Synergy, what's reserved, and whether you've used your Surge this turn.
- `+party/surge <target>=<move>` makes an attack, spell, assist or dispirit as a Surge.
- `+party/surgepress` makes the next hit of your Burst a Surge.

## Building Synergy

A party earns Synergy when its members finish exchanges, take real damage from opponents, and empower their actions. Recovering, cancelling, joining and corrections earn none. A bigger party can hold more Synergy. If a party shrinks, what it holds can shrink with it, and Synergy never moves with a member who changes party.

## Surging

A Surge uses the same options as an ordinary action, with `;action=spell` or `;action=assist` to change the action. On an attack with several targets, `;target=<name>` picks which one is boosted. For an improvised move, use `+party/surge/improv`.

A Surge boosts damage, or the Spirit and healing from support. It doesn't add accuracy, reserves, an extra action or an extra target. Each character can Surge once per personal turn.

Declaring a Surge reserves the Synergy at once. If the action is cancelled, or a revival it carried is declined, the Synergy comes back. A miss still spends it. Automatic actions never spend Synergy.

:::insight[Anyone may spend it]
Any member can spend the party's Synergy, so a party works out among its members who spends it and when. The game doesn't rank members or hand anyone a veto.
:::

## How it connects

A Surge is an ordinary [[combat-moves|attack or support]] with a boost. If an opponent covers for the target of your Surge, the boost applies to the coverer instead.
