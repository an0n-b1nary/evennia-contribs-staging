---
key: combat
title: Combat
category: Playing together
requires: RP_COMBAT_REVEALED
summary: Join by consent, take personal turns, and choose reactions.
---
Combat supports your RP. Each player explicitly joins a side with
`+combat/join side`; an invitation can be refused privately, without a
penalty. `+combat` commands act only as your own character. Anyone may set up
a fight with `+combat/setup` and take the storyteller's role with publicly
attributed `+combatstory` controls. Your NPC permissions remain separate.

## Your turn

Use `+combat` to see Vitality, personal turns, incoming attacks and your own
resources. There are no global rounds. Resolve or cancel every incoming
attack before acting; reactions are available while you owe a pose or wait
for someone else's reaction. After an exchange, describe it in RP. An IC
pose clears the pose reminder, or `+combat/posed` acknowledges shared prose
without creating a pose or granting XP.

`+combat/attack opponent=balanced` starts an attack. The tiers light, quick,
balanced, strong and heavy trade Power for Accuracy. Spell uses the same
syntax. `+combat/assist ally` supports an ally; `+combat/dispirit opponent`
pressures an opponent's Spirit. A boss has more Vitality and actions per
personal turn; ordinary characters start with four personal turns.

## Reacting

Choose from Evade, Resist or Overpower using your incoming token:
`+combat/react token=resist`. Evade can avoid all damage or glance; Resist
mitigates successful hits; Overpower trades a counterattack against incoming
damage. `+combat/react token=overpower,heavy` selects a counter tier.
`+combat/odds token` shows neutral estimates, not the attacker's hidden bet.

Successful Resist adds pressure based on damage prevented. Pressure makes
later Resists less effective; your own completed exchange recovers some.
Repeatedly standing still and Resisting is not a reliable defense.

An attack may secretly bet reaching, penetrating or subtle, each favoring
one reaction and disadvantaging another. Add `;rps=reaching` when declaring.
Equipped Insight can buy `+combat/read token=insight` before reacting.

## Moves and resources

`+moves` lists your free Signature library and equipped loadout. Author and
equip a move before the fight, for example:
`+moves/create Ready Guard={"power":1,"accuracy":1,"effects":["resist_stance"]}`,
then `+moves/equip ready-guard`. Use its key instead of a standard tier.
Signatures have two Effect slots; improvised moves have one.

Reserves pay for special moves and Effects. Standard attacks replenish them.
Spirit changes attack effectiveness. Transcendence grows through actions and
actual damage; at 100, `;empower` improves one packet. `;burst` starts a chain
of up to three manually pressed hits: `+combat/press` or `+combat/stop`.
Burst antes Spirit, carries unpaid exposure, pays each hit's costs, and can
break against Evade or Overpower.

Evade, Resist and Overpower Stances prepare their matching next reaction.
Distinct Stances can coexist, but each reduces the move's Accuracy and adds
cost. Beating the target's defense grants the full bonus; a successful
defense greatly reduces it. Unused Stances expire after your next action.

## Consent and corrections

`+combat/cancel token` cancels an incoming attack only before you accept its
reaction. Use it for an agreed mistake, not an unfavorable dice result.
Automatic reaction acceptance also closes cancellation. Later rollback is
staff-only and visibly restores the whole fight to a checkpoint.

An ignore crossing prompts its owner privately. Explicitly choosing
`+combat/unignore character` removes the actual account-wide ignore,
including alts and channel filtering, until you restore it yourself.
You can still cancel an unaccepted attack or share a fight without directly
interacting with someone you ignore.

Joining freezes your Abilities, Edge and Signatures for that fight, and your
sheet stays locked while you are active in it. An agreed correction uses
`+combat/unlock reason` and `+combat/relock reason` with clear queues,
announcing both steps. `+combat/fade` steps out neutrally and releases your
sheet, so you can edit it or join another fight; `+combat/join` later puts
you back exactly where you were, with the build you had in this fight. You
are active in one fight at a time. `+combat/withdraw` counts remaining
Vitality as lost. If you stop sending any commands for an hour, or disconnect
that long, you are Faded safely; quietly waiting for poses is fine.

The storyteller cannot change your character without you. Damage, healing,
Spirit, conditions, a lower Turn Limit or a return to the fight arrive as a
numbered request in `+combat`; answer with `+combat/accept n` or
`+combat/decline n`. Ending a fight needs every present player's agreement.
An incapacitated or withdrawn character returns only through a visible
`+combatstory/requestreturn name=Vitality;reason` they accept. Returning
retains turns, resources and loadout, and restored Vitality adds assessment
exposure rather than erasing prior loss. Late arrivals can voluntarily reduce
their cap with `+combat/cap number`. Assessment suggests RP outcomes; it
imposes none.

Need to stop for a few days? `+combatstory/shelve reason` sets the fight
aside: everyone steps out with their place kept, sheets unlock and the room
is free. Later, `+combatstory/shelved` lists it and `+combatstory/unshelve
number` brings it back; everyone rejoins with `+combat/join`, then anyone uses
`+combatstory/resume`.

## Accessibility and NPCs

`+combat/auto on` explicitly enables automatic incoming reactions.
`+combat/act` requests one outgoing Auto-Act, useful whenever deciding an
action is burdensome. It never invents your RP, presses Burst or Empowers.
`+tactics/save Careful={"appetite":"cautious","rps_appetite":"balanced"}`
sets independent defensive risk and random RPS frequency. Auto-Act sees
public facts, never hidden opponent stats or planned reactions.

Use `/npc` to address a controlled NPC. Storytellers can enroll permitted
NPCs, attach templates and request one action per selected NPC, with public
controller attribution. No automation enrolls another PC.

All commands use labeled plain text. After reconnecting, `+combat` restores
your queue, `+combat/journal` lists transitions and
`+combat/result exchange` recovers committed outcomes without applying them
again. Human playtesting will tune these initial rules.
