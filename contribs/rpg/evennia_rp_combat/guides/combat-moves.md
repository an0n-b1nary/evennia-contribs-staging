---
key: combat-moves
title: Attacks, reactions and resources
category: Playing together
requires: RP_COMBAT_REVEALED
order: 11
summary: How hard to hit, which reaction to choose, hidden bets, and the resources behind special moves.
---
Every exchange in a [[combat|fight]] is an attack and an answer to it. This page covers the choices on each side, and the resources that pay for the special ones.

- `+combat/attack <opponent>=<tier>` attacks with a standard tier, and `+combat/spell` casts the same way.
- `+combat/react <token>=evade|resist|overpower` answers an attack aimed at you.
- `+combat/odds <token>` estimates how each reaction would go.
- `+combat/improv <opponent>=<fields>` improvises a one-off move.

## Attacking

A standard attack picks a tier: light, quick, balanced, strong or heavy. Lighter tiers land more often, and heavier ones hit harder when they land. You can name several targets, and they share one roll.

If your game has Signature moves, use an equipped move's key in place of a tier. An improvised move is designed on the spot with the same fields, but with a smaller budget and room for only one effect.

## Reacting

Each attack on you arrives with a token, shown in `+combat`. Answer it with one of three reactions:

- **Evade** avoids the hit entirely, or turns it into a glancing blow.
- **Resist** takes the hit and reduces it.
- **Overpower** answers with a counterattack, trading damage for damage. Add a tier to choose how hard: `+combat/react <token>=overpower,heavy`.

`+combat/odds` shows a neutral estimate. It counts only what you can see, never the attacker's hidden bet.

:::insight[Standing still isn't a defence]
Each successful Resist adds pressure, and pressure makes your next Resist less effective. Finishing an exchange of your own eases it. A character who only ever braces wears down, so the fight keeps moving.
:::

## Hidden bets

An attacker can secretly bet that the attack is **reaching**, **penetrating** or **subtle**: add `;rps=reaching` when attacking. Each bet favours one reaction and works against another, so a good guess pays off and a bad one costs. The defender doesn't see the bet. With the right ability equipped, `+combat/read` spends something to read an attack before you choose. Another ability lets an attacker announce the bet with `;public`, making it bite harder. The defender sees it and still chooses freely.

## Resources

- **Reserves** pay for special moves and their effects. Standard attacks refill them.
- **Spirit** makes your attacks more or less effective. An assist raises an ally's, and a dispirit lowers an opponent's.
- **Transcendence** builds as you act and as you take real damage. When it's full, add `;empower` to improve one action.
- **Burst:** add `;burst` to start a chain of a few hits, pressed one at a time with `+combat/press`, or ended with `+combat/stop`. A Burst stakes Spirit up front and leaves you exposed, and it can break against Evade or Overpower.

## Stances and effects

A stance is an effect on a move that prepares your next reaction of the matching kind: Evade, Resist or Overpower. It costs some Accuracy and a little more Reserve. The bonus is largest when your attack beats the target's defence, and much smaller when they defend. An unused stance expires after your next action. Different stances can be ready at once.

If your game gives domains effects in a fight, add `;domain=<key>` to use one. You get one domain effect per exchange.

## Abilities

Abilities you equip before the fight can change these rules in small ways: softer Resists, wider glancing blows, cheaper stances, a sharper Burst after patient turns, and more. Each rewards a choice your build would usually skip. **Domain Resistance** blocks a domain's harmful effect aimed at you, though never a helpful one.
