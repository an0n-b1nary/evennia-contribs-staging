# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Resolution phases, sides, and visibility: the pipeline's shared vocabulary.

Phases are the named moments a modifier can hook. The full list is fixed now
so the kernel's vocabulary doesn't change when combat arrives, but a plain
check only runs three of them:

    DECLARE          reserved (combat): riders attach to an action
    BUILD            adjust ratings and scores
    OFFER_REACTIONS  reserved (combat): a defender is shown reactions and odds
    REACTION_CHOSEN  reserved (combat): the defender's pick is locked in
    PRE_RESOLVE      last adjustments, made seeing everything BUILD added
    ON_OUTCOME       after the roll: notes and side effects; numbers are settled

Sides are absolute: `ACTOR` is whoever makes the check and `TARGET` is the
difficulty or the opponent.

Visibility says who may see a modifier, and so whose estimates include it:

    OPEN    anyone shown the breakdown
    HIDDEN  staff and the side that owns the modifier (an attacker's feint)
    SECRET  staff only (a storyteller's private thumb on the scale)
"""

from __future__ import annotations

DECLARE = "declare"
BUILD = "build"
OFFER_REACTIONS = "offer_reactions"
REACTION_CHOSEN = "reaction_chosen"
PRE_RESOLVE = "pre_resolve"
ON_OUTCOME = "on_outcome"

PHASES = (DECLARE, BUILD, OFFER_REACTIONS, REACTION_CHOSEN, PRE_RESOLVE, ON_OUTCOME)
CHECK_PHASES = (BUILD, PRE_RESOLVE, ON_OUTCOME)

ACTOR = "actor"
TARGET = "target"
SIDES = (ACTOR, TARGET)

OPEN = "open"
HIDDEN = "hidden"
SECRET = "secret"
VISIBILITIES = (OPEN, HIDDEN, SECRET)

# Viewers for `CheckResult.entries_for()` and `estimate_check(viewer=...)`.
STAFF = "staff"
PUBLIC = "public"
VIEWERS = (STAFF, ACTOR, TARGET, PUBLIC)


def other_side(side: str) -> str:
    return TARGET if side == ACTOR else ACTOR


def visible_to(visibility: str, owner: str, viewer: str) -> bool:
    """Whether `viewer` may see something of `visibility` owned by side `owner`."""
    if viewer == STAFF or visibility == OPEN:
        return True
    return visibility == HIDDEN and viewer == owner


__all__ = [
    "ACTOR",
    "BUILD",
    "CHECK_PHASES",
    "DECLARE",
    "HIDDEN",
    "OFFER_REACTIONS",
    "ON_OUTCOME",
    "OPEN",
    "PHASES",
    "PRE_RESOLVE",
    "PUBLIC",
    "REACTION_CHOSEN",
    "SECRET",
    "SIDES",
    "STAFF",
    "TARGET",
    "VIEWERS",
    "VISIBILITIES",
    "other_side",
    "visible_to",
]
