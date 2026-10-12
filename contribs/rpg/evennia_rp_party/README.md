# evennia-rp-party

Optional tactical parties within a combat side. Preview release **0.1.0**;
Python 3.12+ and Evennia 6.0+. Combat 0.2.1+ is required for support spread
and recovery events. No new models, migrations or typeclass mixins.

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

Synergy/Team Surge is deferred to a point release for calibration. Boss
Checks remain future Party 0.2 work. No automatic Cover, shared resource
spending, extra actions or multi-target Burst is introduced.

## Configuration and lifecycle

These are provisional defaults for playtesting, not a balance guarantee:
See [calibration evidence and limits](CALIBRATION.md) for reproducible samples.

| Setting | Default | Units/bounds |
|---|---|---|
| `RP_PARTY_SPIRIT_COEFFICIENT` | `"1"` | percentage points per displayed Spirit, 0..100 |
| `RP_PARTY_SUPPORT_POINTS` | `"5"` | Rally/Rattle percentage points, 0..100 |
| `RP_PARTY_BOOST_CAP` | `"30"` | percentage points, 0..100 |
| `RP_PARTY_PINPOINT_PENALTY` | `"10"` | Cover reaction percentage points, 0..100 |
| `RP_PARTY_ENCORE_FACTOR` | `"1/2"` | ordinary Spirit fraction, 0..1 |

Use exact integer/rational strings; floats, booleans and nonfinite numbers
are rejected. `RP_PARTY_FROZEN` blocks new coordination; saved combat rules
continue. `RP_PARTY_REVEALED` hides commands; remove the provider registration
to disable its mechanical rules. Runtime settings follow evennia-links.

State is `fight.state["partners"]["party"]`, schema 1. Mechanical changes use
combat's Fight lock and append-only journal. Reload, shelving and rollback
keep party identities, positions, permissions and support. Ending archives
the data. No membership/resources cross fights. Removing the package while
a fight remains open preserves its section; combat disables its modifiers
and displays an unavailable notice. Reinstalling restores retained data and
stored modifiers; declarations made absent stay unmodified.
Support entries also retain personal-clock markers, so actions completed
while Party is absent do not restore an expired Rally/Rattle on reinstall.

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
