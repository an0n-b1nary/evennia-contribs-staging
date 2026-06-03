# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Evennia Script for the weekly XP batch.

XPBatchScript checks once per hour whether the Monday 00:00 UTC boundary for
the current week has been crossed, and runs run_weekly_batch() if it hasn't
been run for the completed week yet.  Idempotency is enforced via
db.last_batch_week — re-running after a server restart is a safe no-op.

ensure_xp_batch_script_running() should be called from the game's
at_server_start() to start the Script if it isn't already running::

    # In your game's at_server_start():
    from evennia_xp.scripts import ensure_xp_batch_script_running
    ensure_xp_batch_script_running()
"""

import logging

logger = logging.getLogger("evennia")


def ensure_xp_batch_script_running():
    """Create XPBatchScript if it is not already running.

    Called by the game's at_server_start(). Safe to call multiple times.
    """
    from evennia.utils.search import search_script

    existing = search_script("xp_batch")
    if not existing:
        from evennia.utils.create import create_script

        create_script(
            "evennia_xp.scripts.XPBatchScript",
            key="xp_batch",
            persistent=True,
            autostart=True,
        )
        logger.info("XP batch: Script started.")


try:
    from evennia import DefaultScript

    class XPBatchScript(DefaultScript):
        """
        Evennia Script that runs the weekly XP batch on Monday 00:00 UTC.

        Checks every hour whether the batch for the most recently completed
        ISO week has already been run.  Tracks the last-processed week in
        db.last_batch_week so server restarts are safe.
        """

        def at_script_creation(self):
            self.key = "xp_batch"
            self.desc = "Runs the weekly XP batch every Monday at 00:00 UTC."
            self.interval = 3600  # hourly check
            self.persistent = True

        def at_repeat(self):
            """Fire on each hourly tick; run the batch when the week boundary has passed."""
            from evennia_xp.batch import (
                _last_monday_00_utc,
                _week_str_from_window_end,
            )

            window_end = _last_monday_00_utc()
            target_week = _week_str_from_window_end(window_end)

            last_run = self.db.last_batch_week or ""
            if last_run == target_week:
                return  # already ran this week

            logger.info("XP batch Script: running batch for week=%s", target_week)
            try:
                from evennia_xp.batch import run_weekly_batch

                summary = run_weekly_batch(week=target_week)
                self.db.last_batch_week = target_week
                logger.info(
                    "XP batch Script: complete — week=%s awards=%d xp=%s errors=%d",
                    summary.week,
                    summary.total_awards,
                    summary.total_xp,
                    len(summary.errors),
                )
            except Exception:
                logger.exception(
                    "XP batch Script: run_weekly_batch raised an exception " "for week=%s",
                    target_week,
                )

except ImportError:
    # Running outside Evennia (e.g. plain Django shell / management commands).
    # XPBatchScript is unavailable but ensure_xp_batch_script_running and
    # all batch functions remain usable.
    pass
