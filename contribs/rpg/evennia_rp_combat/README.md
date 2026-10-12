# evennia-rp-combat

> **Preview (0.2.2, Pre-Alpha).** Pin an exact commit. Initial coefficients
> are a playtesting baseline; no human balance result is claimed.

Consent-based room combat for Evennia 6.x: personal turns, queued reactions,
freeform RP, durable Tactics and optional character sheets and NPCs. Combat
uses its own exact score mapping and resolver; it never changes ordinary
`+test` checks or grants XP. No character typeclass mixin is required.

## Install

Install `evennia-links` and `evennia-rp-rules` first, then this package. Add
`evennia_rp_combat` after those apps in `INSTALLED_APPS`, run
`evennia migrate --noinput`, and add `evennia_rp_combat.commands.CombatCmdSet`
to your character cmdset. Python 3.12 and Evennia 6.0.0 are the reference
runtime. See [the reference game](../../../example_game/README.md) for a
complete host configuration and seeded Proving Grounds.

Configure the kernel ruleset/subject adapter and `RP_COMBAT_ROLES`, mapping
attack, attack_defense, spell, spell_defense, dispirit, will and agility to
seven stat keys. Generic `DictStatSource`/`StatSource` inputs work without
chargen. A custom dotted `RP_COMBAT_SOURCE` may return an immutable
`evennia_rp_combat.data.Build` (or None to use the normal adapter).

Chargen 0.4 supplies playable sheets, equipped Abilities/Edge and revisioned
Signatures. Configure `RP_CHARGEN_MOVE_VALIDATOR` to
`evennia_rp_combat.integrations.validate_move` when combat is installed.
Its free authoring library remains usable without combat. NPCs use blueprint
stat blocks and permission-checked controllers, never PC sheets. Posing can
clear pose obligations; Scenes receives SYSTEM entries; all are optional.
Absent partners are checked through the app registry before importing them.

## Play

```text
+combat/setup practice
+combat/join one
+combat/join two                  (the second player)
+combat/attack opponent=balanced;rps=reaching
+combat/odds 2.1:1                (use the actual incoming token)
+combat/react 2.1:1=resist
+combat/posed
+combat/act
```

Every PC explicitly joins. Attacking an unenrolled character privately
invites them to join any side; refusal spends nothing, is not announced and
only tells the inviter. An ignore crossing prompts its owner privately.
`+combat/unignore character` explicitly removes the account-wide entry,
including alts/channel filtering, until manually restored. Ignore never
prevents unrelated members of the same fight from participating.

Resolve or cancel all incoming packets before your own next outgoing action.
Reactions remain available while an outgoing exchange or a pose is pending.
Each actor has a personal Turn Limit (default 4), with no global rounds.
Multiple targets share one draw; no result appears before every target has
accepted or canceled. Boss multipliers increase Vitality and per-turn action
allowances; any player may choose them, and every join announces the
resulting Vitality, Turn Limit and Boss Mode to the room. A Burst is one
exchange with at most three manually pressed hits.

`+combat/cancel token` works only before reaction acceptance, including an
automatic acceptance. It refunds unexecuted reservations without a turn tick.
Accepted results require staff `+combat/rollback sequence=reason`, restoring a
whole-fight checkpoint and changing pending tokens. The journal retains
superseded operations. Prose, XP and external ignore/build edits are not
rewound; external build differences pause recovery for reconciliation.

`+combat/journal` shows public transition summaries; `+combat/result exchange`
recovers committed public outcomes after reconnect. Each fight is a `Fight`
row; every mechanical write locks it, saves the new state and appends one
`FightEntry` (the state before, plus the result) in one transaction. History
is append-only, so nothing is rewritten however long the fight runs. Frozen
builds are stored once per fight in `FightBuild` and referenced by digest.
Service `operation_id` retries reuse the recorded result. Room delivery follows the
commit and is not a durable chat transport. Inspecting results never reapplies
damage. Private RPS and draws are excluded from pending policy/UI views.

Joining freezes a build (Abilities, Edge, stats, Signatures) for that fight,
and the sheet stays locked while the character is active in it, through
reload and ordinary chargen lock expiry. Clear queues, then use
`+combat/unlock reason` / `+combat/relock reason` for an announced correction.
A character is active in at most one fight at a time. Fade (and withdrawal)
releases the sheet: you may edit it or fight elsewhere, and `+combat/join`
later restores your exact place, including the build frozen for this fight,
and says so if your sheet has changed since. Fade retains resources and
assessment contributions; withdrawal counts remaining Vitality as lost.
Maintenance cancels only unaccepted packets and Fades safely, when you leave
the room or your connection is idle or disconnected for
`RP_COMBAT_IDLE_SECONDS` (default one hour); waiting for others' poses while
connected is not idleness. It never acts or reacts for an unwilling player.
When nobody is left active the fight pauses, and joining a paused fight says
so; anyone may then `+combatstory/resume`.
Vitality never drops below 0, and overkill neither deepens assessment loss
nor grants extra Transcendence. At 0 a participant is incapacitated: they
cannot act or accept a new reaction, and every attack they hadn't answered is
voided with a refund (a voided Burst opener refunds its ante; a later hit
ends the chain as a stop). Accepted reactions still resolve.

