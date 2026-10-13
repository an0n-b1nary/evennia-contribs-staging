# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reusable encounter effects; callers supply authorization, lock and draws.

Effect identifiers are checkpointed idempotency keys. These operations are
not attacks/exchanges and grant only normal damage-taken resources.
"""

from copy import deepcopy
from fractions import Fraction as F

from . import arithmetic as math
from . import engine, partners
from .data import Build, CombatError, Move
from .modifiers import bonus as passive


def damage(state, source, target, amount, ident):
    source, target = str(source), str(target)
    if type(amount) is not int or amount < 0 or not isinstance(ident, str) or not ident:
        raise CombatError("Encounter damage needs a nonnegative integer and stable identity.")
    request = [source, target, amount]
    ledger = state["effect_results"]
    if ident in ledger:
        if ledger[ident]["request"] != request:
            raise CombatError("That encounter effect identity belongs to another request.")
        return ledger[ident]["damage"]
    actor, victim = engine.participant(state, source), engine.participant(state, target)
    if actor["side"] == victim["side"]:
        raise CombatError("Encounter damage requires opposing sides.")
    eligible = engine.participating(victim)
    actual = engine.harm(victim, amount) if eligible else 0
    ledger[ident] = {"request": request, "damage": actual}
    partners.emit(
        state,
        partners.Event(
            "hostile_damage",
            source,
            ident,
            0,
            target,
            damage=actual,
            target_was_participating=eligible,
        ),
    )
    return actual


def resist(state, source, target, amount, draw, ident):
    """Domain-neutral declared damage, normal Resist odds/mitigation/pressure.

    Profile: physical Attack, Accuracy 0, attacker Spirit 0, no element,
    RPS, Empower or attack riders. Defender passives/stances/exposure apply.
    """
    source, target = str(source), str(target)
    ledger_key = f"resist/{ident}"
    request = [source, target, amount, draw]
    if ledger_key in state["effect_results"]:
        saved = state["effect_results"][ledger_key]
        if saved["request"] != request:
            raise CombatError("That Resist test identity belongs to another request.")
        return deepcopy(saved["result"])
    if type(amount) is not int or amount < 0:
        raise CombatError("Declared test damage must be a nonnegative integer.")
    defender = engine.active(state, target)
    build = Build.from_dict(defender["build"])
    result = math.resolve(
        Build.from_dict(engine.participant(state, source)["build"]),
        build,
        Move(),
        "resist",
        draw,
        accuracy=0,
        spirit=0,
        defender_spirit=defender["spirit"],
        pressure=defender["pressure"],
        penalty=engine.exposure(defender, build, "resist"),
        bonus=engine.value(defender, "resist_stance")
        + engine.value(defender, "flowing_resist")
        + passive(build, "before_reaction", "resist", "attack")
        + passive(build, "before_resolution", "resist", "attack"),
        damage_override=F(amount),
    )
    loss = damage(state, source, target, result.damage, ident)
    defender["pressure"] = min(30, defender["pressure"] + result.pressure_gain)
    value = {
        "chance": result.chance,
        "success": result.success,
        "damage": loss,
        "pressure_gain": result.pressure_gain,
    }
    state["effect_results"][ledger_key] = {"request": request, "result": value}
    return deepcopy(value)


def stagger(state, target, penalty, source):
    """One nonstacking next-full-turn skip with a persistent reaction opening."""
    row = engine.participant(state, target)
    if type(penalty) is not int or not 0 <= penalty <= 100:
        raise CombatError("The reaction penalty must be 0..100 percentage points.")
    if row.get("turn_skip") is not None:
        return False
    row["turn_skip"] = {"pending": True, "source": str(source)}
    # This condition's lifetime is controlled by execution, never wall time
    # or the current partial turn's exchange clock. It cannot consume Ward.
    row["conditions"]["staggered"] = {
        "magnitude": penalty,
        "expires": 2**63 - 1,
        "source": str(source),
    }
    consume_skip(row)
    return True


def consume_skip(row):
    skip = row.get("turn_skip")
    if skip and skip["pending"] and row["actions_left"] == row["allowance"]:
        row["turns"] = min(row["turn_limit"], row["turns"] + 1)
        skip["pending"] = False


def initiating_executed(row):
    """Called only for an executed initiating packet, never a declaration."""
    if row.get("turn_skip") and not row["turn_skip"]["pending"]:
        row["conditions"].pop("staggered", None)
        row["turn_skip"] = None
