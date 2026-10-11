# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Validated passive combat effects with explicit, restricted phase inputs.

Register ``combat_bonus`` and ``combat_rule`` in RP_RULES_EFFECT_KINDS.
``combat_bonus`` adds fixed amounts at combat phases; ``combat_rule`` selects
one of the bounded conditional rules in RULES. Ordinary checks build
these modifiers safely but never execute them: hooks() is empty there.
Combat folds frozen specs without handing hooks live objects or hidden draws.
"""

import json
from fractions import Fraction

from evennia_rp_rules.modifiers import BaseModifier, EffectSpecError

FIELDS = {
    "build": ("attack", "attack_defense", "spell", "spell_defense", "dispirit", "will", "agility"),
    "declare": ("power", "accuracy"),
    "before_reaction": ("evade", "resist", "overpower"),
    "before_resolution": ("power", "accuracy", "evade", "resist", "overpower"),
    "after_resolution": ("spirit",),
    "exchange_end": ("pressure_recovery", "reserves", "transcendence"),
}


class CombatEffect(BaseModifier):
    def hooks(self):
        return set()

    @classmethod
    def from_spec(cls, spec, *, level=1, **meta):
        allowed = {
            "kind",
            "phase",
            "field",
            "amount",
            "per_level",
            "actions",
            "stack",
            "key",
            "label",
            "visibility",
            "priority",
        }
        problems = []
        if set(spec) - allowed:
            problems.append("combat_bonus: unknown fields")
        phase = spec.get("phase", "build")
        field = spec.get("field", "")
        if (
            not isinstance(phase, str)
            or not isinstance(field, str)
            or field not in FIELDS.get(phase, ())
        ):
            problems.append("combat_bonus: field is not permitted in that phase")
        stack = spec.get("stack")
        if stack is not None and (not isinstance(stack, str) or not 1 <= len(stack) <= 64):
            problems.append("combat_bonus: stack must be a short nonempty key")
        actions = spec.get("actions", [])
        if not isinstance(actions, list) or any(
            a not in ("attack", "spell", "assist", "dispirit") for a in actions
        ):
            problems.append("combat_bonus: actions must name combat actions")
        try:
            amount = Fraction(str(spec.get("amount", 0))) + (level - 1) * Fraction(
                str(spec.get("per_level", 0))
            )
            if abs(amount) > 100:
                problems.append("combat_bonus: magnitude exceeds 100")
        except (ValueError, TypeError, ZeroDivisionError):
            problems.append("combat_bonus: amount/per_level must be finite numbers")
            amount = Fraction(0)
        if spec.get("visibility", "open") != "open":
            problems.append("combat_bonus: numeric passives in 0.1 must be open")
        if problems:
            raise EffectSpecError(problems)
        effect = cls()
        effect.phase, effect.field, effect.amount = phase, field, amount
        effect.actions = tuple(actions)
        effect.stack = spec.get("stack")
        effect.key = meta.get("key") or spec.get("key", "combat_bonus")
        return effect

    def frozen(self):
        return {
            "kind": "combat_bonus",
            "phase": self.phase,
            "field": self.field,
            "amount": str(self.amount),
            "actions": list(self.actions),
            "stack": self.stack,
        }


def bonus(build, phase, field, action=""):
    total, stacks = Fraction(0), {}
    for key, serialized in build.effects:
        spec = json.loads(serialized)
        if spec.get("kind", "combat_bonus") != "combat_bonus":
            continue
        effect = CombatEffect.from_spec(spec, key=key)
        if (
            effect.phase != phase
            or effect.field != field
            or (effect.actions and action not in effect.actions)
        ):
            continue
        if effect.stack:
            stacks[effect.stack] = max(stacks.get(effect.stack, effect.amount), effect.amount)
        else:
            total += effect.amount
    return total + sum(stacks.values())


# Conditional Ability rules: one validated parameter set per rule. Numeric
# fields are (low, high) bounds checked at every level; ``scale`` names the
# field ``per_level`` grows. Values sum across a build's entries for the
# same rule and are clamped again, so stacking never escapes the bounds.
F = Fraction
RULES = {
    # Successful Resist keeps less damage: fraction minus amount x Agility.
    "deflect": {"fields": {"amount": (0, F(1, 100))}, "scale": "amount"},
    # Evade's glancing band widens by band x defense, up to cap points;
    # glancing blows keep `mitigation` less of the damage.
    "stoneskin": {
        "fields": {"band": (0, F(1, 4)), "cap": (0, 10), "mitigation": (0, F(1, 4))},
        "scale": "band",
    },
    # Points added to a bet's penalty and bonus; bet "" means every bet.
    "rps": {"fields": {"penalty": (-20, 20), "bonus": (-20, 20)}, "scale": "penalty"},
    # Lower-Power counter penalty points removed per Accuracy tier of margin.
    "finesse": {"fields": {"amount": (0, 15)}, "scale": "amount"},
    # Reserves off Stance-bearing moves; Transcendence off each exchange end.
    "tactician": {"fields": {"discount": (0, 2), "transcendence": (0, 8)}, "scale": None},
    # Accuracy tiers per charge on the next Burst; charges up to cap.
    "measured_tempo": {"fields": {"amount": (0, 1), "cap": (1, 5)}, "scale": "amount"},
    # Overextended added by pressing or a broken chain is multiplied by factor.
    "explosive": {"fields": {"factor": (F(1, 2), 1)}, "scale": None},
    # Reaction points for the other reaction after a successful Evade/Resist.
    "flowing_guard": {"fields": {"amount": (-20, 20)}, "scale": "amount"},
    # After support, Vulnerable spares Resist and adds amount to the others.
    "braced_support": {"fields": {"amount": (0, 20)}, "scale": None},
    # A public bet's penalty grows by amount; its bonus is unchanged.
    "calling_the_shot": {"fields": {"amount": (0, 20)}, "scale": "amount"},
    # Negative own Spirit no longer lowers Overpower chances.
    "desperate_counter": {"fields": {}, "scale": None},
    # Spirit (hundredths) off the next Burst ante after a landed Dispirit.
    "taunting_opener": {"fields": {"amount": (0, 600)}, "scale": "amount"},
    # One Reserve once per exchange when a defender's Overpower fails.
    "bait": {"fields": {}, "scale": None},
    # Vitality paid per missing Reserve for a special move.
    "blood_price": {"fields": {"amount": (1, 20)}, "scale": None},
}
BETS = ("", "reaching", "penetrating", "subtle")
INTEGER_FIELDS = {"cap", "discount", "transcendence"}


class CombatRule(BaseModifier):
    """A conditional combat Ability rule, interpreted only by combat."""

    def hooks(self):
        return set()

    @classmethod
    def from_spec(cls, spec, *, level=1, **meta):
        problems = []
        name = spec.get("rule")
        definition = RULES.get(name) if isinstance(name, str) else None
        if definition is None:
            raise EffectSpecError(["combat_rule: unknown rule"])
        allowed = {"kind", "rule", "per_level", "key", "label", "visibility", "priority"}
        allowed |= set(definition["fields"])
        if name == "rps":
            allowed.add("bet")
        if set(spec) - allowed:
            problems.append("combat_rule: unknown fields")
        if spec.get("visibility", "open") != "open":
            problems.append("combat_rule: rules must be open")
        bet = spec.get("bet", "")
        if name == "rps" and bet not in BETS:
            problems.append("combat_rule: bet must be reaching, penetrating, subtle or empty")
        values = {}
        try:
            per_level = F(str(spec.get("per_level", 0)))
            if per_level and definition["scale"] is None:
                problems.append("combat_rule: this rule does not scale with level")
            for field, (low, high) in definition["fields"].items():
                value = F(str(spec.get(field, 0)))
                if field == definition["scale"]:
                    value += (level - 1) * per_level
                if field in INTEGER_FIELDS and value.denominator != 1:
                    problems.append(f"combat_rule: {field} must be whole")
                if not low <= value <= high:
                    problems.append(f"combat_rule: {field} must be within {low}..{high}")
                values[field] = value
        except (ValueError, TypeError, ZeroDivisionError):
            problems.append("combat_rule: values must be finite numbers")
        if problems:
            raise EffectSpecError(problems)
        effect = cls()
        effect.rule, effect.bet, effect.values = name, bet, values
        effect.key = meta.get("key") or spec.get("key", "combat_rule")
        return effect

    def frozen(self):
        data = {"kind": "combat_rule", "rule": self.rule}
        data.update({field: str(value) for field, value in self.values.items()})
        if self.rule == "rps":
            data["bet"] = self.bet
        return data


def rules(build):
    """A build's combined rules: {rule: {field: Fraction}}; rps by bet."""
    combined = {}
    for _key, serialized in build.effects:
        spec = json.loads(serialized)
        if spec.get("kind") != "combat_rule":
            continue
        name = spec["rule"]
        fields = RULES[name]["fields"]
        target = combined.setdefault(name, {})
        if name == "rps":
            target = target.setdefault(spec.get("bet", ""), {})
        for field in fields:
            target[field] = target.get(field, F(0)) + F(spec.get(field, "0"))
    for name, values in combined.items():
        groups = values.values() if name == "rps" else (values,)
        for group in groups:
            for field, (low, high) in RULES[name]["fields"].items():
                group[field] = max(F(low), min(F(high), group.get(field, F(0))))
    return combined


def rps_shift(build, bet):
    """Penalty and bonus points a build adds to its own bet."""
    table = rules(build).get("rps", {})
    penalty = sum((table.get(key, {}).get("penalty", F(0)) for key in ("", bet)), F(0))
    bonus = sum((table.get(key, {}).get("bonus", F(0)) for key in ("", bet)), F(0))
    return max(F(-20), min(F(20), penalty)), max(F(-20), min(F(20), bonus))


def move_cost(build, move):
    """A move's Reserve cost after Tactician's Stance discount."""
    cost = move.cost
    stances = sum(effect.endswith("_stance") for effect in move.effects)
    discount = rules(build).get("tactician", {}).get("discount", F(0))
    return cost - min(stances, int(discount))
