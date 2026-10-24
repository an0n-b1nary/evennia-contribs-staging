# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Deterministic read-time upgrades; stored journal/build rows never change."""

from copy import deepcopy

from . import partners
from .data import CombatError

SCHEMA = 5

# Combat 0.2's per-participant fields: a pending recovery action, the
# standing choice about allies' revivals, and Measured Tempo charges.
PARTICIPANT_DEFAULTS = {"recovering": False, "revive": "ask", "tempo": 0}


def upgrade(value):
    if not isinstance(value, dict) or type(value.get("schema")) is not int:
        raise CombatError("Unsupported combat state version; no progress was applied.")
    state = deepcopy(value)
    if state["schema"] == 1:
        state.setdefault("partners", {})
        state["schema"] = 2
    if state["schema"] == 2:
        for row in state["participants"].values():
            for key, default in PARTICIPANT_DEFAULTS.items():
                row.setdefault(key, default)
        state["schema"] = 3
    if state["schema"] == 3:
        state["effect_results"] = {}
        for row in state["participants"].values():
            row["turn_skip"] = None
            row["partner_subjects"] = {}
            row["actions_spent"] = (
                row["turns"] * row["allowance"] + row["allowance"] - row["actions_left"]
            )
        state["schema"] = 4
    if state["schema"] == 4:
        for row in state["participants"].values():
            row["armed"] = {}
        state["schema"] = 5
    if state["schema"] != SCHEMA:
        raise CombatError(
            "Unsupported combat state version; staff must restore or migrate this fight."
        )
    return partners.upgrade_sections(state)
