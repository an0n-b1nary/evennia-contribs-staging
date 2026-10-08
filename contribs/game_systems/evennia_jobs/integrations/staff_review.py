# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Staff-review reporter: file a ``+discuss`` ticket for an automated flag.

Several contribs raise flags that a person should look at, and each exposes a
dotted-path setting taking ``callable(title, description)`` so it never has to
import a ticket system. This module is that callable for evennia-jobs::

    # settings.py
    RPTRACKER_FLAG_REVIEW_HOOK = "evennia_jobs.integrations.staff_review.file_review_job"
    BOARDS_ANTIGAMING_REPORTER = "evennia_jobs.integrations.staff_review.file_review_job"

Tickets are ``DISCUSS`` jobs with no author. ``+discuss`` is the staff-only
type (non-staff never see it on the web or through the API), so a player is
not told they were flagged before staff have looked.

Errors propagate. Both shipped callers catch and log them, so a failed ticket
never stops the flag itself from being recorded.
"""


def file_review_job(title, description):
    """File an authorless DISCUSS ticket and return the new Job.

    Args:
        title (str): Short ticket title.
        description (str): Full ticket body, with whatever context the
            flagging contrib supplies.
    """
    from evennia_jobs.models import Job, JobType

    return Job.create_job(
        job_type=JobType.DISCUSS,
        author=None,
        title=title,
        description=description,
    )
