# Party 0.1.1 Synergy calibration

Measured 2026-10-11 against combat 0.2.2's real pure engine. Reproduce with
`python scripts/calibrate_synergy.py` in the reference-game environment.
It writes JSON and changes no stored fights. Keep the provisional defaults:
100 per Surge, +25 primary-output percentage points, 10 per completed
exchange, 1/4 per actual hostile Vitality lost, and 40 extra once per
exchange containing an executed outgoing Empower. These are playtest
settings, with a significant small-team pacing limit described below.

## One selected packet

All 100 d100 draws are enumerated against neutral builds, without an RPS
bet. Attacks face Resist. Spirit starts at zero; one ordinary named target
receives the output. The outgoing actor's party starts with exactly 100
Synergy for this arithmetic comparison. Support rows use displayed Spirit;
Dispirit lists the mean loss including failures and the ordinary -10 cap.

| Action | Ordinary | With Surge | Relative change |
|---|---:|---:|---:|
| Attack or Spell | 10.20 damage | 13.40 damage | +31.37% |
| Empowered Attack or Spell | 16.64 damage | 21.04 damage | +26.44% |
| Assist | 4.00 Spirit | 5.00 Spirit | +25.00% |
| Empowered Assist | 6.00 Spirit | 7.00 Spirit | +16.67% |
| Dispirit | 3.90 Spirit lost | 4.875 Spirit lost | +25.00% |
| Empowered Dispirit | 5.85 Spirit lost | 6.50 Spirit lost | +11.11% |

The percentage-point bucket precedes mitigation and integer rounding, so
mean attack gains need not be exactly 25%. The empowered support baseline
is already 1.5 times ordinary output; adding Surge gives 1.75, rather than
1.875. Dispirit's recipient cap additionally limits realized output. Heal
uses the same ordinary support multiplier and normal healing taper/cap.

Resolver tests also cover empowered Heal plus Encore (primary 4.38 Spirit
and 26 healing at draw 100, incidental allies 3.75 Spirit and no healing),
unchanged five-point Rally/Rattle, a selected multi-target packet, Cover,
later Burst hits and a paid Surge in the Burst transfer basis. They verify
normal Measured Tempo, Explosive and recovery behavior. These are boundary
checks, not evidence of composition balance.

## Earning and opportunity

2,000 seeded encounters: five party sizes × two member Boss multipliers ×
two spending policies × 100 seeds. Each conscious member gets up to four
personal turns; Boss multiplier 3 therefore offers twelve actions per
member. The fixed scheduler is a sampling harness, not a global-round rule.
A neutral 500-Vitality foe replies after each action, within its normal
twenty-action cap. Everyone uses balanced Attack/Resist, with real Spirit,
damage, membership caps and personal-turn limits. No paid Empower, Heal,
revival or OOC resource correction occurs. Stop on ordinary unavailability.

The spending policy takes the first available legal Surge in offer order;
the comparison saves every point. Neither is an optimized policy.

| Members | Boss 1 mean executed actions | Boss 1 mean Surges | Boss 1 saved pool without spending | Boss 3 mean Surges |
|---|---:|---:|---:|---:|
| 1 | 4 | 0 | 50.68 | 1.00 |
| 2 | 8 | 0 | 102.18 | 2.03 |
| 3 | 12 | 1 | 154.13 | 3.91 |
| 5 | 20 | 2 | 257.29 | 3.90 |
| 8 | 32 | 3 | 375.90 | 3.91 |

At Boss multiplier 1, a three-member party's mean foe damage rises from
144.69 to 148.09, five members from 244.65 to 252.35, and eight from 412.50
to 424.66. At multiplier 3, the five/eight-member parties defeat the foe in
every sample under either policy; spending saves roughly one completed
attack on average (37.80 → 36.86 and 38.20 → 37.32). It grants no action.
Those encounter totals include unchanged non-Surged attacks, hence their
smaller overall gain than the isolated packet's.

**Small-team limit:** one member earns no spend in a normal four-turn fight;
two members generally reach 100 after their last available action. They
need earlier outgoing Empower, more real hostile loss enabled by healing,
or a longer allowance to use Surge. This is a clear pacing cost of retaining
100, not a claim that every party gets a moment in every scene. One
executed Empower's 40-point extra award brings the threshold four ordinary
exchange awards closer before cap effects, but this harness does not model
how quickly a build earns its 100 Transcendence.

The five-member cap bounds stored resources rather than award rate. Larger
parties can fund more one-target spends; unused Synergy also accumulates
when a foe has no actions left. Boss-scaled members have more actions and
Vitality, but still one Surge use per personal turn. The tests exercise
competing reservations, cap shrinkage and the entirely unavailable pool.

## Healing and continuity limits

A resolver scenario alternates earned Heal and ordinary Reserve-restoring
attacks while an opponent damages the healed ally. Pool gain is exactly
the six completed-exchange awards plus 1/4 of actual hostile loss, including
loss enabled by the healing. Setting Vitality OOC adds nothing. Declined
revival refunds Surge; accepted revival applies normal healing and requires
recovery, whose allowance/Poison tick awards nothing. These checks prevent
free entry/refund awards; they do not establish healing-loop balance.

Automated coverage includes cancellation versus miss, once-only rewards,
multi-target partial acceptance, Burst/Empower limits, party movement and
dissolution, frozen/absent/recovering/capped actors, reload, shelving and
staff rollback. Shelving uses combat's normal cancellation/refund rules.
Populated physical uninstall/reinstall checks settle executed and canceled
reservations without replaying damage or awards. A pending unexecuted
packet regains its frozen modifier after reinstalling. Ordinary-player live
commands earn 100 through ten exchanges, reserve across Server reload,
refund, execute, and refuse a second spend in the same personal turn.

## Playtest decision

Retain these settings as provisional. Three-to-eight-member parties obtain
occasional shared moments in these samples, without an extra exchange or
chain-wide bonus. For two-person scenes, consider a lower cost or higher
exchange award after human pacing feedback; do not describe the current
threshold as universally accessible. Support usefulness, different stat
spreads, optimized healing/revival loops, RPS preferences, and whether a
single-target output boost feels distinct from Empower still need human
playtesting. If the spend feels too similar, an extra-target spend remains
a separate future design decision. Boss Checks and ally Burst handoffs are
outside this point release.
