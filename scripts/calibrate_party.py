# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Measure provisional Party defaults through the installed engine (no DB writes).

Run with the sandbox environment: python scripts/calibrate_party.py.
This reports arithmetic samples, not human balance or pacing evidence.
"""

import json
import os
import sys
from contextlib import redirect_stdout
from fractions import Fraction as F
from pathlib import Path
from random import Random


def samples():
    from django.test import override_settings
    from evennia_rp_combat import arithmetic, engine
    from evennia_rp_combat.data import Build, Move
    from evennia_rp_party import rules

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
    performer = Build(neutral.scores, abilities=(("proficiency", "performance", 1),))
    results = []
    with override_settings(RP_COMBAT_PARTNERS=registry):
        for size in (2, 3, 5, 8):
            for encore in (False, True):
                state = engine.new_state()
                for ident in range(1, size + 2):
                    engine.join(
                        state,
                        ident,
                        f"Sample {ident}",
                        "allies" if ident <= size else "foe",
                        performer if ident == 2 else neutral,
                    )
                key = rules.create(state, 1, "Sample party")
                for ident in range(2, size + 1):
                    rules.join(state, ident, key)
                engine.declaration(
                    state,
                    2,
                    (1,),
                    Move(action="assist"),
                    50,
                    domain="performance" if encore else "",
                    domain_effects={"performance": "encore"},
                )
                expected = F(0)
                for ident in range(1, size + 1):
                    actor = state["participants"][str(ident)]
                    for roll in range(1, 101):
                        expected += F(
                            arithmetic.resolve(
                                Build.from_dict(actor["build"]),
                                neutral,
                                Move(),
                                "resist",
                                roll,
                                spirit=actor["spirit"],
                                damage_boost=rules.boost(state, key),
                            ).damage,
                            100,
                        )
                results.append(
                    {
                        "members": size,
                        "support": "Encore" if encore else "Assist",
                        "total_spirit": str(
                            F(
                                sum(
                                    state["participants"][str(ident)]["spirit"]
                                    for ident in range(1, size + 1)
                                ),
                                100,
                            )
                        ),
                        "boost_percent": str(rules.boost(state, key)),
                        "expected_team_damage": str(expected),
                    }
                )
    return results


def sustained(seeds=100, *, alternating=False):
    """Fixed scheduling harness, not a global-round rule or optimal strategy.

    Each of four cycles offers every ally one action, then the boss three.
    A support specialist heals an injured other ally when affordable;
    otherwise they Assist. The alternating policy attacks on odd cycles
    instead. Encore is used only with its Reserve surcharge.
    Boss pressure alternates Dispirit and Attack when requested. Everyone
    Resists attacks. No targets, resources or allowances are fabricated.
    """
    from django.test import override_settings
    from evennia_rp_combat import engine
    from evennia_rp_combat.data import Build, Move
    from evennia_rp_party import rules

    roles = ("attack", "attack_defense", "spell", "spell_defense", "dispirit", "will", "agility")
    registry = {
        "party": {"app": "evennia_rp_party", "provider": "evennia_rp_party.providers.PROVIDER"}
    }
    rows = []
    with override_settings(RP_COMBAT_PARTNERS=registry):
        for mixed in (False, True):
            for count, encore in ((0, False), (1, False), (2, False), (1, True), (2, True)):
                for pressure in (False, True):
                    totals = {
                        key: F(0)
                        for key in (
                            "damage",
                            "healing",
                            "ally_vitality",
                            "foe_vitality",
                            "support_actions",
                        )
                    }
                    for seed in range(seeds):
                        rng = Random(seed)
                        state = engine.new_state()
                        for ident in (1, 2, 3, 4):
                            supporter = ident <= count
                            scores = {role: 0 for role in roles}
                            if mixed:
                                scores.update(
                                    attack=5 if supporter else 20,
                                    dispirit=20 if supporter else 0,
                                    attack_defense=10,
                                    will=10,
                                    agility=5,
                                )
                            frozen = Build(
                                tuple((role, str(scores[role])) for role in roles),
                                abilities=(("proficiency", "performance", 1),) if supporter else (),
                            )
                            engine.join(
                                state,
                                ident,
                                f"Sample {ident}",
                                "allies" if ident < 4 else "foe",
                                frozen,
                                boss=3 if ident == 4 else 1,
                                auto=True,
                            )
                        key = rules.create(state, 1, "Allies")
                        rules.join(state, 2, key)
                        rules.join(state, 3, key)
                        rules.create(state, 4, "Boss")

                        def act(
                            actor, target, move, domain="", *, state=state, rng=rng, totals=totals
                        ):
                            exchange_id = engine.declaration(
                                state,
                                actor,
                                (target,),
                                move,
                                rng.randint(1, 100),
                                domain=domain,
                                domain_effects={"performance": "encore"},
                            )
                            exchange = state["exchanges"][exchange_id]
                            if exchange["phase"] == "waiting":
                                engine.reaction(state, target, f"{exchange_id}:1", "resist")
                            for outcome in exchange["outcomes"]:
                                if actor < 4:
                                    totals["damage"] += outcome.get("damage", 0)
                                    totals["healing"] += outcome.get("healing", 0)
                            if actor < 4 and move.action == "assist":
                                totals["support_actions"] += 1

                        for cycle in range(4):
                            for ident in (1, 2, 3):
                                actor = state["participants"][str(ident)]
                                if not engine.participating(actor) or not engine.participating(
                                    state["participants"]["4"]
                                ):
                                    continue
                                if ident <= count and not (alternating and cycle % 2):
                                    others = [
                                        row
                                        for row in state["participants"].values()
                                        if row["side"] == "allies"
                                        and row["id"] != str(ident)
                                        and engine.participating(row)
                                    ]
                                    if others:
                                        target = min(others, key=lambda row: row["hp"])
                                        domain = (
                                            "performance" if encore and actor["reserves"] else ""
                                        )
                                        heal = target["hp"] < target["max_hp"] and actor[
                                            "reserves"
                                        ] >= 2 + bool(domain)
                                        move = (
                                            Move(
                                                action="assist",
                                                kind="improvised",
                                                effects=("heal",),
                                            )
                                            if heal
                                            else Move(action="assist")
                                        )
                                        act(ident, int(target["id"]), move, domain)
                                        continue
                                act(ident, 4, Move())
                            for offset in range(3):
                                boss = state["participants"]["4"]
                                targets = [
                                    ident
                                    for ident in (1, 2, 3)
                                    if engine.participating(state["participants"][str(ident)])
                                ]
                                if not engine.participating(boss) or not targets:
                                    break
                                target = targets[(cycle + offset) % len(targets)]
                                action = (
                                    "dispirit"
                                    if pressure and (cycle * 3 + offset) % 2 == 0
                                    else "attack"
                                )
                                act(4, target, Move(action=action))
                        assessment = engine.assessment(state)
                        totals["ally_vitality"] += F(assessment["allies"])
                        totals["foe_vitality"] += F(assessment["foe"])
                    rows.append(
                        {
                            "builds": "mixed" if mixed else "neutral",
                            "policy": "alternating" if alternating else "full support",
                            "supporters": count,
                            "support": "Encore" if encore else "Assist",
                            "boss": "Attack/Dispirit" if pressure else "Attack",
                            "seeds": seeds,
                            **{
                                key: round(float(value / seeds), 3) for key, value in totals.items()
                            },
                        }
                    )
    return rows


def cover_samples():
    from django.test import override_settings
    from evennia_rp_combat import arithmetic, engine
    from evennia_rp_combat.data import Build, Move
    from evennia_rp_party import rules

    roles = ("attack", "attack_defense", "spell", "spell_defense", "dispirit", "will", "agility")
    scores = tuple((role, "0") for role in roles)
    neutral = Build(scores)
    registry = {
        "party": {"app": "evennia_rp_party", "provider": "evennia_rp_party.providers.PROVIDER"}
    }
    result = []
    with override_settings(RP_COMBAT_PARTNERS=registry):
        for pinpoint, original_resists, coverer_resists in (
            (False, False, False),
            (True, False, False),
            (True, True, False),
            (True, False, True),
            (True, True, True),
        ):
            state = engine.new_state()
            for ident in (1, 2, 3):
                abilities = (
                    (("proficiency", "aim", 1),)
                    if ident == 1
                    else (("domain-resistance", "aim", 1),)
                    if (ident == 2 and original_resists) or (ident == 3 and coverer_resists)
                    else ()
                )
                engine.join(
                    state,
                    ident,
                    f"Sample {ident}",
                    "attackers" if ident == 1 else "defenders",
                    Build(scores, abilities=abilities),
                )
            rules.create(state, 1, "Attackers")
            rules.formation(state, 1, "front")
            key = rules.create(state, 2, "Defenders")
            rules.join(state, 3, key)
            rules.formation(state, 2, "back", cover=True)
            rules.formation(state, 3, "front")
            exchange = engine.declaration(
                state,
                1,
                (2,),
                Move(),
                50,
                domain="aim" if pinpoint else "",
                domain_effects={"aim": "pinpoint"},
            )
            view = engine.interception_view(
                state,
                f"{exchange}:1",
                2,
                3,
                reaction_penalty=10 if pinpoint and not coverer_resists else 0,
            )
            chances = {
                reaction: arithmetic.resolve(
                    neutral,
                    view.build,
                    Move(),
                    reaction,
                    1,
                    bonus=F(dict(view.bonuses)[reaction]),
                    penalty=F(dict(view.penalties)[reaction]),
                ).chance
                for reaction in view.reactions
            }
            result.append(
                {
                    "pinpoint": pinpoint,
                    "original_resists": original_resists,
                    "coverer_resists": coverer_resists,
                    **chances,
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
    print(
        json.dumps(
            {
                "next_action": samples(),
                "cover": cover_samples(),
                "sustained": sustained() + sustained(alternating=True),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
