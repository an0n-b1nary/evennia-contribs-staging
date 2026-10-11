# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Validated passive combat effects with explicit, restricted phase inputs.

Register ``combat_bonus`` in RP_RULES_EFFECT_KINDS. Ordinary checks build
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
        effect = CombatEffect.from_spec(json.loads(serialized), key=key)
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