An ally may revive them with a Heal (`+combat/assist name=move`, one
incapacitated target). The offer waits in their queue until they
`+combat/accept` or `/decline` it; `+combat/revive accept` accepts allies'
revivals automatically, and `+combat/retract` withdraws an unaccepted offer.
Unresolved offers refund the healer. A Heal that restores nothing doesn't
revive. Revival is earned healing in the assessment, with the usual costs and
taper. The revived participant then takes `+combat/recover`: one action from
their allowance that ticks Poison and expires conditions once, with no
action rewards. Until then they can neither act nor be targeted. Medicine's
Treat on the reviving Heal may instead waive recovery (`;domain=medicine;waive`),
without cleansing. Someone revived after using their whole Turn Limit gets the
healing but cannot recover or act again, and is told so before accepting.

A withdrawn character, or anyone the table agrees to bring back OOC, returns
only after a visible `+combatstory/requestreturn name=Vitality;reason` and
their own `+combat/accept` (or `/decline`). That restored Vitality adds
exposure, so it never erases a side's earlier loss; turns, resources,
conditions and the frozen build are retained. A Faded participant at 0 may
rejoin, still incapacitated.

`+combatstory/shelve reason` sets a whole fight aside: unaccepted packets are
canceled with refunds, everyone Fades with their place retained, sheets
unlock and the room is free for other fights. `+combatstory/shelved` lists
shelved fights you took part in or that were set aside in your room;
`/unshelve number` brings one back to your room, where each participant
rejoins with `+combat/join` and anyone resumes.

## Automation and storytelling

`+tactics/save name=JSON` creates/selects a private preset. Defensive
`appetite` (cautious/balanced/bold) minimizes neutral expected loss with a
counter/reserve tradeoff. Independent `rps_appetite` makes uniform random
bets 0/35/75 percent of eligible Auto-Acts. Policies see own build and public
incoming facts or eligible public target Vitality, never hidden opponent
stats, reaction commitments, RPS bets or draws.

`+combat/auto on` explicitly enables incoming Auto-Resolve. `+combat/act`
explicitly requests one outgoing exchange, useful for accessibility as well
as NPCs. Neither enables a scheduler or creates RP poses. Auto-Act never
selects Burst or Empower. `front_first` falls back to random without Party.

