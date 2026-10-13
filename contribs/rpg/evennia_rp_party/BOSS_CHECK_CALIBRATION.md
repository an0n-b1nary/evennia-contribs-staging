# Boss Check calibration (0.2.0)

These are provisional storytelling presets. A controller chooses a response
window and a challenge the actual squad can overcome, previews the current
stakes, and deliberately resolves. There is no automatic deadline or promise
that every composition passes every preset.

| Preset | Tank damage per eligible member | DPS direct damage per member | Final Support boost | Boss Spirit at most | Failure damage per eligible member | Contest successes |
|---|---:|---:|---:|---:|---:|---|
| easy | 24 | 12 | 5% | -1 | 8 | ceil(n/4) |
| balanced | 35 | 18 | 8% | -3 | 12 | ceil(n/2) |
| hard | 45 | 24 | 12% | -6 | 16 | ceil(3n/4) |

Tank divides its total across eligible Front defenders before ordinary Resist.
Every Front defender must survive for success. Partial casualties fail without
an extra wave; complete collapse adds failure damage only to survivors still
eligible. Tank Backlash is ceil(total declared Tank damage / 2). Contest
Backlash is ceil(n × that preset's Tank value / 2), independent of individual
roll margins. Contest damages individual failures even on group success,
with no second failure wave. Other successful Check types grant Stagger alone.

All successes grant one nonstacking next-full-turn skip and a **30-point**
reaction chance penalty. Evade, Resist and Overpower share it; mitigation
fractions stay ordinary. Already Staggered bosses receive no additional skip
or refreshed opening. The final-cap opening persists until fight end.

`RP_PARTY_CHECK_PRESETS` accepts a full replacement mapping. Its keys are
`easy`, `balanced`, `hard`; each contains exact strings for `tank`, `dps`,
`support`, `pressure`, `failure`, `backlash` (`"1/2"`) and `fraction`
(`"1/4"`, `"1/2"`, `"3/4"`). `RP_PARTY_STAGGER_POINTS` sets the integer
reaction penalty. Issuance freezes the preset; ordinary core and Party tuning
still apply to combat at resolution. A Check's `value` option overrides its
requirement, not the preset's failure damage or Backlash fraction.

## Reproduction and measurements

With the reference game's dependencies installed, run:

```sh
python scripts/calibrate_boss_checks.py > boss-check-samples.json
```

The script uses seed **20261012**, 100 trials per sampled scenario, Party
sizes **2, 3, 5, 8**, neutral equal-stat builds, ordinary Resist, actual combat
packets and the Party provider. Tank samples include **100 and 50 Vitality**,
one/approximately half/all members in Front, and all difficulties. Support
compares one/two supporters and ordinary/Encore output. Resource-funded
support enumerates every d100 with the stated resources already earned.
Contest quotas use exact binomial probabilities from the configured kernel's
middle-rating versus middle-difficulty odds, with independent rolls.

Representative results from the reference ruleset:

| Scenario | Result |
|---|---|
| Five members, balanced Tank, 100 Vitality, one Front | 63% success; 37% collapse |
| Same, two Front | 100% success; mean total party loss 101.18 |
| Five members, balanced Tank, 50 Vitality, one Front | 0% success; mean loss 98 including collapse wave |
| Same, two Front | 33% success; 15% collapse |
| Same, all five Front | 100% success; mean loss 103.72 |
| Balanced DPS, one ordinary attack cycle | 0–15% success across sampled sizes |
| Balanced DPS, two ordinary attack cycles | 94–100% success |
| Balanced DPS, one cycle using Burst | 100% reached the quota |
| Five members, one ordinary supporter, one response | Mean boost 5.80%; 0% meet balanced 8% |
| Same, one Encore supporter | Mean boost 7.01%; 0% meet 8% |
| Same, two ordinary supporters | Mean boost 11.68%; 100% meet 8% |
| Same, one Empowered Encore | Mean boost 8.00%; 50% meet 8% |
| Same, one Empowered Encore with Team Surge | Mean boost 8.10%; 56% meet 8% |
| Balanced Pressure, one neutral Dispirit response | 60–70% success |
| Balanced Pressure, three responses | 92–96% success |
| Five equal-rating Contest responders | 81.87% easy; 50.94% balanced; 19.38% hard |

These results support retaining the presets as initial defaults: Formation
redistributes Tank risk, a DPS response window matters, distinct supporters
remain useful, and a single resource-funded supporter can reach balanced
Support without making a second supporter redundant. Easy Support is a
reasonable choice for a squad with one ordinary supporter. Hard Contest is
deliberately demanding at equal ratings; authored roll difficulty and permitted
approaches should reflect the squad's strengths.

This is arithmetic and state-machine evidence, not a full encounter playtest.
It does not model optimized builds, healing between every packet, adversarial
boss tactics, all domain/Ability combinations, or correlated roleplay choices.
DPS samples measure reaching the direct-damage quota; defeating the boss can
cancel the instance before a separate Check resolution. Small-sample rates
are descriptive, not precision balance estimates. Raid nonstacking, cohort
changes, cancellation, idempotency, stale previews and provider removal are
verified by regression tests rather than these balance samples.
