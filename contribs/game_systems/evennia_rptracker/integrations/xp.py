# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_rptracker XP integration — RP session collector and post-batch hook.

This module ships the rptracker-domain XP feed. It is only active when
registered in the game's settings and evennia-xp is installed:

    XP_COLLECTORS += [
        ("rp_session", "evennia_rptracker.integrations.xp.collect_rp_sessions"),
    ]
    XP_POST_BATCH_HOOKS += [
        "evennia_rptracker.integrations.xp.flip_session_flags",
    ]

Register flip_session_flags as a post-batch hook so session.xp_awarded is
set only after XPLog rows are confirmed in the database (not just in memory).

Both functions import from evennia_xp at call time (not at module import), so
this file is safe to ship even when evennia-xp is not installed — it simply
can't be called meaningfully.
"""

import logging
from datetime import timedelta
from decimal import Decimal

logger = logging.getLogger("evennia")

_WINDOW_DAYS = 7


def _window_start(window_end):
    return window_end - timedelta(days=_WINDOW_DAYS)


# ---------------------------------------------------------------------------
# collect_rp_sessions
# ---------------------------------------------------------------------------


def collect_rp_sessions(window_end):
    """Yield Awards for completed RPSessions that have not yet been awarded XP.

    Eligibility is delegated to session.is_xp_eligible() (status=COMPLETED,
    duration >= 30 min, >= 1 partner, xp_awarded=False). The filter on
    activated_at__isnull=False excludes sessions that never fully activated.

    Args:
        window_end: datetime (Monday 00:00 UTC) marking the end of the window.

    Yields:
        Award for each eligible session.
    """
    return _collect(window_end, "rp_session")


def collect_rp_channel_sessions(window_end):
    """Yield uncapped IC-channel awards through the host's multiplier policy."""
    return _collect(window_end, "rp_channel_session")


def _collect(window_end, source):
    from evennia_xp.batch import Award
    from evennia_xp.gating import resolve_xp_multiplier

    from evennia_rptracker.models import RPSession

    window_start = _window_start(window_end)
    sessions = RPSession.objects.filter(
        source_type=source,
        status=RPSession.Status.COMPLETED,
        xp_awarded=False,
        activated_at__isnull=False,
        ended_at__gt=window_start,
        ended_at__lte=window_end,
    ).select_related("character", "room")

    for session in sessions:
        if session.character_id is None or not session.is_xp_eligible():
            continue
        mult = resolve_xp_multiplier(
            source,
            room=session.room,
            character=session.character,
        )
        if not mult:
            continue
        yield Award(
            character_id=session.character_id,
            amount=Decimal("1.0") * mult,
            source_type=source,
            source_ref_id=session.pk,
            multiplier=mult,
            reason=f"{'IC-channel' if source == 'rp_channel_session' else 'RP'} session #{session.pk}",
        )


# ---------------------------------------------------------------------------
# flip_session_flags  (post-batch hook)
# ---------------------------------------------------------------------------


def flip_session_flags(window_end, awards, week_label):
    """Set xp_awarded=True / xp_week on RPSessions that have XPLog rows.

    Checks the DB rather than trusting the in-memory award list so this is
    safe even if some per-character transactions rolled back.

    Args:
        window_end: datetime marking the end of the batch window (unused but
            included for signature parity with other post-batch hooks).
        awards: sequence of Award namedtuples produced by the batch run.
        week_label: ISO week string (e.g. "2026-W28") written to xp_week.
    """
    _flip_flags(awards, week_label, "rp_session")


def flip_channel_session_flags(window_end, awards, week_label):
    """Mark only channel sessions whose XP ledger writes actually committed."""
    _flip_flags(awards, week_label, "rp_channel_session")


def _flip_flags(awards, week_label, source):
    from evennia_xp.models import XPLog

    from evennia_rptracker.models import RPSession

    expected = {(a.character_id, a.source_ref_id) for a in awards if a.source_type == source}
    if not expected:
        return

    # A ledger row only confirms the award it was written for: same source,
    # same session and same character.
    awarded = {
        ref
        for character_id, ref in XPLog.objects.filter(
            source_type=source,
            source_ref_id__in={ref for _character_id, ref in expected},
        ).values_list("character_id", "source_ref_id")
        if (character_id, ref) in expected
    }
    if awarded:
        RPSession.objects.filter(pk__in=awarded, source_type=source).update(
            xp_awarded=True,
            xp_week=week_label,
        )
