# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Seeded Boss Check measurements through the real engine, without DB writes."""

import json
import os
import sys
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
from random import Random


def samples(trials=100):
    from django.test import override_settings
    from evennia_rp_combat import engine
    from evennia_rp_combat.data import Build, Move
    from evennia_rp_party import boss, rules

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
    performer = Build(neutral.scores, abilities=(("proficiency", "performance", 1),))
    registry = {
        "party": {"app": "evennia_rp_party", "provider": "evennia_rp_party.providers.PROVIDER"}
    }

    def setup(size, hp=100, encore=False):
        state = engine.new_state()
        engine.join(state, 1, "Boss", "boss", neutral, boss=max(2, size))
        for ident in range(2, size + 2):
            engine.join(state, ident, f"Member {ident}", "party", performer if encore else neutral)
            state["participants"][str(ident)]["hp"] = hp
        key = rules.create(state, 2, "Sample")
        for ident in range(3, size + 2):
            rules.join(state, ident, key)
        return state, key

    result = {
        "seed": 20261012,
        "trials_per_tank_case": trials,
        "tank": [],
        "dps": [],
        "support": [],
        "pressure": [],
    }
    rng = Random(20261012)
    with override_settings(RP_COMBAT_PARTNERS=registry):
        for size in (2, 3, 5, 8):
            for difficulty in ("easy", "balanced", "hard"):
                for hp in (100, 50):
                    for front_count in sorted({1, max(1, size // 2), size}):
                        outcomes = Counter()
                        for _ in range(trials):
                            state, key = setup(size, hp)
                            front = [str(i) for i in range(2, 2 + front_count)]
                            for ident in front:
                                rules.formation(state, ident, "front")
                            ident = boss.issue(state, 1, [key], "tank", difficulty=difficulty)[0]
                            view = boss.preview(state, ident)
                            outcome = boss.resolve(
                                state,
                                ident,
                                view["token"],
                                acknowledgment="Calibration response window",
                                draws={i: rng.randint(1, 100) for i in front},
                            )
                            outcomes["passed"] += outcome["passed"]
                            outcomes["collapse"] += outcome["collapse"]
                            outcomes["loss"] += sum(
                                (v["damage"] if isinstance(v, dict) else v)
                                for v in outcome["damage"].values()
                            )
                        result["tank"].append(
                            {
                                "size": size,
                                "difficulty": difficulty,
                                "hp": hp,
                                "front": front_count,
                                "pass_rate": outcomes["passed"] / trials,
                                "collapse_rate": outcomes["collapse"] / trials,
                                "mean_party_loss": outcomes["loss"] / trials,
                            }
                        )
            for cycles in (1, 2):
                for burst in (False, True):
                    passes = 0
                    for _ in range(trials):
                        state, key = setup(size)
                        ident = boss.issue(state, 1, [key], "dps")[0]
                        for _cycle in range(cycles):
                            for member in range(2, size + 2):
                                state["participants"][str(member)]["pose"] = False
                                ex = engine.declaration(
                                    state, member, [1], Move(), rng.randint(1, 100), burst=burst
                                )
                                engine.reaction(state, 1, f"{ex}:1", "resist")
                                for hit in (2, 3):
                                    exchange = state["exchanges"][ex]
                                    if exchange["phase"] != "press":
                                        break
                                    engine.press(state, member, rng.randint(1, 100))
                                    engine.reaction(state, 1, f"{ex}:{hit}", "resist")
                                if state["participants"]["1"]["hp"] <= 0:
                                    break
                            if state["participants"]["1"]["hp"] <= 0:
                                break
                        passes += sum(boss.get(state, ident)["damage"].values()) >= boss.required(
                            boss.get(state, ident), size
                        )
                    result["dps"].append(
                        {
                            "size": size,
                            "cycles": cycles,
                            "burst": burst,
                            "pass_rate": passes / trials,
                        }
                    )
            for supporters in (1, 2):
                for encore in (False, True):
                    for cycles in (1, 2):
                        boosts = []
                        for _ in range(trials):
                            state, key = setup(size, encore=encore)
                            for _cycle in range(cycles):
                                for member in range(2, 2 + min(size, supporters)):
                                    state["participants"][str(member)]["pose"] = False
                                    engine.declaration(
                                        state,
                                        member,
                                        [3 if member == 2 else 2],
                                        Move(action="assist"),
                                        rng.randint(1, 100),
                                        domain="performance" if encore else "",
                                        domain_effects={"performance": "encore"},
                                    )
                            boosts.append(float(rules.boost(state, key)))
                        result["support"].append(
                            {
                                "size": size,
                                "supporters": supporters,
                                "encore": encore,
                                "cycles": cycles,
                                "mean_boost": sum(boosts) / trials,
                                "balanced_pass_rate": sum(v >= 8 for v in boosts) / trials,
                            }
                        )
            for actions in (1, 2, 3):
                passes = 0
                for _ in range(trials):
                    state, key = setup(size)
                    for turn in range(actions):
                        member = 2 + turn % size
                        state["participants"][str(member)]["pose"] = False
                        engine.declaration(
                            state, member, [1], Move(action="dispirit"), rng.randint(1, 100)
                        )
                    passes += state["participants"]["1"]["spirit"] <= -300
                result["pressure"].append(
                    {"size": size, "actions": actions, "balanced_pass_rate": passes / trials}
                )
        # Enumerate every d100 for a single support response with resources
        # already earned. No free earning is implied by these starting states.
        result["resource_support"] = []
        for size in (2, 3, 5, 8):
            for encore in (False, True):
                for empowered in (False, True):
                    for surged in (False, True):
                        boosts = []
                        for draw in range(1, 101):
                            state, key = setup(size, encore=encore)
                            state["participants"]["2"]["transcendence"] = 100
                            rules.party(state, key)["synergy"] = "100"
                            engine.declaration(
                                state,
                                2,
                                [3],
                                Move(action="assist"),
                                draw,
                                empower=empowered,
                                domain="performance" if encore else "",
                                domain_effects={"performance": "encore"},
                                partner_requests={"party": {"kind": "surge", "target": "3"}}
                                if surged
                                else None,
                            )
                            boosts.append(float(rules.boost(state, key)))
                        result["resource_support"].append(
                            {
                                "size": size,
                                "encore": encore,
                                "empower": empowered,
                                "surge": surged,
                                "mean_boost": sum(boosts) / 100,
                                "balanced_pass_rate": sum(v >= 8 for v in boosts) / 100,
                            }
                        )
        from fractions import Fraction
        from math import comb

        from evennia_rp_rules.resolvers import Contest
        from evennia_rp_rules.ruleset import get_ruleset

        ruleset = get_ruleset()
        scale = next(iter(ruleset.stats.values())).scale
        rating = scale.parse(scale.rungs[len(scale.rungs) // 2].key)
        probability = ruleset.resolver.estimate(Contest(rating, rating)).success
        result["contest"] = []
        for size in (2, 3, 5, 8):
            for difficulty, profile in boss.DEFAULTS.items():
                quota = (size * Fraction(profile["fraction"])).__ceil__()
                chance = sum(
                    comb(size, k) * probability**k * (1 - probability) ** (size - k)
                    for k in range(quota, size + 1)
                )
                result["contest"].append(
                    {
                        "size": size,
                        "difficulty": difficulty,
                        "quota": quota,
                        "individual_pass_rate": float(probability),
                        "group_pass_rate": float(chance),
                    }
                )
    return result


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
