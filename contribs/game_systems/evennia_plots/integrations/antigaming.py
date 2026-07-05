# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Plot-domain anti-gaming detection sweep for evennia_plots.

Register ``sweep`` in ``XP_ANTIGAMING_SWEEPS``::

    # settings.py
    XP_ANTIGAMING_SWEEPS = [
        ...
        "evennia_plots.integrations.antigaming.sweep",
    ]

Rules (volume / time-based only — quality and length heuristics are never used):

    Thread gaming: PlotThread concluded within 24h of creation. Zeroes out
    bonus_xp_computed and sets bonus_xp_flag_reason.

Explicitly NOT flagged:

- Exclusive-partner sessions: one-on-one RP is legitimate.
- Short update content: word count / post length is not a quality signal.

Each rule is idempotent: already-flagged items (bonus_xp_flag_reason != "")
are skipped. Re-running sweep on the same window is a no-op.

**Optional Job-ticket integration:** when a thread is flagged, ``_create_job``
attempts to create a DISCUSS-type Job ticket for staff review. If the jobs app
is not installed (``JobType`` import fails), the flag is still written and the
exception is logged silently. Staff must review flagged threads and either
restore bonus_xp_computed or confirm the flag via their preferred tool.
"""

import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

_WINDOW_DAYS = 7


def _window_start(window_end):
    return window_end - timedelta(days=_WINDOW_DAYS)


def _create_job(title, description):
    """Create a DISCUSS-type Job ticket for staff review. Silent on import error.

    This is an optional integration: if the jobs app is not installed, the flag
    is still written to PlotThread.bonus_xp_flag_reason and logged; only the
    automatic ticket creation is skipped.
    """
    try:
        from evennia_jobs.models import Job, JobType

        Job.create_job(
            job_type=JobType.DISCUSS,
            author=None,
            title=title,
            description=description,
        )
    except Exception:
        logger.exception(
            "evennia_plots.integrations.antigaming: failed to create job for %r", title
        )


def _flag_thread_gaming(window_end):
    """Zero bonus XP for threads concluded within 24h of creation."""
    from evennia_plots.models import PlotThread

    window_start = _window_start(window_end)
    concluded = PlotThread.objects.filter(
        status=PlotThread.Status.CONCLUDED,
        bonus_xp_computed__gt=0,
        bonus_xp_flag_reason="",
        concluded_at__gt=window_start,
        concluded_at__lte=window_end,
    )

    flagged = 0
    for thread in concluded:
        if thread.concluded_at is None or thread.created_at is None:
            continue
        age = (thread.concluded_at - thread.created_at).total_seconds()
        if age < 0 or age >= 86400:
            continue

        reason = f"Auto-flag: thread gaming - concluded {age / 3600:.1f}h after creation"
        PlotThread.objects.filter(pk=thread.pk).update(
            bonus_xp_computed=0,
            bonus_xp_flag_reason=reason,
        )
        _create_job(
            title=f"Auto-flag: thread gaming - #{thread.plot_number} {thread.name}",
            description=(
                f"PlotThread #{thread.pk} '{thread.name}' was concluded "
                f"{age / 3600:.1f}h after creation.\n\n"
                f"Bonus XP has been zeroed. Review and restore bonus_xp_computed "
                f"and clear bonus_xp_flag_reason if the conclusion was legitimate."
            ),
        )
        flagged += 1

    if flagged:
        logger.info(
            "evennia_plots.integrations.antigaming: thread gaming - flagged %d thread(s)", flagged
        )


def sweep(window_end):
    """Flag plot-domain items before collectors run.

    Called by the XP batch processor before collectors run. Flags threads that
    were concluded too quickly (within 24h of creation) and zeroes their bonus XP.

    Args:
        window_end: datetime (Monday 00:00 UTC) marking the end of the batch window.
    """
    logger.info(
        "evennia_plots.integrations.antigaming: sweep starting for window_end=%s", window_end
    )
    _flag_thread_gaming(window_end)
    logger.info("evennia_plots.integrations.antigaming: sweep complete")
