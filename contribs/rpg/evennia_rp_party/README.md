# evennia-rp-party

Optional tactical parties within a combat side. Preview release **0.2.0**;
Python 3.12+ and Evennia 6.0+. Combat 0.2.3+ is required for atomic resource
reservations and public transition notices. No new models, migrations or typeclass mixins.

## Install

Install `evennia-links`, `evennia-rp-rules`, `evennia-rp-combat`, then this
package. Append `evennia_rp_party` after combat in `INSTALLED_APPS`, add
`evennia_rp_party.commands.PartyCmdSet` to your character commands, and set:

```python
RP_PARTY_REVEALED = True
RP_PARTY_FROZEN = False
RP_COMBAT_PARTNERS = {
    "party": {"app": "evennia_rp_party", "provider": "evennia_rp_party.providers.PROVIDER"},
}
```

Merge this entry into any existing registry. Combat must also be revealed.
Commands and player enrollment do not require a persistent Group, owner or
formal role. Parties do not change sides, assessment denominators, personal
turns, build locks or existing consent. See `help +party` and the included
Party guide. `+party/.../as NPC=...` follows combat's NPC controller permissions.

## First release

Any enrolled participant may create/join/leave a party. Any member can
rename it. Dissolution waits for participating members' agreement; permitted
controllers agree for NPCs. Anyone enrolled can clean up an empty or wholly
unavailable party. All affected queues must be clear before dissolution.
Membership/Formation require clear incoming and outgoing exchanges; an owed
pose is harmless. Membership changes invalidate pending dissolution votes.
Invitations use stable identities and never move another character.

Front/Back/Flex starts at Flex. Back grants no Cover permission until its
player explicitly opts in. Cover atomically redirects and accepts Resist or
Overpower, keeps the original frozen packet and hands any remaining Burst
to the coverer. Later hits use fresh inputs against that Front.
The chain cannot be intercepted a second time, including after Formation
changes between hits. Clear coverer queues are required. Turn caps/owed
poses do not prevent defense.
Direct ignore crossings are checked without automatic unignore.

Formation penalties are 20 points for Front → protected Back, 20 for Back →
Front, and 40 for Back → protected Back. Flex/unpartied interactions are
neutral. With no eligible Front, the target's Back penalty disappears;
the attacker's own Back penalty remains. Long-Range halves these penalties.
Pinpoint bypasses the target's Back penalty, unless that target resists its
domain. A covering Front takes a separate 10-point penalty unless their own
build resists that domain. Long-Range never halves this Cover penalty.

Party boost uses signed average displayed Spirit, plus independent Rally
minus Rattle, then clamps to 0..30%. Each supporter has one combined slot
across the fight. A qualifying Assist/Heal Rallies the recipient's party;
Dispirit Rattles the opponent's party. Different supporters stack. Ordinary
Spirit output before resource caps qualifies; positive effective healing
also qualifies once. No rider on a failed/zero-effect/canceled operation.

Entries expire on the source's next completed exchange/recovery, replaced
by a newly earned entry afterward. A finished source's final entry expires
after the affected party's next completed exchange. Fade suppresses it and
does not restart clocks. Sources and affected parties must be available.
The boost affects outgoing Attack/Spell only, excluding counters, Poison,
self-damage and healing. Burst Spirit transfer uses pre-boost damage.

Encore spreads half-strength ordinary Assist Spirit to the primary target
and eligible party members, including the actor. It records repeats per
recipient. Healing, revival, cleansing, domain riders and paid Surge remain
primary-only. Domain Resistance never blocks this helpful effect. Incidental
recipients cost no extra actions/Reserves and do not receive revival.
An unpartied target uses ordinary single-target support. Unavailable and
ignored incidental recipients are skipped. Primary consent remains mandatory.

Incapacitated/recovering, Faded, absent, withdrawn and correction-unlocked
members retain their roster/position but supply no tactics. Exhausted
personal turn caps do not remove defensive participation. Eligibility uses
saved combat state, never live sessions. Declarations freeze their inputs.

