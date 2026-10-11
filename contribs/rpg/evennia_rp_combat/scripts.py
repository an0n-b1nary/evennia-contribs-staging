# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""A persistent room coordinator. No wall-clock action scheduler."""

from evennia import DefaultScript

from .engine import new_state


class CombatCoordinator(DefaultScript):
    def at_script_creation(self):
        self.key = "rp_combat_coordinator"
        self.desc = "Consent-based room combat and its retained audit journal"
        self.persistent = True
        self.interval = 60
        self.start_delay = True
        self.db.state = new_state()
        self.db.journal = []
        self.db.operations = {}
        self.db.invitations = {}

    def is_valid(self):
        return self.obj is not None

    def at_repeat(self):
        from .maintenance import maintain

        maintain(self)
