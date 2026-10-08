# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Settings for evennia_rp_equipment, with their defaults.

Every setting is read when needed, so `override_settings` works in tests.

    RP_EQUIPMENT_TYPECLASS    typeclass `+gear/make` creates
    RP_EQUIPMENT_SLOTS        the order worn lines are shown in; slots are flavour,
                              and any number of items may share one
    RP_EQUIPMENT_ITEM_CAP     most items one character's making may have in the
                              world at once (None: no cap)
    RP_EQUIPMENT_STAFF_LOCK   lockstring for +gear/audit
"""

from __future__ import annotations

from django.conf import settings

DEFAULTS = {
    "RP_EQUIPMENT_TYPECLASS": "evennia_rp_equipment.typeclasses.Equipment",
    "RP_EQUIPMENT_SLOTS": ("head", "body", "hands", "feet", "weapon", "accessory"),
    "RP_EQUIPMENT_ITEM_CAP": 20,
    "RP_EQUIPMENT_STAFF_LOCK": "cmd:perm(Builder)",
}


def get(name: str):
    """`settings.<name>`, or this contrib's default for it."""
    return getattr(settings, name, DEFAULTS[name])


def slots() -> tuple[str, ...]:
    """The configured slots, lower-cased, in order, without repeats."""
    return tuple(dict.fromkeys(str(s).strip().lower() for s in get("RP_EQUIPMENT_SLOTS") or ()))


def item_cap() -> int | None:
    return get("RP_EQUIPMENT_ITEM_CAP")
