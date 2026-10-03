# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Settings for evennia_rp_chargen, with their defaults.

Every setting is read when needed, so `override_settings` works in tests.

    RP_CHARGEN_STAFF_LOCK        lockstring for staff commands and +sheet on others
    RP_CHARGEN_ALLOCATION        {"path": allocation class, "params": {...}}
    RP_CHARGEN_ALLOCATION_NOUN   what allocation points are called ("build points")
    RP_CHARGEN_PIP_BUDGET        total edge a character may carry (None: no budget)
    RP_CHARGEN_PIP_CAP           most edge on one stat (None: the scale's maximum)
    RP_CHARGEN_WEAKNESS_CAP      most weakness on one stat (None: the scale's maximum)
    RP_CHARGEN_PIP_NOUN          what edge pips are called ("edge")
    RP_CHARGEN_WEAKNESS_NOUN     what weakness pips are called ("weakness")
    RP_CHARGEN_LOADOUT_NOUN      what the equipped-ability set is called ("loadout")
    RP_CHARGEN_LOCK_SCOPES       what a build lock freezes (("pips", "loadout"))
    RP_CHARGEN_LOCK_TTL          seconds after the last IC action that a lock lapses
                                 (None: only an unlock or a session end releases it)
    RP_CHARGEN_REQUIRE_APPROVAL  True: a finalized sheet needs staff approval to play
    RP_CHARGEN_RPTRACKER_APP_LABEL  app label of the RP tracker partner
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings

DEFAULTS = {
    "RP_CHARGEN_STAFF_LOCK": "cmd:perm(Builder)",
    "RP_CHARGEN_ALLOCATION": {"path": "evennia_rp_chargen.allocation.FreeAllocation"},
    "RP_CHARGEN_ALLOCATION_NOUN": "build points",
    "RP_CHARGEN_PIP_BUDGET": None,
    "RP_CHARGEN_PIP_CAP": None,
    "RP_CHARGEN_WEAKNESS_CAP": None,
    "RP_CHARGEN_PIP_NOUN": "edge",
    "RP_CHARGEN_WEAKNESS_NOUN": "weakness",
    "RP_CHARGEN_LOADOUT_NOUN": "loadout",
    "RP_CHARGEN_LOCK_SCOPES": ("pips", "loadout"),
    "RP_CHARGEN_LOCK_TTL": 3 * 60 * 60,
    "RP_CHARGEN_REQUIRE_APPROVAL": False,
    "RP_CHARGEN_RPTRACKER_APP_LABEL": "evennia_rptracker",
}

PIPS = "pips"
LOADOUT = "loadout"


def get(name: str):
    """`settings.<name>`, or this contrib's default for it."""
    return getattr(settings, name, DEFAULTS[name])


def lock_scopes() -> tuple[str, ...]:
    """The configured scopes, in their configured order, without repeats."""
    return tuple(dict.fromkeys(get("RP_CHARGEN_LOCK_SCOPES") or ()))


def lock_ttl() -> timedelta | None:
    ttl = get("RP_CHARGEN_LOCK_TTL")
    if ttl is None or isinstance(ttl, timedelta):
        return ttl
    return timedelta(seconds=ttl)


def scope_noun(scope: str) -> str:
    """Player-facing name of a lock scope ("edge", "loadout")."""
    if scope == PIPS:
        return get("RP_CHARGEN_PIP_NOUN")
    if scope == LOADOUT:
        return get("RP_CHARGEN_LOADOUT_NOUN")
    return scope


def locked_things() -> str:
    """`"edge and loadout"`: what a build lock freezes, in words."""
    nouns = [scope_noun(scope) for scope in lock_scopes()]
    if len(nouns) <= 1:
        return "".join(nouns) or "build"
    return f"{', '.join(nouns[:-1])} and {nouns[-1]}"


def require_approval() -> bool:
    return bool(get("RP_CHARGEN_REQUIRE_APPROVAL"))


def staff_lock() -> str:
    return get("RP_CHARGEN_STAFF_LOCK")
