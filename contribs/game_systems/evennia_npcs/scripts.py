# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""One persistent cleanup script; no AI or player-action timers."""

from evennia.scripts.scripts import DefaultScript

from . import conf


class NPCMaintenance(DefaultScript):
    def at_script_creation(self):
        self.key = "npc_maintenance"
        self.persistent = True
        self.interval = conf.get("NPCS_MAINTENANCE_INTERVAL")

    def at_repeat(self):
        from .services import maintain

        maintain()


def ensure_npc_script_running():
    from evennia.utils.create import create_script
    from evennia.utils.search import search_script

    if not search_script("npc_maintenance"):
        create_script(NPCMaintenance, persistent=True, autostart=True)
