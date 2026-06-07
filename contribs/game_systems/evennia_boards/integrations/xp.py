# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_boards XP integration — cutscene collector and anti-gaming sweep.

This module ships the boards-domain XP feed. It is only active when registered
in the game's settings and evennia-xp is installed:

    XP_COLLECTORS += [
        ("cutscene", "evennia_boards.integrations.xp.collect_cutscene_posts"),
    ]
    XP_ANTIGAMING_SWEEPS += [
        "evennia_boards.integrations.xp.sweep_cutscene_spam",
    ]

Run sweep_cutscene_spam before collect_cutscene_posts (as XP_ANTIGAMING_SWEEPS
runs before XP_COLLECTORS in the batch engine) so flagged posts are excluded.

BOARDS_ANTIGAMING_REPORTER — dotted path to a callable(title, description).
    Default (None or unset): logs only. Point this at a jobs-creating function
    to file staff tickets without this module importing a jobs app directly.

    Example (add to your settings.py)::

        BOARDS_ANTIGAMING_REPORTER = "myapp.jobs.reporters.create_antigaming_job"

    The callable receives:
        title (str)       — short flag summary
        description (str) — full flag detail including post IDs

Both collect_cutscene_posts and sweep_cutscene_spam import from evennia_xp at
call time (not at module import), so this file is safe to ship even when
evennia-xp is not installed — it simply can't be called meaningfully.
"""

import logging
from datetime import timedelta
from decimal import Decimal

logger = logging.getLogger("evennia")

_CUTSCENE_SPAM_COUNT = 3  # posts within a 24h window triggers a flag
_WINDOW_DAYS = 7


def _window_start(window_end):
    return window_end - timedelta(days=_WINDOW_DAYS)


def _find_burst(items, *, count, window_hours):
    """Return the first group of *count* items within *window_hours* of each other.

    Items must be sorted by created_at. Returns the items in the burst, or
    an empty list when no burst is found.
    """
    window = timedelta(hours=window_hours)
    for i in range(len(items) - count + 1):
        t_start = getattr(items[i], "created_at", None)
        t_end = getattr(items[i + count - 1], "created_at", None)
        if t_start and t_end and (t_end - t_start) <= window:
            return items[i : i + count]
    return []


def _call_reporter(title, description):
    """Invoke BOARDS_ANTIGAMING_REPORTER, or log only when not configured."""
    from django.conf import settings

    reporter_path = getattr(settings, "BOARDS_ANTIGAMING_REPORTER", None)
    if not reporter_path:
        logger.warning(
            "evennia_boards: no BOARDS_ANTIGAMING_REPORTER configured; " "flag logged only: %r",
            title,
        )
        return
    try:
        from importlib import import_module

        module_path, _, attr = reporter_path.rpartition(".")
        getattr(import_module(module_path), attr)(title, description)
    except Exception:
        logger.exception("evennia_boards: reporter %r failed for %r", reporter_path, title)


def sweep_cutscene_spam(window_end):
    """Flag authors who posted >= 3 IC-board posts within any 24h window.

    Reads and writes board data only (Post.xp_flagged). Does not interact
    with evennia_xp directly — it only writes the flag that collect_cutscene_posts
    reads. Run this before collect_cutscene_posts in XP_ANTIGAMING_SWEEPS.

    Already-flagged posts are skipped (idempotent). Each newly flagged burst
    invokes BOARDS_ANTIGAMING_REPORTER for staff review.

    Args:
        window_end: datetime (Monday 00:00 UTC) marking the end of the window.
    """
    from evennia_boards.models import Post

    window_start = _window_start(window_end)
    ic_posts = (
        Post.all_objects.filter(
            board__board_type="ic",
            author_id__isnull=False,
            xp_flagged=False,
            created_at__gt=window_start,
            created_at__lte=window_end,
        )
        .select_related("board")
        .order_by("author_id", "created_at")
    )

    by_author = {}
    for post in ic_posts:
        by_author.setdefault(post.author_id, []).append(post)

    flagged_authors = 0
    for _author_id, posts in by_author.items():
        burst = _find_burst(posts, count=_CUTSCENE_SPAM_COUNT, window_hours=24)
        if not burst:
            continue

        author_name = posts[0].author_name
        reason = f"Auto-flag: cutscene spam — {len(burst)} IC posts within 24h"
        Post.all_objects.filter(pk__in=[p.pk for p in burst]).update(
            xp_flagged=True,
            xp_flag_reason=reason,
        )
        _call_reporter(
            title=f"Auto-flag: cutscene spam — {author_name}",
            description=(
                f"{author_name} created {len(burst)} IC-board posts within 24 hours.\n\n"
                f"Post IDs: {', '.join(str(p.pk) for p in burst)}\n\n"
                f"Review and clear xp_flagged on legitimate posts."
            ),
        )
        flagged_authors += 1

    if flagged_authors:
        logger.info(
            "evennia_boards: cutscene spam — flagged posts for %d author(s)",
            flagged_authors,
        )


def collect_cutscene_posts(window_end):
    """Yield Awards for IC-board posts created within the window.

    Posts on boards with board_type="ic" earn 1 XP each (scaled by the
    active arc multiplier if evennia-xp gating is configured). Archived
    posts, flagged posts, and already-awarded posts are all skipped.

    Requires evennia-xp to be installed and registered. Import from
    evennia_xp.batch (Award namedtuple), evennia_xp.models (XPLog), and
    evennia_xp.gating (resolve_xp_multiplier) happen at call time.

    Args:
        window_end: datetime marking the end of the window.

    Yields:
        Award per eligible IC-board Post.
    """
    from evennia_xp.batch import Award
    from evennia_xp.gating import resolve_xp_multiplier
    from evennia_xp.models import XPLog

    from evennia_boards.models import Post

    window_start = _window_start(window_end)
    # Post.objects (ArchivedManager default) already excludes archived posts.
    posts = Post.objects.filter(
        board__board_type="ic",
        created_at__gt=window_start,
        created_at__lte=window_end,
        author_id__isnull=False,
        xp_flagged=False,
    )

    post_ids = list(posts.values_list("pk", flat=True))
    if not post_ids:
        return

    awarded_ids = set(
        XPLog.objects.filter(
            source_type=XPLog.SourceType.CUTSCENE,
            source_ref_id__in=post_ids,
        ).values_list("source_ref_id", flat=True)
    )

    for post in posts.select_related("board"):
        if post.pk in awarded_ids:
            continue
        mult = resolve_xp_multiplier("cutscene")
        if not mult:
            continue
        yield Award(
            character_id=post.author_id,
            amount=Decimal("1.0") * mult,
            source_type=XPLog.SourceType.CUTSCENE,
            source_ref_id=post.pk,
            multiplier=mult,
            reason=f"Cutscene post: {post.title}",
        )
