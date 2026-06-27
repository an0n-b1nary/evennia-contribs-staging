# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
XP gating helpers for evennia_plots.

Single canonical point for "should XP be suppressed / scaled right now?"
decisions. The XP batch, RPTracker close-out, and the plot-bonus award path
should all import from here so future policy changes (regional arcs,
character-scoped overrides) land in one place.

Register this module as your XP multiplier resolver::

    # settings.py
    XP_MULTIPLIER_RESOLVER = "evennia_plots.gating.resolve_xp_multiplier"

Resolution order for resolve_active_arc:

1. thread.arc — explicit per-thread arc (wins over global)
2. PlotArc.objects.filter(is_current=True).first() — global current arc
3. None — no arc context; XP flows at full rate

resolve_xp_multiplier(source) wraps resolve_active_arc and returns the per-arc
per-source Decimal multiplier. Callers use this instead of thread_pauses_xp
for fine-grained XP scaling.

The *room* and *character* kwargs are placeholders for future regional /
character-scoped extensions; they are accepted but ignored today. Callers that
have these values in scope should pass them so the call sites are already wired
when the policy expands.
"""

from decimal import Decimal


def resolve_active_arc(thread=None, *, room=None, character=None):
    """Return the arc that governs XP for *thread*, or None.

    Args:
        thread: PlotThread instance, or None.
        room: Room ObjectDB instance (future regional use), or None.
        character: Character ObjectDB instance (future override use), or None.

    Returns:
        PlotArc | None
    """
    if thread is not None and thread.arc_id:
        return thread.arc
    from evennia_plots.models import PlotArc

    return PlotArc.objects.filter(is_current=True).first()


def thread_pauses_xp(thread) -> bool:
    """Return True if the active arc suppresses XP gain for *thread*.

    Convenience predicate: equivalent to
    ``resolve_xp_multiplier("thread_bonus", thread=thread) == 0``, but cheaper
    for callers that only need a boolean.

    Args:
        thread: PlotThread instance.

    Returns:
        bool
    """
    arc = resolve_active_arc(thread=thread)
    return bool(arc and arc.pauses_xp)


def resolve_xp_multiplier(source: str, *, thread=None, room=None, character=None) -> Decimal:
    """Return the XP multiplier for *source* given context.

    Resolution: thread.arc → global current arc → Decimal("1.0") (no arc
    context means full XP).

    Args:
        source: One of PlotArc.XP_SOURCES — "rp_session", "cutscene",
                "lore", "thread_bonus".
        thread: PlotThread instance, or None.
        room: Room ObjectDB instance (future regional use), or None.
        character: Character ObjectDB instance (future override use), or None.

    Returns:
        Decimal multiplier. 1.0 = full rate, 0.0 = paused, 2.0 = doubled.
    """
    arc = resolve_active_arc(thread=thread, room=room, character=character)
    if arc is None:
        return Decimal("1.0")
    return arc.get_xp_multiplier(source)
