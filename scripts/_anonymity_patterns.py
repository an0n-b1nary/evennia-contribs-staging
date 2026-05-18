"""Shared loader for `.anonymity-patterns` — used by every anonymity guard.

The patterns file is deliberately gitignored so the public repo never reveals
which private names the guards are configured to block. See
`.anonymity-patterns.example` for format.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PATTERNS_FILE = REPO_ROOT / ".anonymity-patterns"

MISSING_HINT = (
    "anonymity guard: .anonymity-patterns not found - skipping. "
    "Copy .anonymity-patterns.example to .anonymity-patterns and edit "
    "to enable the guard."
)


def load_patterns(path: Path = PATTERNS_FILE) -> list[re.Pattern[str]]:
    """Parse `.anonymity-patterns`. One regex per line.

    Prefix a line with `i:` to make that regex case-insensitive.
    Lines starting with `#` are comments; blank lines are ignored.
    """
    patterns: list[re.Pattern[str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        flags = 0
        if line.lower().startswith("i:"):
            flags = re.IGNORECASE
            line = line[2:].strip()
        try:
            patterns.append(re.compile(line, flags))
        except re.error as exc:
            print(f"anonymity-guard: bad regex {line!r}: {exc}", file=sys.stderr)
            sys.exit(2)
    return patterns
