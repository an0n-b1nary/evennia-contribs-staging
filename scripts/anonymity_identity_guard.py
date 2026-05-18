"""Refuse to commit when the git author/committer identity matches a forbidden pattern.

Run as a pre-commit hook. Checks:
  - `git config user.name` and `git config user.email` (the identity that will
    be used by default).
  - `$GIT_AUTHOR_NAME`, `$GIT_AUTHOR_EMAIL`, `$GIT_COMMITTER_NAME`,
    `$GIT_COMMITTER_EMAIL` env vars (catches inline overrides like
    `GIT_AUTHOR_EMAIL=x git commit` or `git commit --author=...`, which sets
    GIT_AUTHOR_* in the commit child process).

Patterns come from `.anonymity-patterns` (same gitignored file the content
guard uses). If the file is missing, prints a one-line hint and exits 0.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _anonymity_patterns import MISSING_HINT, PATTERNS_FILE, load_patterns


def _git_config(key: str) -> str:
    result = subprocess.run(
        ["git", "config", "--get", key],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def collect_identity_values() -> list[tuple[str, str]]:
    """Return [(source_label, value), ...] for every identity-bearing string."""
    pairs: list[tuple[str, str]] = []
    for key in ("user.name", "user.email"):
        val = _git_config(key)
        if val:
            pairs.append((f"git config {key}", val))
    for env in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        val = os.environ.get(env, "")
        if val:
            pairs.append((f"${env}", val))
    return pairs


def main() -> int:
    if not PATTERNS_FILE.exists():
        print(MISSING_HINT, file=sys.stderr)
        return 0

    patterns = load_patterns()
    if not patterns:
        return 0

    failures: list[str] = []
    for source, value in collect_identity_values():
        for pat in patterns:
            if pat.search(value):
                failures.append(f"  {source} = {value!r} matches forbidden pattern /{pat.pattern}/")
                break

    if failures:
        print("anonymity identity guard: forbidden identity detected:", file=sys.stderr)
        for line in failures:
            print(line, file=sys.stderr)
        print(
            "\nFix: set the repo-local identity to your protected handle, e.g.:\n"
            "  git config user.name  <handle>\n"
            "  git config user.email <id>+<handle>@users.noreply.github.com",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
