# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Exact combat arithmetic. No database, random generator or ordinary checks.

Spirit is stored in hundredths; other resources are integral. Calculation
uses Fractions and rounds once at the documented award boundary.
"""

from dataclasses import dataclass
from fractions import Fraction as F

from . import conf
from .data import CombatError

DEFAULT_RULES = {
    "damage_floor": 4,
    "damage_ceiling": 45,
    "damage_base": 18,
    "damage_score_weight": F(7, 20),
    "damage_power_weight": 4,
    "strain_damage": 5,
    "evade_base": 50,
    "evade_accuracy_weight": 8,
    "resist_base": 60,
    "resist_defense_weight": F(7, 10),
    "resist_agility_weight": F(3, 10),
    "resist_accuracy_weight": 4,
    "resist_pressure_chance": F(1, 2),
    "resist_fraction": F(3, 10),
    "resist_defense_fraction": F(1, 200),
    "resist_pressure_fraction": F(1, 100),
    "resist_min_fraction": F(1, 4),
    "resist_max_fraction": F(85, 100),
    "overpower_base": 45,
    "overpower_accuracy_weight": 8,
    "overpower_lower_power_penalty": 15,
    "overpower_fraction": F(1, 2),
    "overpower_power_fraction": F(1, 10),
    "pressure_recovery": 6,
    "stance_full": 10,
    "stance_defended": 2,
}


def rule(name):
    return F(str(conf.get("RP_COMBAT_RULES").get(name, DEFAULT_RULES[name])))


RPS = {
    "": {"evade": 0, "resist": 0, "overpower": 0},
    "reaching": {"evade": -20, "resist": 0, "overpower": 20},
    "penetrating": {"evade": 20, "resist": -20, "overpower": 0},
    "subtle": {"evade": 0, "resist": 20, "overpower": -20},
}


def clamp(low, high, value):
    return max(low, min(high, value))


def rounded(value):
    value = F(value)
    if value < 0:
        return -rounded(-value)
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def threshold(value):
    return clamp(5, 95, rounded(value))


def raw_damage(offense, defense, power, *, strain=False, multiplier=1):
    return (
        clamp(
            rule("damage_floor"),
            rule("damage_ceiling"),
            rule("damage_base")
            + rule("damage_score_weight") * (offense - defense)
            + rule("damage_power_weight") * power,
        )
        + (rule("strain_damage") if strain else 0)
    ) * multiplier


@dataclass(frozen=True)
class Outcome:
    reaction: str
    chance: int
    success: bool
    glancing: bool
    domain: bool
    damage: int
    counter_damage: int
    pressure_gain: int
    burst_damage: int = 0


def resolve(
    attack,
    defense,
    move,
    reaction,
    roll,
    *,
    accuracy=None,
    power=None,
    spirit=0,
    defender_spirit=0,
    pressure=0,
    penalty=0,
    bonus=0,
    rps="",
    counter=None,
    counter_power=None,
    counter_accuracy=None,
    slip_inside=False,
    endure=False,
    strain=False,
    multiplier=1,
    counter_multiplier=1,
    ignore_penetrating=False,
    rps_shift=(0, 0),
    damage_boost=0,
    surge=0,
    damage_override=None,
):
    """Resolve one packet; damage is before remaining-Vitality truncation.

    ``penalty`` is nonnegative exposure; ``bonus`` is a signed reaction
    modifier. Public callers omit RPS; policy callers never receive it,
    except a bet its attacker made public. ``rps_shift`` adds points to the
    bet's penalty and bonus (the attacker's own rules). The defender's own
    conditional rules come from ``defense``, so previews and automatic
    reactions see exactly what manual resolution applies.
    """
    from .modifiers import rules

    own = rules(defense)
    if reaction not in ("evade", "resist", "overpower") or rps not in RPS:
        raise CombatError("Unknown reaction or RPS bet.")
    if type(roll) is not int or not 1 <= roll <= 100:
        raise CombatError("A combat roll must be a whole d100 result.")
    if move.action not in ("attack", "spell"):
        raise CombatError("Only Attack and Spell create a reaction.")
    power = move.power if power is None else F(power)
    accuracy = move.effective_accuracy if accuracy is None else F(accuracy)
    agility = defense.score("agility")
    defensive = defense.score(f"{move.action}_defense")
    spirit, defender_spirit = F(spirit, 100), F(defender_spirit, 100)
    rps_bonus = F(RPS[rps][reaction])
    if rps_bonus < 0:
        rps_bonus = min(F(0), rps_bonus - F(rps_shift[0]))
    elif rps_bonus > 0:
        rps_bonus = max(F(0), rps_bonus + F(rps_shift[1]))
    if ignore_penetrating and rps == "penetrating" and reaction == "resist":
        rps_bonus = 0
    modifier = bonus - penalty + rps_bonus
    counter = counter or move.__class__()
    cp = counter.power if counter_power is None else counter_power
    ca = counter.effective_accuracy if counter_accuracy is None else counter_accuracy
    if reaction == "evade":
        chance = threshold(
            rule("evade_base")
            + agility
            - rule("evade_accuracy_weight") * accuracy
            - spirit
            + modifier
        )
    elif reaction == "resist":
        chance = threshold(
            rule("resist_base")
            + rule("resist_defense_weight") * defensive
            + rule("resist_agility_weight") * agility
            - rule("resist_accuracy_weight") * accuracy
            - spirit
            - rule("resist_pressure_chance") * pressure
            + modifier
        )
    else:
        gap_penalty = rule("overpower_lower_power_penalty") * max(power - cp, 0)
        if "finesse" in own:
            # A more accurate counter recovers part of the Power-gap penalty.
            gap_penalty = max(F(0), gap_penalty - own["finesse"]["amount"] * max(ca - accuracy, 0))
        if "desperate_counter" in own:
            defender_spirit = max(defender_spirit, F(0))
        chance = threshold(
            rule("overpower_base")
            + rule("overpower_accuracy_weight") * (ca - accuracy)
            + defender_spirit
            - spirit
            - (0 if slip_inside else gap_penalty)
            + modifier
        )
    success = roll <= chance
    band = 10
    glance_fraction = F(1, 2)
    if "stoneskin" in own:
        # Sturdiness turns some clean hits into glancing blows, never into
        # clean Evades; the domain slice stays nearest a clean hit.
        band += min(own["stoneskin"]["cap"], max(F(0), own["stoneskin"]["band"] * defensive))
        glance_fraction -= own["stoneskin"]["mitigation"]
    glancing = reaction == "evade" and chance < roll <= min(100, chance + band)
    domain = not success
    if reaction == "evade" and glancing:
        domain = roll > min(100, chance + band) - 2
    fraction = F(1)
    if reaction == "evade":
        fraction = F(0) if success else glance_fraction if glancing else F(1)
    elif success and reaction == "resist":
        fraction = clamp(
            rule("resist_min_fraction"),
            rule("resist_max_fraction"),
            rule("resist_fraction")
            - defensive * rule("resist_defense_fraction")
            + pressure * rule("resist_pressure_fraction")
            - own.get("deflect", {}).get("amount", F(0)) * max(agility, F(0)),
        )
    elif success:
        fraction = clamp(
            F(1, 4),
            F(4, 5),
            rule("overpower_fraction") + (power - cp) * rule("overpower_power_fraction"),
        )
    raw = raw_damage(
        attack.score(move.action), defensive, power, strain=strain, multiplier=multiplier
    )
    if damage_override is not None:
        raw = F(damage_override)
        if raw < 0:
            raise CombatError("Declared test damage cannot be negative.")
    # Party damage cannot feed its own Spirit-transfer loop. Surge is a
    # separate paid output benefit and remains in the transfer basis.
    burst_damage = rounded(raw * (1 + F(surge) / 100) * fraction)
    raw *= 1 + (F(damage_boost) + F(surge)) / 100
    damage = rounded(raw * fraction)
    counter_damage = 0
    if reaction == "overpower" and success:
        counter_damage = rounded(
            raw_damage(
                defense.score(counter.action),
                attack.score(f"{counter.action}_defense"),
                cp,
                multiplier=counter_multiplier,
                strain="strain" in counter.effects,
            )
        )
    gain = rounded(raw) - damage if reaction == "resist" and success and not endure else 0
    return Outcome(
        reaction, chance, success, glancing, domain, damage, counter_damage, gain, burst_damage
    )


def support_values(
    actor,
    target,
    action,
    roll,
    *,
    active=None,
    factor=1,
    repeat=False,
    heals=0,
    empower=False,
    surge=0,
):
    active = (
        max(actor.score(k) for k in ("attack", "spell", "dispirit")) if active is None else active
    )
    multiplier = (F(3, 2) if empower else F(1)) + F(surge) / 100
    if action == "assist":
        magnitude = F(3, 4) + F(roll - 1, 198)
        value = (4 + active / 10) * magnitude * factor * multiplier
        healing = rounded(
            (12 + F(3, 10) * active) * magnitude * factor * F(3, 4) ** heals * multiplier
        )
        return rounded(100 * value * (F(1, 4) if repeat else 1)), healing, True
    chance = threshold(65 + (actor.score("dispirit") - target.score("will")) / 2)
    success = roll <= chance
    value = (6 + actor.score("dispirit") / 10) * factor * multiplier
    return -rounded(100 * value * (F(1, 4) if repeat else 1)) if success else 0, 0, success


def burst_ante(spirit, ante=600):
    paid = min(ante, spirit + 1000)
    return spirit - paid, ante - paid


def burst_transfer(damage, will, actor_spirit, target_spirit, debt):
    requested = rounded(100 * min(4, F(17, 100) * damage / (1 + max(will, 0) / 40)))
    actual = min(requested, target_spirit + 1000, 2000 - actor_spirit + debt)
    repayment = min(debt, actual)
    return (
        actor_spirit + actual - repayment,
        target_spirit - actual,
        debt - repayment,
        requested,
        actual,
    )


def spirit_after_hit(will, spirit, defended):
    if defended:
        return 200
    if spirit > 0:
        return -min(spirit, rounded(100 * clamp(1, 3, 2 - will / 20)))
    return min(-spirit, rounded(100 * clamp(1, 3, 2 + will / 20)))
