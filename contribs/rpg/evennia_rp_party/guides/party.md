---
key: party
title: Party tactics
category: Playing together
requires: RP_PARTY_REVEALED
summary: Coordinate Formation, Cover, support and shared Synergy within a combat side.
---
A side says who is allied and owns the combat assessment. A Party is an
optional tactical team within that side. You can remain unpartied, form
several parties on one side, and move between them with clear queues.
There are no owners, formal roles or persistent organizations here.

## Getting together

Join combat explicitly first: `+combat/join side`. `+party/create name`
creates your team; `+party` lists identities and `+party/join identity`
joins one yourself. An invitation with `+party/invite character` can be
accepted or declined; it does not move anyone automatically. Use
`+party/leave` freely once incoming/outgoing exchanges are clear.

Any member may `+party/rename name`. `+party/dissolve` proposes dissolution;
members answer `+party/agree` or `+party/veto`. Each participating member
must agree. NPC controllers use `/as`. An empty or wholly unavailable party
can be cleaned up by any enrolled participant with `+party/dissolve identity`.
Dissolution waits for clear queues and leaves members in the fight unpartied.

## Position and Cover

Use `+party/formation front`, `back` or `flex`. Flex starts neutral. Front
protects the Back row of its own party. Back trades offensive accuracy for
protection while a Front remains available. Long-Range halves Formation
penalties. Incapacitated/recovering or unavailable Front members cannot protect.

Cover is a separate standing permission, off by default. Opt in with
`+party/formation back=on`; use `back=off` to withdraw it. Permission leaves
an unaccepted attack open for a same-party Front to Cover, suppressing your
automatic reaction for that packet while preserving your saved Auto-Resolve
choice. Without permission, Back uses ordinary automatic reactions.

A Front with clear queues can `+party/cover defender=token,resist` or
`token,overpower,counter`. Cover redirects and reacts atomically. The covered
hit keeps its original inputs; the coverer cannot Evade it. Pinpoint can
bypass Back protection and penalize the coverer's reaction, with each person's
own Domain Resistance checked separately. Cover can still rescue a teammate.

If the attack is a Burst, the rest of its chain now targets the coverer.
Later hits use fresh inputs. The attacker may stop after the covered hit.
Cover adds no action, draw or independent cost; normal reaction costs apply.
It cannot rewrite an accepted reaction or a partly accepted multi-target attack.

## Making support count

Party Damage Boost uses members' average Spirit plus Rally minus Rattle.
Ordinary support still works across parties and to unpartied allies. A
successful Assist/Heal adds Rally to the recipient's party; Dispirit adds
Rattle to the opponent's party. Different supporters contribute independently;
each owns one combined slot, replaced by their next qualifying support.

An entry ends on the supporter's next completed exchange or recovery. If
they have finished acting, it ends after the affected party's next completed
exchange. Fade suppresses an entry without restarting its duration. Boosts
freeze when an attack is declared, including each fresh Burst hit. They
affect outgoing damage; they do not multiply counters, Poison or healing.

Encore spreads reduced ordinary Assist Spirit across the named ally's
eligible party, including yourself if you belong. Each recipient has their
own repeat tracking. Heal/cleansing/revival stay on the named ally only.
Resistance does not block helpful Encore; unavailable/ignored incidental
recipients are skipped. An unpartied ally gets ordinary single-target support.

## Synergy and Team Surge

Your party earns Synergy by finishing exchanges (10), suffering actual
hostile damage (1/4 per Vitality), and executing an outgoing Empower (40
extra once per exchange). A Burst is one exchange. Recovery, cancellations,
self-costs, OOC corrections and joining grant none. The cap is 100 per
counted member, up to 500. A smaller active roster can clamp it; everybody
Fading freezes it for return. Moving never carries a share to another party.

Spend 100 with `+party/surge enemy=balanced` for +25% primary output against
one target. Use `+party/surge ally=assist` or `enemy=dispirit` for support;
a named Heal uses `+party/surge ally=move;action=assist`. Spell adds
`;action=spell`. Other ordinary options include `rps=bet`, `domain=key`,
`burst` and `empower`. On a multi-target action, `;target=name` selects the
boosted target; the first is the default. `+party/surgepress [empower]`
boosts the next Burst hit; further hits receive no carried-over Surge.
For an improvised Heal, use
`+party/surge/improv ally={"action":"assist","effects":["heal"]}`.
Other improvised moves use the same JSON as combat, with ordinary options
after it, such as `;empower` or `;burst;rps=subtle`.

