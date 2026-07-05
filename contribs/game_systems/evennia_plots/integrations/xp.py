# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
XP source collectors for evennia_plots.

Provides collect_thread_bonuses and collect_arc_bonuses for registration in
``XP_COLLECTORS``::

    # settings.py
    XP_COLLECTORS = [
        ...
        ("thread_bonus", "evennia_plots.integrations.xp.collect_thread_bonuses"),
        ("arc_bonus",    "evennia_plots.integrations.xp.collect_arc_bonuses"),
    ]

Requires the ``[xp]`` extra (``evennia-xp``). The ``XPLog`` import is deferred
to function bodies so this module is safe to import without evennia-xp present.

Window convention: the weekly batch passes ``window_end = Monday 00:00 UTC``.
Each collector queries the preceding 7-day window: ``(window_end - 7d, window_end]``.

Design rules:

- Collectors never write XPLog or CharacterXP rows. They read and yield.
- collect_thread_bonuses creates PlotBonusCredit rows (via get_or_create) to
  establish stable source_ref_ids for XPLog idempotency.
- Every yielded amount has already been multiplied by resolve_xp_multiplier().
- Items whose multiplier resolves to 0 are silently skipped (Downtime arc).
- All cross-domain imports are lazy (inside function bodies).
"""

from collections import namedtuple
from datetime import timedelta
from decimal import Decimal

Award = namedtuple(
    "Award",
    ["character_id", "amount", "source_type", "source_ref_id", "multiplier", "reason"],
)

_WINDOW_DAYS = 7


def _window_start(window_end):
    return window_end - timedelta(days=_WINDOW_DAYS)


def collect_thread_bonuses(window_end):
    """Yield Awards for PlotThread conclusion bonuses concluded in the window.

    For each concluded thread with bonus_xp_computed > 0 and bonus_xp_awarded=False,
    distributes the bonus amount to every PlotParticipant. Respects the arc
    multiplier via thread.bonus_xp_should_award (which checks resolve_xp_multiplier
    for "thread_bonus" > 0).

    A PlotBonusCredit row is get_or_created for each (thread, character_id) pair.
    Its pk becomes source_ref_id for XPLog idempotency.

    Args:
        window_end: datetime marking the end of the window.

    Yields:
        Award per (thread, participant) credit.
    """
    # evennia_xp is an optional dep; import deferred so this module loads without it.
    from evennia_xp.models import XPLog

    from evennia_plots.integrations.gating import resolve_xp_multiplier
    from evennia_plots.models import PlotBonusCredit, PlotParticipant, PlotThread

    window_start = _window_start(window_end)
    threads = PlotThread.objects.filter(
        status=PlotThread.Status.CONCLUDED,
        bonus_xp_awarded=False,
        bonus_xp_computed__gt=0,
        concluded_at__gt=window_start,
        concluded_at__lte=window_end,
    )

    awarded_credit_ids = set(
        XPLog.objects.filter(
            source_type=XPLog.SourceType.THREAD_BONUS,
        ).values_list("source_ref_id", flat=True)
    )

    for thread in threads:
        if not thread.bonus_xp_should_award:
            continue

        mult = resolve_xp_multiplier("thread_bonus", thread=thread)
        if not mult:
            continue

        participants = PlotParticipant.objects.filter(thread=thread, character_id__isnull=False)
        base_amount = Decimal(str(thread.bonus_xp_computed))

        for participant in participants:
            char_id = participant.character_id
            credit, _ = PlotBonusCredit.objects.get_or_create(
                thread=thread,
                character_id=char_id,
            )
            if credit.pk in awarded_credit_ids:
                continue
            yield Award(
                character_id=char_id,
                amount=base_amount * mult,
                source_type=XPLog.SourceType.THREAD_BONUS,
                source_ref_id=credit.pk,
                multiplier=mult,
                reason=f"Thread concluded: {thread.name}",
            )


def collect_arc_bonuses(window_end):
    """Stub collector for PlotArc conclusion bonuses.

    Arc bonuses are staff-set and triggered manually via a staff command, not
    by the weekly batch. This function is a no-op placeholder that keeps the
    collector interface consistent.

    Args:
        window_end: datetime (unused; kept for interface parity).

    Yields:
        Nothing.
    """
    yield from ()
