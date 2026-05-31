# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Anti-gaming detection for RP sessions.

``sweep_rp_sessions(window_end)`` should be called before your XP collectors
run, so suspicious sessions are flagged before the collectors skip them.

Rules (volume/time-based only — quality/length heuristics are never used):

    1. Pose spam: RPSession with pose_count >= RPTRACKER_POSE_SPAM_MIN_COUNT
       AND duration < RPTRACKER_POSE_SPAM_MAX_SECONDS. Flagged via session.flag().

    2. Manual end abuse: character has >= RPTRACKER_MANUAL_END_ABUSE_COUNT
       ended_manually=True sessions within any 24-hour window inside the
       batch window. All sessions in the burst are flagged via session.flag().

Explicitly NOT flagged:
    - Exclusive-partner (one-on-one) sessions: legitimate.
    - Short posts / word count: quality is never a signal.

Each rule is idempotent: already-flagged sessions are skipped. Re-running
sweep_rp_sessions on the same window is a no-op.

When a session is newly flagged, an optional notification hook is called
(RPTRACKER_FLAG_REVIEW_HOOK setting, default no-op) so game operators can
route flags to a review queue (e.g. a staff ticket system).
"""

import logging
from datetime import timedelta

from django.conf import settings

logger = logging.getLogger("evennia")

_WINDOW_DAYS = 7


def _window_start(window_end):
    return window_end - timedelta(days=_WINDOW_DAYS)


def _notify_flag_review(title, description):
    """Call the optional RPTRACKER_FLAG_REVIEW_HOOK setting, if configured.

    The hook receives (title, description) and is expected to create a staff
    review notification. If no hook is configured, or if the call raises,
    this is silent so a misconfigured hook never blocks flagging.
    """
    hook_path = getattr(settings, "RPTRACKER_FLAG_REVIEW_HOOK", None)
    if not hook_path:
        return
    try:
        from django.utils.module_loading import import_string

        hook = import_string(hook_path)
        hook(title, description)
    except Exception:
        logger.exception("rptracker.antigaming: RPTRACKER_FLAG_REVIEW_HOOK raised for %r", title)


def _flag_pose_spam(window_end):
    """Flag sessions with high pose count and very short duration."""
    from evennia_rptracker.models import RPSession

    min_count = getattr(settings, "RPTRACKER_POSE_SPAM_MIN_COUNT", 20)
    max_seconds = getattr(settings, "RPTRACKER_POSE_SPAM_MAX_SECONDS", 600)

    window_start = _window_start(window_end)
    candidates = RPSession.objects.filter(
        status=RPSession.Status.COMPLETED,
        xp_awarded=False,
        pose_count__gte=min_count,
        ended_at__gt=window_start,
        ended_at__lte=window_end,
        activated_at__isnull=False,
    ).exclude(status=RPSession.Status.FLAGGED)

    flagged = 0
    for session in candidates:
        duration = session.duration_seconds()
        if duration <= 0 or duration >= max_seconds:
            continue

        reason = (
            f"Auto-flag: pose spam — {session.pose_count} poses in "
            f"{duration}s ({duration / session.pose_count:.1f}s avg inter-pose)"
        )
        session.flag(reason)
        _notify_flag_review(
            title=f"Auto-flag: pose spam — {session.character_name}",
            description=(
                f"RPSession #{session.pk} by {session.character_name} was "
                f"auto-flagged for pose spam.\n\n"
                f"Poses: {session.pose_count}  Duration: {duration}s  "
                f"Avg inter-pose: {duration / session.pose_count:.1f}s\n\n"
                f"Review and unflag if legitimate."
            ),
        )
        flagged += 1

    if flagged:
        logger.info("rptracker.antigaming: pose spam — flagged %d session(s)", flagged)


def _flag_manual_end_abuse(window_end):
    """Flag characters with too many manually-ended sessions in a 24h window."""
    from evennia_rptracker.models import RPSession

    abuse_count = getattr(settings, "RPTRACKER_MANUAL_END_ABUSE_COUNT", 3)
    window_start = _window_start(window_end)
    manually_ended = (
        RPSession.objects.filter(
            ended_manually=True,
            ended_at__gt=window_start,
            ended_at__lte=window_end,
        )
        .exclude(status=RPSession.Status.FLAGGED)
        .order_by("character_id", "ended_at")
    )

    by_char = {}
    for session in manually_ended:
        by_char.setdefault(session.character_id, []).append(session)

    flagged_chars = 0
    for _char_id, sessions in by_char.items():
        burst = _find_burst(sessions, count=abuse_count, window_hours=24)
        if not burst:
            continue

        char_name = sessions[0].character_name
        reason = f"Auto-flag: manual end abuse — {len(burst)} manual session ends within 24h"
        for session in burst:
            session.flag(reason)

        _notify_flag_review(
            title=f"Auto-flag: manual end abuse — {char_name}",
            description=(
                f"{char_name} manually ended {len(burst)} RP sessions within 24 hours.\n\n"
                f"Session IDs: {', '.join(str(s.pk) for s in burst)}\n\n"
                f"Review and unflag if legitimate."
            ),
        )
        flagged_chars += 1

    if flagged_chars:
        logger.info(
            "rptracker.antigaming: manual end abuse — flagged sessions for %d character(s)",
            flagged_chars,
        )


def _find_burst(items, *, count, window_hours):
    """Return the first group of *count* items within *window_hours* of each other."""
    window = timedelta(hours=window_hours)
    for i in range(len(items) - count + 1):
        start_time = _item_time(items[i])
        end_time = _item_time(items[i + count - 1])
        if start_time and end_time and (end_time - start_time) <= window:
            return items[i : i + count]
    return []


def _item_time(item):
    """Return the relevant datetime for a session."""
    if hasattr(item, "ended_at"):
        return item.ended_at
    return None


def sweep_rp_sessions(window_end):
    """Flag suspicious RP sessions before XP collectors run.

    Call this before your XP collectors so flagged sessions are excluded
    from awards. Idempotent — safe to re-run on the same window.

    Args:
        window_end: datetime marking the end of the batch window.
    """
    logger.info("rptracker.antigaming: sweep starting for window_end=%s", window_end)
    _flag_pose_spam(window_end)
    _flag_manual_end_abuse(window_end)
    logger.info("rptracker.antigaming: sweep complete")
