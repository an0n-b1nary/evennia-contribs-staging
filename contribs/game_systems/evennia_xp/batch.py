# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
XP weekly batch engine for evennia_xp.

Public API:
    run_weekly_batch(week=None, *, dry_run=False, sources=None) -> BatchSummary

The batch:
1. Runs every callable in settings.XP_ANTIGAMING_SWEEPS before collectors.
2. Runs every collector registered in settings.XP_COLLECTORS and accumulates
   Award tuples.
3. If dry_run=True, returns a summary without writing anything.
4. Otherwise, writes XPLog rows per-character in isolated atomic transactions so
   one bad character does not roll back the whole batch.
5. Calls every callable in settings.XP_POST_BATCH_HOOKS after all writes.
6. Fires xp_batch_completed signal with the BatchSummary.

Registry conventions:
  XP_COLLECTORS      — list of (key, "dotted.path") pairs.
                        Each function has signature fn(window_end) → iterable[Award].
  XP_ANTIGAMING_SWEEPS — list of "dotted.path" strings.
                          Each function has signature sweep(window_end).
  XP_POST_BATCH_HOOKS  — list of "dotted.path" strings.
                          Each function has signature hook(window_end, awards, week_label).

Award namedtuple fields:
    character_id  — ObjectDB pk of the recipient.
    amount        — Decimal XP (base rate * multiplier).
    source_type   — XPLog.SourceType choice string.
    source_ref_id — PK of the eligibility row that uniquely identifies this award.
    multiplier    — The Decimal multiplier that was applied (for audit).
    reason        — Short human-readable description stored in XPLog.reason.

BatchSummary namedtuple fields:
    week         — ISO week string processed, e.g. "2026-W18"
    total_awards — total number of XPLog rows written (or would be written)
    total_xp     — Decimal sum of all amounts
    by_source    — dict[source_type_str -> {"count": int, "total": Decimal}]
    errors       — list of error strings from per-char transactions
