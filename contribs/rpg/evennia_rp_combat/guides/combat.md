---
key: combat
title: Combat
category: Playing together
requires: RP_COMBAT_REVEALED
aliases: [fighting]
order: 10
summary: Joining a fight by consent, personal turns, reacting, going down, and stepping out.
---
Combat gives a fight in your RP a shared set of rules, so everyone can see what happened and why. Nobody is in a fight without saying yes. There are no rounds: each character takes their own turns, and you write the RP of each exchange as it happens.

- `+combat` shows the fight: everyone's Vitality and turns, attacks waiting on you, and your own resources.
- `+combat/join <side>` joins a fight on a side. Anyone can start one with `+combat/setup`.
- `+attack <opponent>=<move>` attacks. `+assist <ally>` and `+dispirit <opponent>` help or unsettle.
- `+react/<reaction> <token>` answers an attack aimed at you.
- `+combat/fade` steps out of the fight, keeping your place.

## Joining

Every character joins for themselves. If someone attacks a character who hasn't joined, that character is invited privately. `+combat/refuse` turns it down, and only the inviter is told. Refusing costs nothing. `+combat/invite` invites someone without attacking them.

A side says who is on whose team. Anyone can join as a **boss**, with more Vitality and more actions in each turn, and the room is told when they do. Each character has a **Turn Limit**: the number of personal turns they get in this fight. You can lower your own with `+combat/cap` if you arrive late.

:::insight[Nobody fights without saying yes]
A fight only includes the people who joined it, and refusing an invitation is private and free. Combat supports a story everyone has agreed to tell. It never drags anyone into one.
:::

## Your turn

When you act, you attack, cast a spell, assist an ally or dispirit an opponent. The room sees the result once everyone involved has answered. Then describe the exchange in a pose. An IC pose clears the reminder, or `+combat/posed` marks shared prose without a pose of your own. That earns no RP credit.

Before your own next action, answer every attack waiting on you. You can react while you're waiting for a pose or for someone else's answer. [[combat-moves]] covers the choices: how hard to hit, which reaction to pick, and the resources that pay for special moves.

## When you're down

At 0 Vitality you're incapacitated. You can't act or react, and attacks you hadn't answered yet are voided, with their cost refunded to the attacker.

An ally can revive you with a healing assist. The offer waits in `+combat` until you `+combat/accept` or `+combat/decline` it. `+combat/revive accept` accepts allies' revivals automatically. Once revived, `+pass` spends one action getting back up, and nobody can target you until you do. Some healers can spare you that. Poison and other conditions keep running, so a weak revival can be undone.

## Stepping out

- **Fade:** `+combat/fade` steps out without penalty. Your sheet unlocks, so you can change it or join another fight. `+combat/join` later puts you back where you were, with the build you had in this fight. If you leave the room, or your connection is idle for a long while, you're faded automatically. Waiting for others' poses doesn't count as idle.
- **Withdraw:** `+combat/withdraw` leaves for good and counts your remaining Vitality as lost.

You're active in one fight at a time. While you are, your abilities, pips and equipped moves are frozen for that fight, and your sheet stays locked.

## Consent and corrections

- **Cancelling:** `+combat/cancel <token>` cancels an attack aimed at you, but only before you've accepted a reaction to it. Use it for an agreed mistake, not a roll you didn't like. Once an exchange is accepted, only staff can roll the fight back, and they restore the whole fight to a checkpoint for everyone to see.
- **Fixing a build:** to correct your sheet mid-fight, clear your queue and use `+combat/unlock <reason>`, then `+combat/relock <reason>`. Both are announced.
- **Ignoring someone:** if someone you ignore tries to interact with you in a fight, you're asked privately. `+combat/unignore <character>` removes the ignore entirely, including on alts and channels, until you add it back. You can share a fight with someone you ignore without interacting with them.
- **The storyteller asks:** anything a storyteller would change about your character arrives as a numbered request you accept or decline. [[combat-storytelling]] covers it.

## If deciding is hard

`+combat/auto on` answers attacks on you automatically, and `+combat/act` takes one action for you. Neither writes your RP, and automatic choices only use what you could see yourself. If your game has them, `+tactics` saves how cautious or bold those automatic choices are. Choosing tactics doesn't switch automatic reactions on.

## After reconnecting

`+combat` shows your queue as it was. `+combat/journal` lists what happened, and `+combat/result <exchange>` shows an exchange's outcome again without applying it twice. Everything is plain text with clear labels, never colour alone.

## How it connects

Combat rolls use your stats and pips, as [[checks]] explains, and the abilities you equip can change its rules. Ending a fight doesn't decide the story: its assessment suggests outcomes, and the table decides.
