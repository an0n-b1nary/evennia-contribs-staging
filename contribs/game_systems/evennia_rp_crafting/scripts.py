# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from evennia.scripts.scripts import DefaultScript


class AmbientScript(DefaultScript):
    def at_script_creation(self):
        self.key = "rp_crafting_ambients"
        self.desc = "Bounded fixture ambience and temporary-layer cleanup."
        self.interval = 60
        self.persistent = True
        self.start_delay = True

    def at_repeat(self):
        from .companions import ambient_tick as companion_tick
        from .fixtures import ambient_tick

        ambient_tick()
        companion_tick()