"""

import logging
from collections import defaultdict, namedtuple
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import import_module

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("evennia")

Award = namedtuple(
    "Award",
    ["character_id", "amount", "source_type", "source_ref_id", "multiplier", "reason"],
)

BatchSummary = namedtuple(
    "BatchSummary", ["week", "total_awards", "total_xp", "by_source", "errors"]
)

# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------


def _last_monday_00_utc(reference=None):
    """Return the most recent Monday 00:00:00 UTC at or before *reference*.

    If *reference* is already Monday 00:00:00 UTC, returns it unchanged (so
    running the batch exactly at the boundary processes the just-completed week).
    """
    if reference is None:
        reference = timezone.now()
    # Convert to UTC-aware for arithmetic.
    now_utc = reference.astimezone(UTC)
    day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    # weekday(): Mon=0 … Sun=6.  Roll back to the last Monday.
    days_back = day_start.weekday()
    return day_start - timedelta(days=days_back)


def _week_str_from_window_end(window_end):
    """Return the ISO week string for the week that *window_end* closes.

    window_end is Monday 00:00 UTC; the preceding Sunday belongs to the
    target week, e.g. 2026-W18.
    """
    prev = window_end - timedelta(seconds=1)
    iso = prev.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _window_end_from_week_str(week_str):
    """Parse "YYYY-Www" into the Monday 00:00 UTC that closes that week.

    E.g. "2026-W18" → 2026-05-04 00:00:00 UTC (start of W19 = end of W18).
    """
    year_str, w_str = week_str.split("-W")
    year, week = int(year_str), int(w_str)
    monday = datetime.fromisocalendar(year, week, 1)  # naive Monday of target week
    # window_end = the following Monday 00:00 UTC
    window_end_naive = monday + timedelta(days=7)
    return window_end_naive.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Registry resolver
# ---------------------------------------------------------------------------


def _resolve_dotted(path):
    """Import and return the callable at *path* (e.g. 'myapp.module.func').

    Raises ImportError or AttributeError if the path cannot be resolved.
    """
    module_path, _, attr = path.rpartition(".")
    return getattr(import_module(module_path), attr)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_weekly_batch(week=None, *, dry_run=False, sources=None):
    """Run the weekly XP batch.

    Args:
        week: ISO week string "YYYY-Www" to process, e.g. "2026-W18".
            Defaults to the most recently completed ISO week.
        dry_run: If True, compute awards and return the summary without
            writing any XPLog rows or calling post-batch hooks.
        sources: Optional iterable of source-key strings to limit which
            collectors run, e.g. ["rp_session", "lore_authored"]. Useful
            for debugging or targeted backfills. None runs all collectors.

    Returns:
        BatchSummary namedtuple.
    """
    from evennia_xp.awards import record_xp
    from evennia_xp.signals import xp_batch_completed

    # 1. Resolve window.
    if week:
        window_end = _window_end_from_week_str(week)
        week_label = week
    else:
        window_end = _last_monday_00_utc()
        week_label = _week_str_from_window_end(window_end)

    logger.info("XP batch: starting for week=%s window_end=%s", week_label, window_end)

    # 2. Anti-gaming sweeps — each registered callable runs independently so
    #    a failure in one never skips the others.
    for sweep_path in getattr(settings, "XP_ANTIGAMING_SWEEPS", []):
        try:
            _resolve_dotted(sweep_path)(window_end)
        except ImportError:
            pass
        except Exception:
            logger.exception("XP batch: antigaming sweep %r raised an exception", sweep_path)

    # 3. Run collectors from the registry.
    registered_pairs = getattr(settings, "XP_COLLECTORS", [])
    if sources is not None:
        source_set = set(sources)
        registered_pairs = [(k, path) for k, path in registered_pairs if k in source_set]

    awards = []
    for source_key, collector_path in registered_pairs:
        try:
            fn = _resolve_dotted(collector_path)
            for award in fn(window_end):
                awards.append(award)
        except Exception:
            logger.exception("XP batch: collector %r raised an exception", source_key)

    # 4. Compute summary stats (same whether dry or not).
    by_source = defaultdict(lambda: {"count": 0, "total": Decimal("0.00")})
    for award in awards:
        by_source[award.source_type]["count"] += 1
        by_source[award.source_type]["total"] += award.amount

    total_awards = len(awards)
    total_xp = sum(a.amount for a in awards) if awards else Decimal("0.00")

    if dry_run:
        logger.info(
            "XP batch: dry_run=True, would award %d items (%s XP) for week=%s",
            total_awards,
            total_xp,
            week_label,
        )
        return BatchSummary(
            week=week_label,
            total_awards=total_awards,
            total_xp=total_xp,
            by_source=dict(by_source),
            errors=[],
        )

    # 5. Write awards — per-character atomic transactions for isolation.
    errors = []

    # Group by character.
    by_char = defaultdict(list)
    for award in awards:
        by_char[award.character_id].append(award)

    for char_id, char_awards in by_char.items():
        try:
            with transaction.atomic():
                for award in char_awards:
                    record_xp(
                        character_id=award.character_id,
                        amount=award.amount,
                        source_type=award.source_type,
                        source_ref_id=award.source_ref_id,
                        week=week_label,
                        reason=award.reason,
                        multiplier_applied=award.multiplier,
                    )
        except Exception as exc:
            logger.exception("XP batch: transaction failed for character_id=%s", char_id)
            errors.append(f"char {char_id}: {exc}")

    # 6. Post-batch hooks (flag-flips, notifications, etc.).
    for hook_path in getattr(settings, "XP_POST_BATCH_HOOKS", []):
        try:
            _resolve_dotted(hook_path)(window_end, awards, week_label)
        except Exception:
            logger.exception("XP batch: post-batch hook %r raised an exception", hook_path)

    # 7. Fire completion signal.
    summary = BatchSummary(
        week=week_label,
        total_awards=total_awards,
        total_xp=total_xp,
        by_source=dict(by_source),
        errors=errors,
    )
    try:
        xp_batch_completed.send(sender=None, summary=summary, week=week_label)
    except Exception:
        logger.exception("XP batch: xp_batch_completed signal raised an exception")

    logger.info(
        "XP batch: complete — week=%s awards=%d total_xp=%s errors=%d",
        week_label,
        total_awards,
        total_xp,
        len(errors),
    )
    return summary
