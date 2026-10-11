# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Deterministic read-time upgrades; stored journal/build rows never change."""

from copy import deepcopy

from . import partners
from .data import CombatError

SCHEMA = 2


def upgrade(value):
    if not isinstance(value, dict) or type(value.get("schema")) is not int:
        raise CombatError("Unsupported combat state version; no progress was applied.")
    state = deepcopy(value)
    if state["schema"] == 1:
        state.setdefault("partners", {})
        state["schema"] = 2
    if state["schema"] != SCHEMA:
        raise CombatError(
            "Unsupported combat state version; staff must restore or migrate this fight."
        )
    return partners.upgrade_sections(state)
