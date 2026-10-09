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
        from .batch import period_key, run_weekly_batch

        week = period_key()
        if self.db.last_batch_week != week:
            result = run_weekly_batch(week)
            if not result["errors"]:
                self.db.last_batch_week = week
