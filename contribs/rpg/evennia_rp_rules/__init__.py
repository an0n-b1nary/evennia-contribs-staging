# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_rp_rules — the value-neutral resolution kernel for the rp- cluster.

Graded stats with edge and weakness pips, a shared outcome ladder, pluggable
resolvers, seedable dice, exact odds, and a phased modifier pipeline that turns
a check into an outcome. No models, no commands, and no stat names: a game
supplies those as a ruleset dict (see `example_ruleset`).

Public API (loaded lazily; importing the package never imports Django):

    Scale, Rung, Rating          — scales.py
    Outcome, OutcomeLadder, Odds — outcomes.py
    DiceSpec, RandomRoller, ScriptedRoller, distribution — dice.py
    Contest, Resolution, GradedResolver — resolvers.py
    Ruleset, StatDef, TagDef, get_ruleset, reset_ruleset_cache — ruleset.py
    Issue, RulesetError          — issues.py
    Check, CheckResult, CheckEstimate, CheckError,
        resolve_check, estimate_check — checks.py
    Modifier, BaseModifier, ScoreBonus, TagBonus, RungShift,
        build_modifier, EffectSpecError — modifiers.py
    ResolutionContext            — pipeline.py
    StatSource, DictStatSource, get_subject — subjects.py
    Vocabulary, get_vocabulary   — vocabulary.py

Phase, side and visibility constants live in `phases`; the `check_resolved`
signal in `signals`.

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
    "Check": "checks",
    "CheckResult": "checks",
    "CheckEstimate": "checks",
    "CheckError": "checks",
    "resolve_check": "checks",
    "estimate_check": "checks",
    "Modifier": "modifiers",
    "BaseModifier": "modifiers",
    "ScoreBonus": "modifiers",
    "TagBonus": "modifiers",
    "RungShift": "modifiers",
    "build_modifier": "modifiers",
    "EffectSpecError": "modifiers",
    "ResolutionContext": "pipeline",
    "StatSource": "subjects",
    "DictStatSource": "subjects",
    "get_subject": "subjects",
    "Vocabulary": "vocabulary",
    "get_vocabulary": "vocabulary",
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
