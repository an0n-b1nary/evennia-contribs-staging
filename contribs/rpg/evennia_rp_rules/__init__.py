# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_rp_rules — the value-neutral resolution kernel for the rp- cluster.

Graded stats with edge and weakness pips, a shared outcome ladder, pluggable
resolvers, seedable dice, and exact odds. No models, no commands, and no stat
names: a game supplies those as a ruleset dict (see `example_ruleset`).

Public API (loaded lazily; importing the package never imports Django):

    Scale, Rung, Rating          — scales.py
    Outcome, OutcomeLadder, Odds — outcomes.py
    DiceSpec, RandomRoller, ScriptedRoller, distribution — dice.py
    Contest, Resolution, GradedResolver — resolvers.py
    Ruleset, StatDef, TagDef, get_ruleset, reset_ruleset_cache — ruleset.py
    Issue, RulesetError          — issues.py

Odds tool:

    python -m evennia_rp_rules.odds --help
"""

__version__ = "0.1.0"

_LAZY = {
    "Scale": "scales",
    "Rung": "scales",
    "Rating": "scales",
    "Outcome": "outcomes",
    "OutcomeLadder": "outcomes",
    "Odds": "outcomes",
    "DiceSpec": "dice",
    "RandomRoller": "dice",
    "ScriptedRoller": "dice",
    "distribution": "dice",
    "Contest": "resolvers",
    "Resolution": "resolvers",
    "GradedResolver": "resolvers",
    "Ruleset": "ruleset",
    "StatDef": "ruleset",
    "TagDef": "ruleset",
    "get_ruleset": "ruleset",
    "reset_ruleset_cache": "ruleset",
    "Issue": "issues",
    "RulesetError": "issues",
}

__all__ = sorted(_LAZY)


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{submodule}", __name__), name)


def __dir__():
    return sorted([*globals(), *_LAZY])
