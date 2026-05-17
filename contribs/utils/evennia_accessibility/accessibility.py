# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Accessibility helpers — screen-reader-friendly output utilities.

These helpers gate on the ``screenreader_mode`` account option
(``OPTIONS_ACCOUNT_DEFAULT`` in settings.py). When on, ASCII tables and
color-only indicators are replaced with plain, linearly-readable text.

Primary entry point for callers::

    from evennia_accessibility import uses_screenreader, plain_list

Usage in a command::

    if uses_screenreader(self.caller):
        self.caller.msg(plain_list(rows, headers=["Name", "Time", "Status"]))
    else:
        # normal EvTable path
"""


def uses_screenreader(caller) -> bool:
    """Return True if *caller* has screenreader_mode enabled.

    Tolerates None, Account-only callers (no puppet), and Characters
    without an account (NPC-like objects).
    """
    if caller is None:
        return False
    # Characters have .account; Accounts don't.
    account = getattr(caller, "account", caller)
    if account is None:
        return False
    try:
        return bool(account.options.get("screenreader_mode", False))
    except Exception:
        return False


def plain_list(rows, headers=None) -> str:
    """Format *rows* as a plain-text list suited for screen readers.

    Args:
        rows: Iterable of iterables. Each inner iterable is one entry.
        headers: Optional list of column-label strings. When provided
            each value is prefixed with "Label: ". When omitted, values
            are joined with " — ".

    Returns:
        A multi-line string with one entry per line.

    Example without headers::

        plain_list([["Char", "2m", "IC"], ["Char2", "5m", "AFK"]])
        # "Char — 2m — IC\\nChar2 — 5m — AFK"

    Example with headers::

        plain_list([["Char", "2m"]], headers=["Name", "Time"])
        # "Name: Char, Time: 2m"
    """
    lines = []
    for row in rows:
        row = list(row)
        if headers:
            pairs = []
            for i, val in enumerate(row):
                label = headers[i] if i < len(headers) else str(i)
                pairs.append(f"{label}: {val}")
            lines.append(", ".join(pairs))
        else:
            lines.append(" — ".join(str(v) for v in row))
    return "\n".join(lines)


def describe_icon(symbol: str, meaning: str) -> str:
    """Return *meaning* — the screen-reader-safe label for a decorative *symbol*.

    Callers use this to swap an icon for its description when SR is on::

        if uses_screenreader(caller):
            indicator = describe_icon("★", "Staff event")
        else:
            indicator = "★"
    """
    return meaning


def describe_priority(level: str) -> str:
    """Return a human-readable priority label for use alongside color cues.

    Args:
        level: One of "normal", "high", "urgent" (case-insensitive).

    Returns:
        A readable string like "High priority". Falls back to the
        original *level* value if unrecognised.
    """
    mapping = {
        "normal": "Normal priority",
        "high": "High priority",
        "urgent": "Urgent priority",
        "low": "Low priority",
    }
    return mapping.get(level.lower(), level.capitalize())
