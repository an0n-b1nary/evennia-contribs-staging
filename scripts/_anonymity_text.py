"""Scan arbitrary text (not files) against `.anonymity-patterns`.

Used by the guards that protect content git never sees — GitHub issue titles
and bodies, issue comments — where the pre-commit hooks cannot reach.

The difference from `anonymity_guard.py` matters: that guard **skips** when
`.anonymity-patterns` is absent, so an external contributor cloning the repo is
not blocked by config they were never given. A missing patterns file there
means "this clone is not the maintainer's". Here it means "we are about to
publish text and have no idea what is forbidden", which is the exact situation
the guard exists for. So `require_patterns()` fails closed instead.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _anonymity_patterns import PATTERNS_FILE, load_patterns


class PatternsUnavailable(RuntimeError):
    """Raised when the patterns file is missing or empty."""


def require_patterns() -> list[re.Pattern[str]]:
    """Load patterns, refusing to continue if there are none.

    Never let a missing or empty patterns file read as "nothing is forbidden".
    """
    if not PATTERNS_FILE.exists():
        raise PatternsUnavailable(
            f"{PATTERNS_FILE.name} not found: refusing to publish text unchecked. "
            "Copy .anonymity-patterns.example and fill it in."
        )
    patterns = load_patterns()
    if not patterns:
        raise PatternsUnavailable(
            f"{PATTERNS_FILE.name} contains no patterns — refusing to publish text unchecked."
        )
    return patterns


def scan_text(label: str, text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    """Return human-readable hit descriptions for `text`.

    The returned strings quote the offending line. Safe for a local terminal;
    **never** print these into a public GitHub Actions log — see
    `count_hits()` for the redaction-safe counterpart.
    """
    hits: list[str] = []
    for lineno, line in enumerate((text or "").splitlines(), start=1):
        for pat in patterns:
            if pat.search(line):
                hits.append(f"  {label} line {lineno}: matches /{pat.pattern}/ -> {line.strip()!r}")
                break
    return hits


def count_hits(text: str, patterns: list[re.Pattern[str]]) -> int:
    """Return only how many lines matched — no content, no pattern names.

    This is what runs where the output is public. Printing the matched line or
    the pattern that caught it would republish, in a world-readable Actions
    log, exactly the string the guard just removed from the issue.
    """
    return sum(1 for line in (text or "").splitlines() if any(pat.search(line) for pat in patterns))
