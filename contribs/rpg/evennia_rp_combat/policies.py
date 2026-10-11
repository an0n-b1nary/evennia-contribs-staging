# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Deliberate, injectable policies receiving capability-limited views only."""

from fractions import Fraction as F

from .arithmetic import resolve
from .data import REACTIONS, TIERS, Build, CombatError, Move
from .modifiers import bonus

APPETITES = {"cautious": (F(1, 4), 1), "balanced": (F(3, 4), F(1, 2)), "bold": (F(3, 2), F(1, 4))}


def auto_react(view, *, appetite="balanced", preferred="", preferred_moves=()):
    """Minimize expected incoming loss minus counter value with neutral RPS.

    Estimates deliberately use only incoming public facts and one's own
    build. The unknown attacker's scores are neutral, never inspected.
    """
    if appetite not in APPETITES:
        raise CombatError("Choose Cautious, Balanced or Bold.")
    if not view.estimates:
        return preferred if preferred in view.reactions else "resist", Move()
    attacker = Build(tuple((role, "0") for role, _ in view.build.scores))
    move = Move(power=0, accuracy=0, action=view.action)
    k, cost = APPETITES[appetite]
    candidates = []
    counters = [Move(key=tier, power=p, accuracy=a) for tier, (p, a) in TIERS.items()]
    counters += [
        move
        for move in view.build.moves
        if move.action in ("attack", "spell") and move.cost <= view.reserves
    ]
    for reaction in view.reactions:
        for counter in counters if reaction == "overpower" else [Move()]:
            if "strain" in counter.effects and view.hp <= 5:
                continue
            outcomes = [
                resolve(
                    attacker,
                    view.build,
                    move,
                    reaction,
                    roll,
                    accuracy=view.accuracy,
                    power=view.power,
                    spirit=view.spirit,
                    defender_spirit=view.spirit_self,
                    pressure=view.pressure,
                    counter=counter,
                    counter_power=counter.power
                    + bonus(view.build, "declare", "power", counter.action)
                    + bonus(view.build, "before_resolution", "power", counter.action),
                    counter_accuracy=counter.effective_accuracy
                    + bonus(view.build, "declare", "accuracy", counter.action)
                    + bonus(view.build, "before_resolution", "accuracy", counter.action),
                    penalty=F(dict(view.penalties).get(reaction, "0")),
                    bonus=F(dict(view.bonuses).get(reaction, "0")),
                    damage_boost=F(view.damage_boost),
                    surge=F(view.surge),
                )
                for roll in range(1, 101)
            ]
            strain_cost = 5 if "strain" in counter.effects else 0
            ko = sum(o.damage >= view.hp - strain_cost for o in outcomes)
            utility = (
                sum(o.damage - k * o.counter_damage for o in outcomes) / 100
                + cost * counter.cost
                + strain_cost
            )
            candidates.append(
                (
                    (
                        ko if appetite == "cautious" else 0,
                        utility,
                        reaction != preferred,
                        counter.key not in preferred_moves,
                        preferred_moves.index(counter.key)
                        if counter.key in preferred_moves
                        else 99,
                        REACTIONS.index(reaction),
                        counter.key,
                    ),
                    reaction,
                    counter,
                )
            )
    _, reaction, counter = min(candidates)
    return reaction, counter


def auto_act(view, *, rng, appetite="balanced", target_policy="random", weights=None):
    """Random guesses; no target builds, committed reactions or roll inputs."""
    if not view.targets and not view.allies:
        raise CombatError("No eligible target for Auto-Act.")
    frequencies = {"cautious": 0, "balanced": 35, "bold": 75}
    if appetite not in frequencies:
        raise CombatError("Choose Cautious, Balanced or Bold for RPS appetite.")
    moves = [Move(key=k, name=k.title(), power=p, accuracy=a) for k, (p, a) in TIERS.items()]
    moves += [
        Move(action="spell", key=f"spell-{k}", name=f"{k.title()} spell", power=p, accuracy=a)
        for k, (p, a) in TIERS.items()
    ]
    moves.extend(
        (
            *view.build.moves,
            Move(key="assist", action="assist"),
            Move(key="dispirit", action="dispirit"),
        )
    )
    legal = [
        m
        for m in moves
        if m.cost <= view.reserves
        and ("strain" not in m.effects or view.hp > 5)
        and (view.allies if m.action == "assist" else view.targets)
    ]
    weights = weights or {"standard": 6, "special": 2, "assist": 1, "dispirit": 1}
    groups = {}
    for move in legal:
        group = (
            move.action
            if move.action in ("assist", "dispirit")
            else "standard"
            if move.kind == "standard"
            else "special"
        )
        groups.setdefault(group, []).append(move)
    groups = {key: values for key, values in groups.items() if weights.get(key, 0) > 0}
    if not groups:
        if not view.targets:
            raise CombatError("No affordable move has a positive Auto-Act weight.")
        groups, weights = {"standard": [Move()]}, {"standard": 1}
    group = rng.choices(list(groups), weights=[weights[k] for k in groups], k=1)[0]
    move = rng.choice(groups[group])
    targets = view.allies if move.action == "assist" else view.targets
    if target_policy == "lowest_vitality" and all(t[1] is not None for t in targets):
        target = min(targets, key=lambda t: (t[1], t[0]))[0]
    elif target_policy == "provoker" and any(t[0] == view.provoker for t in targets):
        target = view.provoker
    else:
        target = rng.choice(targets)[0]
    bet = (
        rng.choice(("reaching", "penetrating", "subtle"))
        if move.action in ("attack", "spell") and rng.randrange(100) < frequencies[appetite]
        else ""
    )
    return target, move, bet
