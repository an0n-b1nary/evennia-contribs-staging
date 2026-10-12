---
key: party
title: Party tactics
category: Playing together
requires: RP_PARTY_REVEALED
summary: Coordinate Formation, Cover and support within a combat side.
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

## OOC coordination and continuity

`+party/chat message` routes private OOC to connected roster members in this
room, including downed allies. Ignore filters still apply. There is no saved
history, pose or RP credit; chat never enters fight state or rollback.

Party membership and permissions survive Fade, shelving and reload. A
revived ally awaiting recovery supplies no tactics until recovery completes.
Using up personal turns still permits ordinary defensive participation.
Moving parties never resets personal turns, support repeats or assessment.

The initial numbers are provisional playtest defaults. Synergy/Team Surge
will follow after calibration; Boss Checks are planned for Party 0.2.