## Synergy and Team Surge

Each party starts at zero Synergy. A completed personal exchange earns 10;
actual hostile Vitality loss earns 1/4 per point for the victim's party;
an outgoing exchange containing an executed Empower earns 40 extra once.
A Burst earns one completion award, with damage awards per hit and at most
one Empower award. Successful Overpower counterdamage rewards the actual
victim's party. Attributed hostile Poison on an ordinary own action also
earns on actual loss. Recovery, accepted reactions alone, cancellations,
self-costs, OOC corrections, joining and retries earn nothing. Recovery's
Poison tick earns nothing. Helpful healing/revival is not itself damage gain.

The cap is `100 × min(counted members, 5)`. Joining grants nothing and
contributions stay in their old party. With counted members, a shrinking
cap visibly clamps available Synergy after honoring pending reservations.
If everybody becomes unavailable, the retained balance freezes. Returning
clamps before spending; dissolution discards the balance. Exact fractions
are retained, so small hits do not lose their quarter-point awards.

`+party/surge enemy=balanced` spends 100 to add 25 percentage points to one
packet's primary output. The first named target is the default; a Boss can
use `+party/surge enemy,other=balanced;target=other`. Select support with
`+party/surge ally=assist`, a named Heal with `;action=assist`, or
`+party/surge enemy=dispirit`. `;action=spell` selects Spell. Attack options
`rps=...`, `domain=...`, `burst`, `empower`, `public` and revival `waive`
follow ordinary combat legality. `/as NPC=targets;move;options` directs a
permitted NPC. `+party/surgepress [empower]` buys the next hit of an open
Burst; ordinary `+combat/press` never carries the previous hit's Surge.
Use `+party/surge/improv names=JSON[;options]` for an improvised move,
including a Heal; JSON wording may contain semicolons. Example:
`+party/surge/improv ally={"action":"assist","effects":["heal"]};empower`.

Surge and Party Damage Boost add in one damage bucket after ordinary attack
Empower's Power/Accuracy tiers; Surge grants no Accuracy. Support Empower
plus Surge is 1.75 times ordinary output. Only the named target receives
Surge, including an Encore primary; additional Encore recipients, riders,
Rally/Rattle, counters and secondary packets are unchanged. Cover carries
the original packet's Surge to its actual victim. Burst transfer excludes
Party Damage Boost and includes the separately paid Surge.

Any member can spend without voting, once per personal turn, subject to
ordinary allowances/recovery and costs. The marker survives changing parties,
Fade, loadout corrections and cap changes; Boss allowances in one personal
turn share it. No Reserve, extra action or target is granted. Auto-Act never
spends. Announce intentions with party chat if useful.

Declaration atomically reserves the pool and use marker, before automatic
resolution. Cancellation of that selected packet before execution refunds
it and releases the marker; canceling another target does not. An executed
miss spends it. A declined revival Heal refunds it. Refunds obey the live
cap; pending reservations cannot make the available balance negative.
Reservations, outcomes and awards share combat's journal/rollback boundary.
Manual Boss Checks ship in 0.2; automatic Cover and ally Burst handoffs
remain future work.

## Manual Boss Checks

`+bosscheck Parties=type;difficulty=balanced` offers a narrative challenge
to named opposing Parties (IDs or exact names separated by commas). Types
are Tank, DPS, Support, Pressure, Special and optionally Contest. A Boss
Mode x2+ character issues between its exchanges without spending an action
or resource. One boss may simultaneously challenge multiple Parties; each
has an independent instance, cancellation and result. Each Party has at
most one pending Check across all bosses, and each boss may issue against
that cohort once per personal turn, even after cancellation/party recreation.
Whole sides and unpartied characters are not Check targets. Nothing
automatically issues or resolves a Check, including NPC Auto-Act/schedules.

