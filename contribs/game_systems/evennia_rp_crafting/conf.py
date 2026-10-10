# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.conf import settings

from evennia_links.collect import resolve_dotted
from evennia_links.runtime import get, register

MAX_AMOUNT = 2**63 - 1
DEFAULT_BEHAVIOURS = {
    "wearable": "evennia_rp_crafting.behaviours.Wearable",
    "readable": "evennia_rp_crafting.behaviours.Readable",
}
DEFAULT_COSTS = {
    "wearable": {"base": {"materials": 1}, "aura_line": {"essences": 1}},
    "readable": {"base": {"materials": 1}},
}


def nonnegative(value):
    return type(value) is int and 0 <= value <= MAX_AMOUNT


def positive(value):
    return nonnegative(value) and value > 0


def boolean(value):
    return type(value) is bool


def register_controls():
    for name, default, validator in (
        ("REVEALED", True, boolean),
        ("FROZEN", False, boolean),
        ("NICHE_CAP", 5, positive),
        ("UNLOCK_STEP", 1, nonnegative),
        ("MONEY_CAP_RAISE", 100, nonnegative),
        ("RESOURCE_CAP_RAISE", 6, nonnegative),
    ):
        register(f"RP_CRAFTING_{name}", default, validator=validator)


def hook(name):
    value = getattr(settings, name, None)
    return resolve_dotted(value) if isinstance(value, str) else value


def is_staff(character):
    return bool(
        character.locks.check_lockstring(
            character, getattr(settings, "RP_CRAFTING_STAFF_LOCK", "cmd:perm(Builder)")
        )
    )


def visible(character):
    return get("RP_CRAFTING_REVEALED") or is_staff(character)


def multiplier(position):
    return 1 + get("RP_CRAFTING_UNLOCK_STEP") * (position - 1)
