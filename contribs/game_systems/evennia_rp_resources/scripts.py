# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Minute boundary check, without a dependency on XP's batch script."""

from evennia import DefaultScript


def ensure_resource_script_running():
    from evennia.utils.create import create_script
    from evennia.utils.search import search_script

    if not search_script("rp_resources_batch"):
        create_script(
            "evennia_rp_resources.scripts.ResourceBatchScript",
            key="rp_resources_batch",
            persistent=True,
        )


class ResourceBatchScript(DefaultScript):
    def at_script_creation(self):
        self.key = "rp_resources_batch"
        self.desc = "Passive resource accrual on the configured Monday-anchored boundary."
        self.interval = 60
        self.persistent = True

    def at_repeat(self):
        from evennia_links.periodic import advance

        from .batch import period_key, run_due_period

        state = self.db.batch_state
        if state is None and self.db.last_batch_week:
            # 0.1.0 scripts stored only the last fully paid period.
            state = {"latest": self.db.last_batch_week, "pending": []}
        self.db.batch_state = advance(state, period_key(), run_due_period, label="Resources batch")
