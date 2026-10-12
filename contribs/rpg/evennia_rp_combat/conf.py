# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Host configuration and independent rollout controls."""

from evennia_rp_rules._config import setting

DEFAULTS = {
    "RP_COMBAT_PARTNERS": {},
    "RP_COMBAT_SOURCE": None,
    "RP_COMBAT_WEAPON_FLAVOR": None,
    "RP_COMBAT_ROLES": {
        "attack": "strength",
        "attack_defense": "endurance",
        "spell": "intellect",
        "spell_defense": "intuition",
        "dispirit": "presence",
        "will": "resolve",
        "agility": "agility",
    },
    "RP_COMBAT_SCORE_BASES": (-20, -10, 0, 10, 20),
    "RP_COMBAT_EDGE_FACTORS": (1, ".9", ".8", ".7", ".6"),
    "RP_COMBAT_DOMAIN_EFFECTS": {},
    "RP_COMBAT_ELEMENT_TRAITS": {},
    "RP_COMBAT_ELEMENT_KIND": "style",
    "RP_COMBAT_STAFF_LOCK": "cmd:perm(Builder)",
    "RP_COMBAT_TURN_LIMIT": 4,
    # Connection idle (no command from the player at all), not combat idle.
    "RP_COMBAT_IDLE_SECONDS": 3600,
    "RP_COMBAT_RULES": {},
    "RP_COMBAT_NPC_MOVES": {},
    "RP_COMBAT_TACTICS_LIMIT": 8,
    "RP_COMBAT_CHARGEN_APP_LABEL": "evennia_rp_chargen",
}


def get(name):
    return setting(name, DEFAULTS[name])


def boolean(value):
    return type(value) is bool


def register_runtime():
    from evennia_links.runtime import register

    for name, description in (
        ("RP_COMBAT_REVEALED", "Expose combat commands and participation."),
        ("RP_COMBAT_FROZEN", "Pause new combat progress; inspection and safe cancellation remain."),
        ("RP_COMBAT_TACTICS_REVEALED", "Expose durable Tactics editing."),
    ):
        register(name, False, validator=boolean, description=description)