It boosts damage or ordinary support Spirit/healing, with no Accuracy,
Reserve, extra action or target. Support Empower and Surge together give
1.75 times ordinary output; attack Empower keeps its normal tier benefits.
Encore boosts only the named recipient's primary output, while its other
recipients and domain riders keep ordinary strength. A covered packet keeps
its Surge against the coverer. Rally/Rattle, counters and Poison are not boosted.

Any member may spend; coordinate culturally. Each character gets one use
per personal turn, including across Boss allowances and party changes.
Declaration reserves both pool and use. A canceled boosted packet or
declined revival refunds it; an executed miss spends it. Other targets'
cancellations do not refund it. Refunds respect the current cap. Ordinary
Auto-Act never spends. `+party` shows available/reserved Synergy and your use.

## OOC coordination and continuity

`+party/chat message` routes private OOC to connected roster members in this
room, including downed allies. Ignore filters still apply. There is no saved
history, pose or RP credit; chat never enters fight state or rollback.

Party membership and permissions survive Fade, shelving and reload. A
revived ally awaiting recovery supplies no tactics until recovery completes.
Using up personal turns still permits ordinary defensive participation.
Moving parties never resets personal turns, support repeats or assessment.

The initial numbers are provisional playtest defaults. Pool, reservations
and use markers survive reload and rollback. Shelving normally cancels
unaccepted packets with refunds, while keeping pool and use history. Old parties start
earning at zero on upgrade. If Party is uninstalled, its modifiers switch
off and data stays saved; reinstalling settles executed/canceled reservations
without replaying rewards or results.

## Boss Checks

Checks are dramatic challenges offered by a boss's controller to named
Parties. They are optional storytelling beats with no automatic deadline.
One boss can challenge several raid Parties simultaneously; each squad has
its own progress and outcome. Boss Checks never target a whole side.

Use `+bosscheck Party=type` to issue, choosing Tank, DPS, Support, Pressure,
Special or Contest and an optional easy/balanced/hard difficulty. Issuance
costs no combat action. The boss should choose a surmountable challenge and
explain its stakes. `+bosscheck/preview id` shows progress and consequences;
`/resolve id=token` commits the preview. Warnings about uneven responses can
be acknowledged with a public reason, but committed exchanges must finish.
Combat status shows your own pending Check in full and summarizes finished
ones; `+combat/journal` keeps the full history.

The Party roster locks during a Check. Formation remains flexible, so Tank
is an opportunity to reorganize the Front and spread its mandatory Resist
damage. Every Front member must survive for the reward; only a complete
Front collapse adds party-wide failure damage. DPS counts the squad's direct
damage, including Burst hits and Overpower. Support measures final party
boost, including Rally/Rattle; Pressure measures boss Spirit at resolution.
Special uses an explicit requirement and helpful hint, interpreted generously.
The boss explicitly previews pass/fail and gives a public explanation when resolving.

`+bosscheck/withdraw id` cancels only your participation. You can remain in
the Party or leave once ordinary queues are clear; you cannot re-enter or
be replaced during that Check. `+bosscheck/cancel id` cancels the whole
Party instance. Neither applies failure damage or rewinds ordinary actions.
Committed consequences can only be rolled back through staff recovery.

Contest Checks declare allowed approaches and use one free
`+bosscheck/roll id=stat` per participant, from their frozen combat-era stats.
Individual failures take damage; enough successes earn group Backlash and
Stagger. Ordinary room tests do not count. Bosses may approve alternative
approaches before a roll, never after seeing it. Without the optional
Contest package, the other Check types still work.

Successful Checks open the boss to Bursts through Stagger: a substantial
reaction penalty and loss of the next entire personal turn. The boss may
finish a current partial turn. Its first executed action after the skipped
turn ends the opening. Several raid successes cannot stack or repeatedly
extend Stagger, but each Party keeps its own earned Backlash. Normal damage
still awards Transcendence/Synergy and contributes to combat assessment.
