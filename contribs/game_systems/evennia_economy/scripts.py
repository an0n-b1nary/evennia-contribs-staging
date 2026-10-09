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
        self.desc = "Passive income, the reveal stipend sweep and offer expiry."
        self.interval = 60
        self.persistent = True

    def at_repeat(self):
        from evennia_links.periodic import advance
        from evennia_links.runtime import get

        from .batch import note_visibility, period_key, run_due_period
        from .exchange import expire_offers

        expire_offers()
        note_visibility()
        state = self.db.batch_state
        if state is None and self.db.last_batch_week:
            # Earlier scripts stored only the last fully paid period.
            state = {"latest": self.db.last_batch_week, "pending": []}
        # Periods completing while frozen queue up and are paid once unfrozen.
        self.db.batch_state = advance(
            state,
            period_key(),
            run_due_period,
            paused=get("RP_ECONOMY_FROZEN"),
            label="Economy batch",
        )
