# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Host policy and durable rollout switches, read on each operation."""

from django.conf import settings

DEFAULTS = {
    "NPCS_STAFF_LOCK": "cmd:perm(Builder)",
    "NPCS_TYPECLASS": "evennia_npcs.typeclasses.NPCCharacter",
    "NPCS_IDLE_OWNER_DAYS": 60,
    "NPCS_SPAWN_IDLE_SECONDS": 86400,
    "NPCS_MAINTENANCE_INTERVAL": 300,
    "NPCS_ALLOW_FULL_PUPPET": False,
    "NPCS_SCENES_APP_LABEL": "evennia_scenes",
    "NPCS_PLOTS_APP_LABEL": "evennia_plots",
}


def get(name):
    return getattr(settings, name, DEFAULTS[name])


def is_bool(value):
    return type(value) is bool


def register_runtime():
    from evennia_links.runtime import register

    for name, default, description in (
        ("NPCS_REVEALED", False, "Expose NPCs to players."),
        (
            "NPCS_FROZEN",
            False,
            "Pause NPC writes and portrayal; release and despawn remain available.",
        ),
        ("NPCS_COMBAT_PROFILES_REVEALED", False, "Expose durable combat profile editing."),
    ):
        register(name, default, validator=is_bool, description=description)
