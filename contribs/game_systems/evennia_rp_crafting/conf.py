# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.conf import settings

from evennia_links.collect import resolve_dotted
from evennia_links.runtime import get, register

MAX_AMOUNT = 2**63 - 1
DEFAULT_BEHAVIOURS = {
    "carried": "evennia_rp_crafting.behaviours.Carried",
    "wearable": "evennia_rp_crafting.behaviours.Wearable",
    "readable": "evennia_rp_crafting.behaviours.Readable",
    "consumable": "evennia_rp_crafting.behaviours.Consumable",
    "broadcast": "evennia_rp_crafting.behaviours.Broadcast",
    "installable": "evennia_rp_crafting.wave_two.Installable",
    "activatable": "evennia_rp_crafting.wave_two.Activatable",
    "companion": "evennia_rp_crafting.companions.Companion",
    "modifier_aura": "evennia_rp_crafting.modifiers.Modifier",
    "modifier_mark": "evennia_rp_crafting.modifiers.Mark",
    "modifier_dye": "evennia_rp_crafting.modifiers.Dye",
    "modifier_engrave": "evennia_rp_crafting.modifiers.Engrave",
    "modifier_undo": "evennia_rp_crafting.modifiers.Undo",
}
# Each entry is a complete verb set, not independently composable permissions.
DEFAULT_COMBINATIONS = {
    "carried": [["readable"], ["activatable"], ["readable", "activatable"]],
    "wearable": [[], ["activatable"]],
    "installable": [[], ["activatable"], ["readable"], ["readable", "activatable"]],
    "consumable": [[]],
    "broadcast": [[]],
    "companion": [[], ["activatable"]],
}
DEFAULT_COSTS = {
    "signet": {"base": {"materials": 1}},
    "companion": {"base": {"materials": 1}, "ambient": {"essences": 1}},
    "modifier_aura": {"base": {"essences": 1}},
    "modifier_mark": {"base": {"essences": 1}},
    "modifier_dye": {"base": {"materials": 1}},
    "modifier_engrave": {"base": {"materials": 1}},
    "modifier_undo": {"base": {"essences": 1}},
    "wearable": {"base": {"materials": 1}, "aura_line": {"essences": 1}},
    "readable": {"base": {"materials": 1}, "extra_page": {"materials": 1}},
    "consumable": {"base": {"provisions": 1}, "extra_beat": {"provisions": 1}},
    "broadcast": {"base": {"essences": 1}, "extra_beat": {"essences": 1}},
    "installable": {"base": {"materials": 1}, "ambient": {"essences": 1}},
    "activatable": {
        "base": {"materials": 1},
        "extra_mode": {"materials": 1},
        "extra_reading": {"essences": 1},
    },
}


def nonnegative(value):
    return type(value) is int and 0 <= value <= MAX_AMOUNT


def positive(value):
    return nonnegative(value) and value > 0


def boolean(value):
    return type(value) is bool


def cooldown(value):
    return type(value) is int and 1 <= value <= 86400


def days(value):
    return type(value) is int and 1 <= value <= 3650


def register_controls():
    for name, default, validator in (
        ("REVEALED", True, boolean),
        ("WAVE_TWO_REVEALED", True, boolean),
        ("WAVE_THREE_REVEALED", True, boolean),
        ("FROZEN", False, boolean),
        ("NICHE_CAP", 5, positive),
        ("UNLOCK_STEP", 1, nonnegative),
        ("MONEY_CAP_RAISE", 100, nonnegative),
        ("RESOURCE_CAP_RAISE", 6, nonnegative),
        ("EVENT_ROOM_COOLDOWN", 30, cooldown),
        ("ACTIVATION_ITEM_COOLDOWN", 30, cooldown),
        ("FIXTURE_ROOM_LIMIT", 5, positive),
        ("TEMPORARY_LAYER_LIMIT", 3, positive),
        ("TEMPORARY_LAYER_SECONDS", 3600, cooldown),
        ("AMBIENT_INTERVAL", 300, cooldown),
        ("PATTERNS_REVEALED", True, boolean),
        ("PATTERN_COMMON_DAYS", 90, days),
        ("PATTERN_TEACH_DAYS", 7, days),
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


def wave_two_visible(character):
    return visible(character) and (get("RP_CRAFTING_WAVE_TWO_REVEALED") or is_staff(character))


def component_visible(character, key):
    if key == "companion" or key.startswith("modifier_"):
        return wave_three_visible(character)
    return key not in ("installable", "activatable") or wave_two_visible(character)


def wave_three_visible(character):
    return visible(character) and (get("RP_CRAFTING_WAVE_THREE_REVEALED") or is_staff(character))


def multiplier(position):
    return 1 + get("RP_CRAFTING_UNLOCK_STEP") * (position - 1)
