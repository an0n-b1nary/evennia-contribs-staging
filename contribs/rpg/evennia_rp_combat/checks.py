# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from fractions import Fraction

from django.core.checks import Error

from . import conf


def check_configuration(app_configs=None, **kwargs):
    from .arithmetic import DEFAULT_RULES
    from .data import Move
    from .engine import DOMAIN_ACTIONS

    errors = []
    required = {"attack", "attack_defense", "spell", "spell_defense", "dispirit", "will", "agility"}
    roles = conf.get("RP_COMBAT_ROLES")
    if (
        not isinstance(roles, dict)
        or set(roles) != required
        or any(not isinstance(v, str) or not v for v in roles.values())
    ):
        errors.append(
            Error("RP_COMBAT_ROLES must map every combat role to a stat key.", id="rp_combat.E001")
        )
    for name, minimum in (
        ("RP_COMBAT_TURN_LIMIT", 1),
        ("RP_COMBAT_IDLE_SECONDS", 0),
        ("RP_COMBAT_TACTICS_LIMIT", 1),
    ):
        value = conf.get(name)
        if type(value) is not int or value < minimum:
            errors.append(Error(f"{name} must be an integer >= {minimum}.", id="rp_combat.E002"))
    for name in ("RP_COMBAT_SCORE_BASES", "RP_COMBAT_EDGE_FACTORS"):
        values = conf.get(name)
        try:
            if len(values) != 5:
                raise ValueError
            for value in values:
                Fraction(str(value))
        except (TypeError, ValueError, ZeroDivisionError):
            errors.append(Error(f"{name} must contain five finite numbers.", id="rp_combat.E003"))
    rules = conf.get("RP_COMBAT_RULES")
    try:
        if not isinstance(rules, dict) or set(rules) - DEFAULT_RULES.keys():
            raise ValueError
        merged = {key: Fraction(str(rules.get(key, value))) for key, value in DEFAULT_RULES.items()}
        if (
            any(value < 0 for value in merged.values())
            or merged["damage_floor"] > merged["damage_ceiling"]
            or not 0 <= merged["resist_min_fraction"] <= merged["resist_max_fraction"] <= 1
        ):
            raise ValueError
    except (TypeError, ValueError, ZeroDivisionError):
        errors.append(
            Error(
                "RP_COMBAT_RULES has an unknown key or invalid numeric bounds.", id="rp_combat.E004"
            )
        )
    domains = conf.get("RP_COMBAT_DOMAIN_EFFECTS")
    if not isinstance(domains, dict) or any(
        not isinstance(k, str) or not k or not isinstance(v, str) or v not in DOMAIN_ACTIONS
        for k, v in domains.items()
    ):
        errors.append(
            Error(
                "RP_COMBAT_DOMAIN_EFFECTS must map domain keys to supported effects.",
                id="rp_combat.E005",
            )
        )
    traits = conf.get("RP_COMBAT_ELEMENT_TRAITS")
    known = {
        "drain",
        "spirit_loss",
        "normalize",
        "op_penalty",
        "penetrating_resist",
        "spirit_gain",
        "half_transcendence",
        "dispel",
    }
    if not isinstance(traits, dict) or any(
        not isinstance(k, str)
        or not isinstance(v, (list, tuple))
        or any(not isinstance(t, str) or t not in known for t in v)
        for k, v in traits.items()
    ):
        errors.append(
            Error("RP_COMBAT_ELEMENT_TRAITS contains unsupported traits.", id="rp_combat.E006")
        )
    catalog = conf.get("RP_COMBAT_NPC_MOVES")
    try:
        if not isinstance(catalog, dict):
            raise ValueError
        for key, definition in catalog.items():
            Move.from_dict({**definition, "key": key, "kind": "signature"})
    except (TypeError, ValueError):
        errors.append(
            Error("RP_COMBAT_NPC_MOVES contains an invalid move definition.", id="rp_combat.E007")
        )
    return errors
