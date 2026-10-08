# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Find worn gear whose requirements no longer hold.

The change guard keeps worn gear's requirements met through every build
change. Two things go around it, because they change the rules rather than a
character: editing the ruleset or catalog (a stat or ability renamed or
removed), and writing to a sheet without the chargen services. `problems()`
lists the results for staff to settle by hand. Nothing is changed for them.

Run it from `+gear/audit`, `evennia rp_equipment_audit`, or the game's
`at_server_start()`::

    from evennia_rp_equipment.audit import log_problems
    log_problems()
"""

from __future__ import annotations

import logging

from evennia_rp_equipment.display import is_equipment
from evennia_rp_equipment.requirements import UNKNOWN, UNMET, describe, status
from evennia_rp_equipment.typeclasses import TAG_CATEGORY, WORN_TAG

logger = logging.getLogger("evennia")


def problems() -> list[str]:
    """One line per worn item requirement that's unmet or names something unknown."""
    from evennia.objects.models import ObjectDB

    found = []
    for item in ObjectDB.objects.get_by_tag(WORN_TAG, category=TAG_CATEGORY).order_by("id"):
        if not is_equipment(item):
            continue
        wearer = item.location
        if wearer is None:
            found.append(f"{item.key} (#{item.id}) is marked worn but nobody carries it.")
            continue
        for req in item.get_requirements():
            state = status(wearer, req)
            if state == UNKNOWN:
                found.append(
                    f"{wearer.key}'s {item.key} (#{item.id}) requires {describe(req)}, "
                    "which this game no longer has."
                )
            elif state == UNMET:
                found.append(
                    f"{wearer.key}'s {item.key} (#{item.id}) requires {describe(req)}, "
                    "which isn't met."
                )
    return found


def log_problems() -> list[str]:
    """`problems()`, each logged as a warning. For `at_server_start()`."""
    found = problems()
    for line in found:
        logger.warning("rp_equipment audit: %s", line)
    return found


__all__ = ["log_problems", "problems"]