`+combat` acts only as your own character (or, with `/npc`, the NPC you
control). `+combatstory` is the storyteller's toolbox, open to every player
and publicly attributed. Anyone may pause at any time. A storyteller change
to another player's character (Vitality, Spirit, conditions, a reduced
Turn Limit, a return) is a numbered request that player sees in `+combat` and
answers with `+combat/accept n` or `/decline n`; changes to NPCs you may
direct apply at once. `/end` needs every present, active player character's
agreement (the proposer's is implied); one decline withdraws it. A pause for
reconciliation after staff rollback is resumed by staff. NPC ownership and
control permissions still apply. `/template blueprint=side,boss,cap` attaches a
reusable template; `/act npc,npc` runs at most one action per permitted NPC in
stable order. Ordinary `/npc` combat switches address the controlled NPC,
leaving the controller's PC separate. Boss Checks and Party formation/cover
are not implemented in 0.1; nonempty Boss Check schedules are refused.

## Rules and integration

Default Vitality 100; Reserves start 3, cap 5; Spirit -10..20 (hundredths);
Transcendence 0..100. Executed standard attacks recover 2 Reserves. Specials
cost 1 plus their Effect count. Signature attack tiers total 2, improvised
ones total 1; Power/Accuracy each start at -2 minimum. Stances subtract
Accuracy and consume Effect/Reserve budget. Each distinct reaction Stance
can coexist: its next matching reaction gains 10 after an attack beats the
defense, or 2 when defended. Unused bonuses expire after the actor's next
own action. Strain reserves 5 Vitality per packet, leaving at least 1. Ward
absorbs the next harmful condition from someone else; Assist's
vulnerability and Burst's overextension are chosen costs and bypass it.

Successful Resist starts at 60 + .7 Defense + .3 Agility - 4 Accuracy - Spirit
percent. Its damage fraction starts .30 - .005 Defense, clamped .25..85.
Pressure gains rounded damage prevented (before overkill), capped 30. Each
pressure subtracts .5 chance points and adds .01 to the damage fraction;
completing your own exchange recovers 6. Failed Resist adds no pressure.
Evade, Overpower, RPS, support, Burst transfer/debt, Empower and conditions
use exact Fractions with half-up award boundaries. See
[the player guide](guides/combat.md) and arithmetic/state-machine tests.

`RP_COMBAT_DOMAIN_EFFECTS` maps host domain keys to the sixteen supported
behaviors in `engine.DOMAIN_ACTIONS`. `RP_COMBAT_ELEMENT_TRAITS` maps host
styles/elements to drain, spirit_loss, normalize, op_penalty,
penetrating_resist, spirit_gain, half_transcendence or dispel. Traits require
matching equipped Elemental Focus/combat-focus. Resistance/vulnerability
and ordinary domain/style tags never become a generic check bonus.
Pinpoint is dormant and Encore uses a single-target fallback without Party.

An equipped `domain-resistance` Ability blocks its domain's effect when it
works against its owner: riders on a hit or Dispirit target (Grapple, Pilfer,
Envenom, Provoke, Beguile, Misdirect, Analyze), Ambush for the defender, and
Slip Inside or Read against the countered or read attacker. It is checked
before Ward, so a Ward isn't spent on a blocked effect. Helpful effects
(Treat, Ward, Exhort, Encore, Endure) are never blocked. A blocked effect
still spends the exchange's single domain use and its surcharge.

Register `combat_bonus` as `evennia_rp_combat.modifiers.CombatEffect` in
`RP_RULES_EFFECT_KINDS` for validated, open, frozen passive specs. Fields are
restricted by phase: build (stat roles), declare (Power/Accuracy),
before_reaction (reaction bonus), before_resolution (tiers/reactions),
after_resolution (Spirit), exchange_end (recovery/Reserves/Transcendence).
Optional action filters and stack keys apply. These effects have no ordinary
check hooks and never receive a live opponent or hidden result.

Register `combat_rule` as `evennia_rp_combat.modifiers.CombatRule` for
conditional Abilities and Flaws: `{"kind": "combat_rule", "rule": "deflect",
"amount": "1/400", "per_level": "1/800"}`. Each rule's fields and bounds are
in `modifiers.RULES`, checked at every level; several entries for one rule
add up and are clamped again. Rules that change a defender's chances or
mitigation (`deflect`, `stoneskin`, `finesse`, `desperate_counter`) apply
inside `arithmetic.resolve`, so odds previews and Auto-Resolve use exactly
what resolution does. The engine applies `rps` (by bet, or every bet; negative
values make a Flaw), `calling_the_shot` (the `;public` option; only a public
bet ever reaches a reaction view), `tactician`, `measured_tempo`, `explosive`,
`flowing_guard`, `braced_support`, `taunting_opener`, `bait` and
`blood_price`. Charges return when a Burst never opens. Names, coefficients
and loadout costs belong to the host catalog.

Settings default to hidden: `RP_COMBAT_REVEALED`, `RP_COMBAT_FROZEN`,
`RP_COMBAT_TACTICS_REVEALED` are independent runtime switches. Other defaults:
`RP_COMBAT_TURN_LIMIT=4`, `RP_COMBAT_IDLE_SECONDS=3600` (connection idle; 0 disables idle Fade),
`RP_COMBAT_TACTICS_LIMIT=8`, `RP_COMBAT_NPC_MOVES={}` (stable move identifiers),
`RP_COMBAT_DOMAIN_EFFECTS={}`, `RP_COMBAT_ELEMENT_TRAITS={}`,
`RP_COMBAT_ELEMENT_KIND="style"`, `RP_COMBAT_STAFF_LOCK="cmd:perm(Builder)"`.
Five-rung score bases/factors and selected coefficients in `RP_COMBAT_RULES`
are configurable; Django checks reject invalid keys and bounds.

`membership_changed` is post-commit and includes character_id, fight_id,
status and actor_id. Companion emitters may pause from it. Mechanics carry
`type=rp_combat` message metadata for future reading-mode delivery; current
views are plain text with explicit labels and no color-dependent choices.
No web endpoints, rewards, PvP ownership, Party or Boss Check subsystem ships.
The included guide is discovered automatically by optional evennia-guides.

The [partner contract](PARTNERS.md) provides pure, registered declaration
modifiers, journaled partner state and plain-text status/help extensions.
State upgrades happen on load, including rollback, without rewriting old
snapshots or frozen builds. Uninstalled providers leave their data intact
and display an unavailable notice. This foundation does not install Party
or add revival, Boss Checks or new Ability mechanics.

## Verification

With dependencies and optional reference partners installed, run
`evennia test --settings test_settings.py evennia_rp_combat` from the reference
game with closed stdin. Confirm a positive `Ran N tests` line. The reference
seams are `world.sandbox.test_combat`; standalone absence profiles are
covered by `scripts/ci_run_combat_tests.py`. See
[MIGRATION_NOTES.md](MIGRATION_NOTES.md) before upgrading a populated game.