Membership is locked while a Check is pending; Formation remains flexible.
`+bosscheck/withdraw id` cancels only your participation and permits departure
once ordinary queues are clear. `+bosscheck/cancel id` cancels your Party's
instance; the boss may also cancel. Neither needs a vote or applies failure
damage. Withdrawals cannot re-enter or be replaced during that Check. The
initial eligible cohort supplies the size; incapacitation/withdrawal reduces
it and recovery may restore an original member. Initially unavailable
members do not acquire obligations by recovering. No eligible targets means
suspend/cancel, never an automatic success. Committed consequences require
staff recovery; cancellation cannot refund an executed ordinary Surge or attack.

Use `/preview id` to inspect the current requirement, roster/progress,
potential damage and resolution token, then `/resolve id=token` to commit.
Changes invalidate the preview. Uneven/incomplete progress, missing Contest
responses and unreachable/already-met requirements warn; `;ack=public reason`
acknowledges warnings. Accepted unresolved exchanges cannot be bypassed.
Tank draws occur only on commitment. Special needs `;requirement=...;hint=...`
when issued and explicit `;pass` or `;fail` on preview and resolve. The
controller interprets roleplay generously; nobody's prose is machine-scored.
Special resolution requires `;ack=public explanation` for that judgment.

Tank distributes declared damage across the current Front, with automatic
ordinary Resist (physical, Accuracy/Spirit zero, no domain/element/RPS).
Every Front defender must survive for Backlash/Stagger. A partial casualty
fails without extra party damage; no Front or complete collapse adds the
failure wave to still-eligible targets. DPS counts actual direct damage
from cohort Attack/Spell/Burst hits and Overpower, excluding Poison,
outsiders, edits and Check Backlash. Support tests final Party boost including
Rally/Rattle; Pressure tests actual boss Spirit at resolution. Ordinary outside
support/debuffs can help those state-based tests. Other failed non-Contest
Checks inflict an unavoidable per-eligible-member failure wave.

Success Staggers the boss: a nonstacking reaction penalty and loss of the
next **whole personal turn**. Its current partial turn may finish. The
penalty remains until its first executed initiating action after the skipped
turn; a canceled action does not clear it. A final-cap boss retains the
opening until fight end. Skips grant no actions/resources/repeat resets.
Tank/Contest successes additionally inflict proportional Backlash. Real
damage feeds normal assessment, Transcendence and hostile-damage Synergy,
but Check Backlash never satisfies another DPS Check.

Install `evennia-rp-party[contest]` and add `evennia_rp_contest` to the host's
apps for Contest Checks. Declare `;approaches=stat,stat[/tag][;roll=rating]`.
`/roll id=stat[/tag]` is one free, bound response; `/allow id=member;stat[/tag]`
allows the boss to approve an alternative **before** rolling. Individual
failures take damage even if the quota is met; meeting it grants group
Backlash/Stagger, with no second party-wide failure wave. Missing responses
count as failures only after explicit warning acknowledgment. Ratings,
modifiers and ruleset identity freeze at enrollment/relock, and rolls remain
private audit records. Each issued Check retains that source even if a later
build correction relocks the participant. An upgraded pre-0.2 participant must explicitly
relock to acquire its Contest source. Contest absence disables only that
type; pending data remains available for resume/cancellation.
An older installed Contest package without the bound API also leaves the other
Check types and ordinary combat available; upgrade it before using Contest Checks.

Pause/shelving preserves pending Checks; a Faded boss suspends them, while
defeat/permanent withdrawal cancels them without consequences. Saved Check
state upgrades without history replay. Provider removal preserves data;
generic combat Fade/pause and staff recovery remain available. Reinstalling
does not backfill missed progress or replay damage. See the player guide and
[Check calibration](BOSS_CHECK_CALIBRATION.md) for defaults and limits.

## Configuration and lifecycle

These are provisional defaults for playtesting, not a balance guarantee:
See [calibration evidence and limits](CALIBRATION.md) for reproducible samples.
The point release adds [Synergy calibration](SYNERGY_CALIBRATION.md).

