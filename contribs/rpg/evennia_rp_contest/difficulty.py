# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Resolve configured difficulty presets or a rating on the chosen stat scale."""

from evennia_rp_contest import conf
from evennia_rp_rules.ruleset import get_ruleset


def resolve_difficulty(text=None, *, stat=None):
    ruleset = get_ruleset()
    scale = ruleset.stats[stat].scale if stat else ruleset.default_scale
    if text is None:
        text = conf.get("RP_CONTEST_DEFAULT_DIFFICULTY")
    if text is None:
        return scale.parse(scale.rungs[len(scale.rungs) // 2].key)
    presets = conf.get("RP_CONTEST_DIFFICULTIES")
    text = next((v for k, v in presets.items() if k.casefold() == str(text).casefold()), text)
    return scale.parse(str(text))
