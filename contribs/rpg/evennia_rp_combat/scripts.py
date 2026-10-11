# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""One game-wide maintenance ticker. No wall-clock action scheduler."""

from evennia import DefaultScript


class CombatMaintenance(DefaultScript):
    """Absence and idle cleanup for every open fight; it never acts or reacts."""

    def at_script_creation(self):
        self.key = "rp_combat_maintenance"
        self.desc = "Consent-based combat absence maintenance"
        self.persistent = True
        self.interval = 60
        self.start_delay = True

    def at_repeat(self):
        from .maintenance import maintain_all

        maintain_all()
