# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Generic sliding-window anti-gaming helpers for evennia_xp.

These helpers are reusable building blocks for game-specific sweep functions
registered in XP_ANTIGAMING_SWEEPS.  They contain no game-specific logic —
no knowledge of Posts, PlotThreads, RPSessions, or Jobs.

Usage in a consumer sweep::

    from evennia_xp.antigaming import _find_burst

    def sweep_cutscene_spam(window_end):
        posts = list(Post.objects.filter(...).order_by("created_at"))
        burst = _find_burst(posts, count=3, window_hours=24)
        if burst:
            ...

_find_burst(items, *, count, window_hours) — return the first run of *count*
    items within *window_hours* of each other.  Items must be sorted by
    timestamp ascending.  Returns the burst items or an empty list.

_item_time(item) — extract the relevant datetime from an item.  Tries
    ``ended_at`` (RPSession-like) then ``created_at`` (Post-like).  Returns
    None if neither is present.
"""

from datetime import timedelta


def _find_burst(items, *, count, window_hours):
    """Return the first group of *count* items within *window_hours* of each other.

    Items must be sorted by their timestamp (ended_at for sessions, created_at
    for posts). Returns the items in the burst, or an empty list if no burst
    is found.

    Args:
        items: Sequence of objects with a timestamp attribute (ended_at or
            created_at). Must be sorted ascending by timestamp.
        count: Minimum number of items that must fall within the window to
            constitute a burst.
        window_hours: Window width in hours. A burst is detected when
            items[i + count - 1].time - items[i].time <= window_hours * 3600s.

    Returns:
        List of *count* items forming the burst, or [] if no burst found.
    """
    window = timedelta(hours=window_hours)
    for i in range(len(items) - count + 1):
        start_time = _item_time(items[i])
        end_time = _item_time(items[i + count - 1])
        if start_time and end_time and (end_time - start_time) <= window:
            return items[i : i + count]
    return []


def _item_time(item):
    """Return the relevant datetime for a session or post.

    Tries ``ended_at`` first (RPSession-like), then ``created_at`` (Post-like).
    Returns None if neither attribute exists.
    """
    if hasattr(item, "ended_at"):
        return item.ended_at
    if hasattr(item, "created_at"):
        return item.created_at
    return None
