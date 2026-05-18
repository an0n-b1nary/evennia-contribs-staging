"""Refuse to stage any file containing references listed in `.anonymity-patterns`.

Run as a pre-commit hook. Receives candidate file paths as positional arguments.
Exits non-zero (and prints offending lines) if any forbidden pattern is found.

If `.anonymity-patterns` is missing, the guard prints a one-line hint and exits
0 (skip). This avoids blocking external contributors who clone the repo
without local guard config; the protection is for *the maintainer's own* clone.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _anonymity_patterns import MISSING_HINT, PATTERNS_FILE, load_patterns  # noqa: E402


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
        print(MISSING_HINT, file=sys.stderr)
        return 0

    patterns = load_patterns()
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
