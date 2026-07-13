# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Name highlighting and pose-time formatting utilities.

``highlight_names`` applies per-reader color highlighting to character names
in poses and room descriptions. ``format_pose_time`` converts a Unix
timestamp into a human-readable relative-time string ("3m 12s", "1h 05m").
Both are pure functions with no typeclass coupling, reused by this contrib's
own commands/mixins and by consumers like evennia_social's ``+where``.
"""

import re
import time

# Matches Evennia pipe-code sequences so we can skip them during name
# substitution. Covers: |#RRGGBB, |[X (background), |lc |lt |le |lu (MXP
# links), and single-char codes like |r |n |/ |- |* |> |!
_COLOR_CODE_RE = re.compile(
    r"\|"
    r"(?:"
    r"#[0-9a-fA-F]{6}"  # |#RRGGBB hex color
    r"|\[[a-zA-Z]"  # |[X background color
    r"|l[cteu]"  # |lc |lt |le |lu  MXP link codes
    r"|[a-zA-Z>\/\-\*\!]"  # |r |n |/ |- |* |> |! etc.
    r")"
)


def highlight_names(text, looker, characters):
    """Apply per-reader name highlighting to *text*.

    Args:
        text (str): Text containing character names (pose, room desc).
            May include Evennia pipe-color codes.
        looker: The Character receiving this text. Must have an
            ``.account`` with OptionHandler preferences
            (``highlight_enabled``, ``highlight_self_color``,
            ``highlight_others_color`` — see README for registration).
        characters: Iterable of Character objects whose ``.key`` names
            should be highlighted.

    Returns:
        str: *text* with character names wrapped in Evennia color codes,
        or the original *text* unchanged if highlighting is disabled or
        there are no names to match.
    """
    # Guard: need a logged-in account with highlighting enabled.
    account = getattr(looker, "account", None)
    if not account:
        return text
    if not account.options.get("highlight_enabled", True):
        return text

    # Collect names, filtering out empty/None keys.
    names = [char.key for char in characters if getattr(char, "key", None)]
    if not names:
        return text

    # Sort longest-first so "Annabel" matches before "Anna".
    names.sort(key=len, reverse=True)

    # Build a single compiled regex with word boundaries.
    escaped = [re.escape(name) for name in names]
    name_pattern = re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)

    # Build color lookup: looker's own name -> self color, others -> others color.
    self_color = account.options.get("highlight_self_color", "w")
    others_color = account.options.get("highlight_others_color", "c")
    looker_key = getattr(looker, "key", None)

    color_map = {}
    for char in characters:
        key = getattr(char, "key", None)
        if key:
            color_map[key.lower()] = (
                self_color if key.lower() == (looker_key or "").lower() else others_color
            )

    # Split text on color codes, apply substitution only to plain segments.
    parts = _COLOR_CODE_RE.split(text)
    codes = _COLOR_CODE_RE.findall(text)

    for i, part in enumerate(parts):
        parts[i] = name_pattern.sub(
            lambda m: f"|{color_map[m.group(0).lower()]}{m.group(0)}|n", part
        )

    # Interleave plain parts and color codes back together.
    result = []
    for i, part in enumerate(parts):
        result.append(part)
        if i < len(codes):
            result.append(codes[i])

    return "".join(result)


def format_pose_time(timestamp):
    """Convert a Unix timestamp to a human-readable relative time string.

    Args:
        timestamp (float or None): Unix timestamp, or None for no data.

    Returns:
        str: Relative time like "just now", "3m 12s", "1h 05m", or "--".
    """
    if timestamp is None:
        return "--"
    elapsed = time.time() - timestamp
    if elapsed < 0:
        elapsed = 0
    if elapsed < 60:
        return "just now"
    minutes, seconds = divmod(int(elapsed), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days > 0:
        return f"{days}d {hours:02d}h"
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {seconds:02d}s"
