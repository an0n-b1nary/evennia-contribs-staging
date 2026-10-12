# Party 0.1 provisional calibration

Measured 2026-10-11 using combat 0.2.1 and the real pure engine. Reproduce
with `python scripts/calibrate_party.py` in the reference-game environment.
The simulation never loads or changes a stored fight. The script emits JSON; arithmetic uses
exact fractions, with decimal rounding only in the sustained-run report.

Retain the initial playtesting defaults: Spirit coefficient 1, Rally/Rattle
5 percentage points, boost cap 30%, Pinpoint Cover penalty 10 points, and
Encore Spirit strength one-half. These are provisional host settings, not
an established balance result. Party 0.1.0 deferred Synergy; the point
release's separate [Synergy samples and limits](SYNERGY_CALIBRATION.md)
cover its earning and one-packet output.

## Encore and party size

One neutral participant Assists another at draw 50, with all members at
zero Spirit. Encore uses Performance expertise and its ordinary surcharge.
Formation is Flex. The damage column enumerates all 100 draws for each
member's next balanced Attack against a neutral Resisting opponent; it is
an arithmetic sample, not a legal simultaneous team action or extra turn.

| Members | Assist / Encore total Spirit | Assist / Encore boost | Assist / Encore expected team damage |
|---|---|---|---|
| 2 | 3.99 / 4 | 6.995% / 7% | 22.92 / 22.92 |
| 3 | 3.99 / 6 | 6.33% / 7% | 34.12 / 34.38 |
| 5 | 3.99 / 10 | 5.798% / 7% | 56.52 / 57.30 |
| 8 | 3.99 / 16 | 5.499% / 7% | 90.12 / 91.68 |

Encore's total Spirit grows with its recipients. Its average contribution
stays approximately two points in this sample; the shared damage multiplier
does not grow linearly with party size. Ordinary Assist concentrates Spirit
on one character, while Encore spreads it and includes its own actor. The
small two-member difference comes from award rounding. Further actions use
each recipient's repeat history, and the normal Spirit and boost caps still
apply. Large-party accuracy benefits and coordinated focus fire need human
assessment even though this immediate damage sample is bounded.

## Sustained action budgets

The harness offers three allies four actions each against one boss with
three actions per personal turn and 300 Vitality. A fixed scheduling cycle
is only a test fixture, never a combat round. Each case uses seeds 0..99;
all attacks face Resist. Neutral builds have zero scores. Mixed builds use
Attack 20 for attackers, Attack 5/Dispirit 20 for support specialists, and
defensive scores 10/Agility 5. Everyone remains Flex.

The full-support policy Assists every action, healing an injured other ally
when affordable. Encore uses its surcharge whenever affordable, including
at full Vitality. The alternating policy replaces every other support action
with an ordinary Attack. It can replenish Reserves for later healing. These
are deliberately simple strategies, not optimal play. An alternate boss
policy replaces every other Attack with Dispirit; compare compositions
within a policy because it also changes the number of damaging attacks.

Full-support examples against the Attack-only boss:

| Builds | Supporters | Mode | Damage dealt | Healing | Ally assessment | Boss assessment |
|---|---|---|---|---|---|---|
| Neutral | 0 | Attack | 145.60 | 0 | .523 | .515 |
| Neutral | 1 | Assist | 101.09 | 9.57 | .536 | .663 |
| Neutral | 2 | Assist | 50.23 | 21.74 | .554 | .833 |
| Neutral | 1 | Encore | 99.90 | 0 | .504 | .667 |
| Neutral | 2 | Encore | 50.98 | 0 | .482 | .830 |
| Mixed | 0 | Attack | 167.77 | 0 | .463 | .441 |
| Mixed | 1 | Assist | 115.75 | 11.09 | .477 | .614 |
| Mixed | 2 | Assist | 55.24 | 28.48 | .509 | .816 |
| Mixed | 1 | Encore | 114.56 | 0 | .440 | .618 |
| Mixed | 2 | Encore | 57.57 | 0 | .414 | .808 |

Assessment is each side's retained Vitality fraction; higher is better for
that side. A second supporter provides independent Rally and additional
healing, but replacing two of three attackers with constant Assist loses
substantial damage. Blindly buying Encore can spend the healing budget
before anyone is injured. These results do **not** establish parity for
permanent support-only play. They favor selective support and make Reserve
management a concrete playtesting concern. Raising a coefficient alone
would not establish balanced compositions across different party sizes.

Alternating support and Attack, against the same Attack-only boss:

| Builds | Supporters | Mode | Damage dealt | Healing | Ally assessment | Boss assessment |
|---|---|---|---|---|---|---|
| Neutral | 1 | Assist | 126.00 | 12.33 | .553 | .580 |
| Neutral | 2 | Assist | 104.34 | 26.37 | .587 | .652 |
| Neutral | 1 | Encore | 125.93 | 12.58 | .554 | .580 |
| Neutral | 2 | Encore | 106.41 | 26.28 | .587 | .645 |
| Mixed | 1 | Assist | 137.54 | 17.91 | .510 | .542 |
| Mixed | 2 | Assist | 102.72 | 40.64 | .571 | .658 |
| Mixed | 1 | Encore | 137.90 | 18.78 | .513 | .540 |
| Mixed | 2 | Encore | 107.48 | 40.34 | .570 | .642 |

The second supporter adds real healing and its own Rally, with an offensive
tradeoff. Encore has a modest additional offensive effect in these samples;
it is not a substitute for healing. Against repeated Dispirit, the neutral
alternating Encore cases deal 131.61/111.72 damage and heal 11.61/21.73 for
one/two supporters; the mixed cases deal 141.94/111.72 and heal 15.99/29.21.
These runs still favor direct attackers in the net side comparison. The
defaults therefore remain a cautious baseline, with support-heavy parity
unproven. Test larger teams, selective healing, stronger support Signatures,
other reactions and deliberate timing before deciding on a numerical change.

## Interception and release checks

The separate Cover sample uses neutral Front attackers and Front coverers
protecting a Back ally. It enumerates original-target and coverer Domain
Resistance independently. The original Formation snapshot survives the
handoff; Pinpoint's Cover penalty stays separate. RPS bets and defensive
Abilities can shift these chances, so a ten-point penalty never guarantees
an attack or disables Cover.

| Pinpoint | Original resists | Coverer resists | Resist | Overpower |
|---|---|---|---|---|
| No | No | No | 80% | 65% |
| Yes | No | No | 50% | 35% |
| Yes | Yes | No | 70% | 55% |
| Yes | No | Yes | 60% | 45% |
| Yes | Yes | Yes | 80% | 65% |

Automated coverage additionally checks independent supporter slots, signed
Spirit/clamping, final-action expiry, repeat tracking, recovery, frozen
inputs, unboosted Burst transfer, helpful Encore with Domain Resistance,
primary-only healing, Calling the Shot previews, Measured Tempo/Taunting
Opener and Bait/Blood Price, and atomic failed interceptions. A Burst cannot
be handed off twice even after a Formation change between hits.

The ordinary-player localhost rehearsal exercises Party creation/invitation,
Formation, standing Cover alongside Auto-Resolve, Cover odds/acceptance,
support, private chat, Fade/rejoin and agreement to dissolve. Automated
command execution establishes operability; human pacing, support usefulness
and team-up feel remain open playtesting questions.
