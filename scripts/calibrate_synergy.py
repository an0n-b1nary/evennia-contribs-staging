# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reproducible Team Surge output and earning samples; no database writes."""

import json
import os
import sys
from contextlib import redirect_stdout
from fractions import Fraction as F
from pathlib import Path
from random import Random


def samples():
    from django.test import override_settings
    from evennia_rp_combat import engine
    from evennia_rp_combat.data import Build, Move
    from evennia_rp_party import rules, synergy

    registry = {
        "party": {"app": "evennia_rp_party", "provider": "evennia_rp_party.providers.PROVIDER"}
    }
    neutral = Build(
        tuple(
            (role, "0")
            for role in (
                "attack",
                "attack_defense",
                "spell",
                "spell_defense",
                "dispirit",
                "will",
                "agility",
            )
        )
    )

    def team(size=3, boss=1):
        state = engine.new_state()
        for ident in range(1, size + 2):
            engine.join(
                state,
                ident,
                f"Sample {ident}",
                "one" if ident <= size else "two",
                neutral,
                boss=boss if ident <= size else 5,
            )
        key = rules.create(state, 1, "Sample team")
        for ident in range(2, size + 1):
            rules.join(state, ident, key)
        return state, key, size + 1

    output = []
    earning = []
    with override_settings(RP_COMBAT_PARTNERS=registry):
        # Enumerate every d100. Empower is the real tier/multiplier behavior.
        for action in ("attack", "spell", "assist", "dispirit"):
            for empowered in (False, True):
                totals = [F(0), F(0)]
                for boosted in (False, True):
                    for roll in range(1, 101):
                        state, key, foe = team()
                        actor = state["participants"]["1"]
                        actor["transcendence"] = 100
                        target = 2 if action == "assist" else foe
                        state["participants"][str(target)]["hp"] = 50
                        rules.party(state, key)["synergy"] = "100"
                        request = (
                            {"party": {"kind": "surge", "target": str(target)}} if boosted else None
                        )
                        ex = engine.declaration(
                            state,
                            1,
                            (target,),
                            Move(action=action),
                            roll,
                            empower=empowered,
                            partner_requests=request,
                        )
                        if action in ("attack", "spell"):
                            engine.reaction(state, target, f"{ex}:1", "resist")
                        outcome = state["exchanges"][ex]["outcomes"][0]
                        totals[int(boosted)] += F(
                            outcome.get("damage", abs(outcome.get("spirit", 0))), 100
                        )
                output.append(
                    {
                        "action": action,
                        "empower": empowered,
                        "ordinary_mean": str(totals[0]),
                        "surge_mean": str(totals[1]),
                        "relative_gain": str(totals[1] / totals[0] - 1),
                    }
                )
        # Fixed offer order is a harness, not a global-round game mechanic.
        # Four personal turns each, shared pool from zero, one foe reply per
        # ally action; no paid Empower, healing or revival. Stop unavailable
        # actors; preserve real Spirit, caps and damage through each run.
        for size in (1, 2, 3, 5, 8):
            for boss in (1, 3):
                for spending in (False, True):
                    results = []
                    for seed in range(100):
                        rng = Random(seed)
                        state, key, foe = team(size, boss)
                        used = 0
                        total_actions = 0
                        for _cycle in range(4 * boss):
                            for ident in range(1, size + 1):
                                actor = state["participants"][str(ident)]
                                enemy = state["participants"][str(foe)]
                                if (
                                    not engine.participating(actor)
                                    or actor["turns"] >= actor["turn_limit"]
                                    or not engine.participating(enemy)
                                ):
                                    continue
                                actor["pose"] = False
                                eligible = not any(
                                    row["actor"] == str(ident)
                                    and row["turn"] == actor["turns"]
                                    and row["status"] != "refunded"
                                    for row in rules.data(state)["surges"].values()
                                )
                                spend = (
                                    spending and eligible and synergy.available(state, key) >= 100
                                )
                                request = (
                                    {"party": {"kind": "surge", "target": str(foe)}}
                                    if spend
                                    else None
                                )
                                ex = engine.declaration(
                                    state,
                                    ident,
                                    (foe,),
                                    Move(),
                                    rng.randint(1, 100),
                                    partner_requests=request,
                                )
                                engine.reaction(state, foe, f"{ex}:1", "resist")
                                total_actions += 1
                                used += int(spend)
                                enemy = state["participants"][str(foe)]
                                if (
                                    engine.participating(enemy)
                                    and enemy["turns"] < enemy["turn_limit"]
                                ):
                                    enemy["pose"] = False
                                    ex = engine.declaration(
                                        state, foe, (ident,), Move(), rng.randint(1, 100)
                                    )
                                    engine.reaction(state, ident, f"{ex}:1", "resist")
                        results.append(
                            {
                                "spent": used,
                                "pool": synergy.pool(state, key),
                                "actions": total_actions,
                                "foe_loss": 500 - state["participants"][str(foe)]["hp"],
                            }
                        )
                    earning.append(
                        {
                            "members": size,
                            "boss_multiplier": boss,
                            "spending": spending,
                            **{
                                name: str(
                                    sum((F(row[name]) for row in results), F(0)) / len(results)
                                )
                                for name in results[0]
                            },
                        }
                    )
    return {"output": output, "earning": earning, "encounters": 2000}


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "example_game"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.conf.test_settings")
    import django

    with redirect_stdout(sys.stderr):
        django.setup()
    print(json.dumps(samples(), indent=2))


if __name__ == "__main__":
    main()
