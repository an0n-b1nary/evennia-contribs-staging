# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Settings for evennia_rp_equipment, with their defaults.

Every setting is read when needed, so `override_settings` works in tests.

    RP_EQUIPMENT_TYPECLASS    typeclass `+gear/make` creates
    RP_EQUIPMENT_SLOTS        the order worn lines are shown in; slots are flavour,
                              and any number of items may share one
    RP_EQUIPMENT_SLOT_COVERS  outer slot -> inner slots hidden from ordinary looks
    RP_EQUIPMENT_ITEM_CAP     most items one character's making may have in the
                              world at once (None: no cap)
    RP_EQUIPMENT_STAFF_LOCK   lockstring for +gear/audit
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

DEFAULTS = {
    "RP_EQUIPMENT_TYPECLASS": "evennia_rp_equipment.typeclasses.Equipment",
    "RP_EQUIPMENT_SLOTS": ("head", "body", "hands", "feet", "weapon", "accessory"),
    "RP_EQUIPMENT_SLOT_COVERS": {},
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


def slot_covers() -> dict[str, tuple[str, ...]]:
    """Normalized covering rules. Cycles (including self-covering) are host errors."""
    raw = get("RP_EQUIPMENT_SLOT_COVERS")
    if not isinstance(raw, dict):
        raise ImproperlyConfigured("RP_EQUIPMENT_SLOT_COVERS must map slots to lists of slots.")
    result = {}
    for slot, covered in raw.items():
        if not isinstance(slot, str) or not slot.strip() or not isinstance(covered, (list, tuple)):
            raise ImproperlyConfigured("RP_EQUIPMENT_SLOT_COVERS must map slots to lists of slots.")
        if any(not isinstance(target, str) or not target.strip() for target in covered):
            raise ImproperlyConfigured("RP_EQUIPMENT_SLOT_COVERS needs nonempty slot names.")
        result[slot.strip().lower()] = tuple(dict.fromkeys(s.strip().lower() for s in covered))

    visited, active = set(), set()

    def visit(slot):
        if slot in active:
            raise ImproperlyConfigured("RP_EQUIPMENT_SLOT_COVERS cannot contain covering cycles.")
        if slot in visited:
            return
        active.add(slot)
        for target in result.get(slot, ()):
            visit(target)
        active.remove(slot)
        visited.add(slot)

    for slot in result:
        visit(slot)
    return result