| Setting | Default | Units/bounds |
|---|---|---|
| `RP_PARTY_SPIRIT_COEFFICIENT` | `"1"` | percentage points per displayed Spirit, 0..100 |
| `RP_PARTY_SUPPORT_POINTS` | `"5"` | Rally/Rattle percentage points, 0..100 |
| `RP_PARTY_BOOST_CAP` | `"30"` | percentage points, 0..100 |
| `RP_PARTY_PINPOINT_PENALTY` | `"10"` | Cover reaction percentage points, 0..100 |
| `RP_PARTY_ENCORE_FACTOR` | `"1/2"` | ordinary Spirit fraction, 0..1 |
| `RP_PARTY_SURGE_COST` | `"100"` | Synergy, >0..500 |
| `RP_PARTY_SURGE_POINTS` | `"25"` | primary output percentage points, 0..100 |
| `RP_PARTY_EXCHANGE_SYNERGY` | `"10"` | points per completed exchange, 0..100 |
| `RP_PARTY_DAMAGE_SYNERGY` | `"1/4"` | points per actual hostile Vitality lost, 0..100 |
| `RP_PARTY_EMPOWER_SYNERGY` | `"40"` | extra points once per executed outgoing Empower exchange, 0..100 |
| `RP_PARTY_STAGGER_POINTS` | `"30"` | integer reaction percentage points, 0..100 |

`RP_PARTY_CHECK_PRESETS` may replace the complete easy/balanced/hard mapping
shown in [Check calibration](BOSS_CHECK_CALIBRATION.md). Each preset needs
`tank`, `dps`, `support`, `pressure`, `failure`, `backlash` and `fraction`.
Damage/boost fields are >0..1000, Pressure is -10..20 displayed Spirit,
and Backlash/Contest fractions are >0..1. Issued Checks retain their preset.

Use exact integer/rational strings; floats, booleans and nonfinite numbers
are rejected. `RP_PARTY_FROZEN` blocks new coordination; saved combat rules
continue. `RP_PARTY_REVEALED` hides commands; remove the provider registration
to disable its mechanical rules. Runtime settings follow evennia-links.

State is `fight.state["partners"]["party"]`, schema 3. Mechanical changes use
combat's Fight lock and append-only journal. Reload, shelving and rollback
keep party identities, positions, permissions and support. Ending archives
the data. No membership/resources cross fights. Removing the package while
a fight remains open preserves its section; combat disables its modifiers
and displays an unavailable notice. Reinstalling restores retained data and
stored modifiers; declarations made absent stay unmodified.
Support entries also retain personal-clock markers, so actions completed
while Party is absent do not restore an expired Rally/Rattle on reinstall.
Schema-1 parties upgrade with zero Synergy; earlier exchanges earn no
retroactive awards. If Party is absent, reserved packets execute without
its modifiers. Reinstalling settles their saved execution/cancellation
once, retaining spent markers or refunding unexecuted packets, with no
retroactive damage, output or earning. Pending unexecuted packets regain
their original frozen modifiers. Status projects settlement read-only;
the next committed operation journals any refund/cap notice.

`+party/chat` sends transient OOC only to connected roster members in the
room, with ignore filtering. It creates no channel, pose, RP credit, fight
entry or replayable state. It has no searchable history.

## Host API and tests

`rules` and `providers` read only saved state and exact host configuration.
All model/permission/ignore/presence work belongs to `services`. Host seeders
may use `rules.prepare(state, name, side)` inside `combat.services.execute`
to author an empty demonstration party without enrolling any PC.

Run `evennia test --settings test_settings.py evennia_rp_party` in an
initialized host, with closed stdin; verify a positive test count. The
reference game adds real sheet, NPC, guide and command seams. Acceptance
also covers combat with Party physically absent and Party without optional
combat partners. See `scripts/ci_run_party_tests.py`.
