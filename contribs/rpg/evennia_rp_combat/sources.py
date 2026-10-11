# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Snapshot generic kernel stat sources using combat's separate score mapping."""

from collections.abc import Mapping
from fractions import Fraction as Q

from evennia_rp_rules._config import resolve_dotted
from evennia_rp_rules.subjects import get_subject

from . import conf
from .data import Build, CombatError


def combat_score(rating):
    bases = tuple(Q(str(v)) for v in conf.get("RP_COMBAT_SCORE_BASES"))
    factors = tuple(Q(str(v)) for v in conf.get("RP_COMBAT_EDGE_FACTORS"))
    index = rating.scale.index(rating.rung)
    if len(rating.scale.rungs) != len(bases) or len(bases) != len(factors):
        raise CombatError("The host's combat score table must match the stat scale's rungs.")
    pips = rating.net_pips
    if not -5 <= pips <= 5:
        raise CombatError("Combat supports net pips from -5 through +5.")
    positive = (Q(2), Q(3, 2), Q(1), Q(3, 4), Q(1, 2))
    negative = (Q(1, 2), Q(3, 4), Q(1), Q(5, 4), Q(3, 2))
    return bases[index] + (
        sum(positive[:pips]) * factors[index] if pips >= 0 else -sum(negative[:-pips])
    )


def snapshot(obj):
    path = conf.get("RP_COMBAT_SOURCE")
    if path:
        build = resolve_dotted(path)(obj)
        if build is not None:
            if not isinstance(build, Build):
                raise CombatError("The combat source must return an immutable Build.")
            return build
    # An optional installed chargen sheet owns playable-state validation and
    # equipped moves. Never import this adapter when the partner is absent.
    if not isinstance(obj, Mapping) and not hasattr(obj, "get_rating"):
        from django.apps import apps

        if apps.is_installed(conf.get("RP_COMBAT_CHARGEN_APP_LABEL")):
            from .integrations import chargen_build

            build = chargen_build(obj)
            if build is not None:
                return build
    source = get_subject(obj)
    if source is None:
        raise CombatError("No combat stat source is available.")
    return from_source(source)


def from_source(source, *, moves=(), abilities=(), effects=(), flaws=()):
    scores = []
    for role, stat in conf.get("RP_COMBAT_ROLES").items():
        rating = source.get_rating(stat)
        if isinstance(rating, str):
            from evennia_rp_rules.ruleset import get_ruleset

            rating = get_ruleset().stats[stat].scale.parse(rating)
        if rating is None:
            raise CombatError(f"The build needs a valid {stat} rating.")
        scores.append((role, str(combat_score(rating))))
    return Build(tuple(scores), tuple(moves), tuple(effects), tuple(abilities), tuple(flaws))
