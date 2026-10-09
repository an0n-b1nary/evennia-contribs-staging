# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from evennia import DefaultScript


def ensure_economy_script_running():
    from evennia.utils.create import create_script
    from evennia.utils.search import search_script

    if not search_script("economy_batch"):
        create_script(
            "evennia_economy.scripts.EconomyBatchScript", key="economy_batch", persistent=True
        )


class EconomyBatchScript(DefaultScript):
    def at_script_creation(self):
        self.key = "economy_batch"
        self.desc = "Passive income, eligibility stipends and offer expiry."
        self.interval = 60
        self.persistent = True

    def at_repeat(self):
        from .batch import period_key, run_stipends, run_weekly_batch
        from .exchange import expire_offers

        expire_offers()
        run_stipends()
        week = period_key()
        if self.db.last_batch_week != week:
            result = run_weekly_batch(week)
            if not result["errors"] and not result["frozen"]:
                self.db.last_batch_week = week
