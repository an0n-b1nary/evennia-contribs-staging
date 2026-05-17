"""Refuse to stage any file containing references listed in `.anonymity-patterns`.

Run as a pre-commit hook. Receives candidate file paths as positional arguments.
Exits non-zero (and prints offending lines) if any forbidden pattern is found.

Patterns are loaded from `.anonymity-patterns` at the repo root. That file is
deliberately gitignored so the public repo never reveals which private names
the guard is configured to block. See `.anonymity-patterns.example` for format.

If `.anonymity-patterns` is missing, the guard prints a one-line hint and exits
0 (skip). This avoids blocking external contributors who clone the repo
without local guard config; the protection is for *the maintainer's own* clone.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PATTERNS_FILE = REPO_ROOT / ".anonymity-patterns"


def load_patterns(path: Path) -> list[re.Pattern[str]]:
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


def scan(path: Path, patterns: list[re.Pattern[str]]) -> list[tuple[int, str]]:
    """Return (line_number, line_content) for each line containing any pattern."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if any(p.search(line) for p in patterns):
            hits.append((lineno, line.rstrip()))
    return hits


def main(argv: list[str]) -> int:
    if not PATTERNS_FILE.exists():
        print(
            "anonymity-guard: .anonymity-patterns not found — skipping. "
            "Copy .anonymity-patterns.example to .anonymity-patterns and edit "
            "to enable the guard.",
            file=sys.stderr,
        )
        return 0

    patterns = load_patterns(PATTERNS_FILE)
    if not patterns:
        return 0

    failures = 0
    for raw in argv:
        path = Path(raw)
        if not path.is_file():
            continue
        for lineno, line in scan(path, patterns):
            print(f"{path}:{lineno}: forbidden reference: {line}")
            failures += 1

    if failures:
        print(
            f"\nAnonymity guard: {failures} forbidden reference(s) found. "
            "Strip or rename before committing.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
