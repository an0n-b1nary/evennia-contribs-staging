"""Refuse to push to a protected GitHub remote when identity could leak.

Run as a pre-push hook (pre-commit framework, stages: [pre-push]).

Args: <remote_name> <remote_url>     (forwarded by git/pre-commit)
Stdin: one line per ref being pushed: <local_ref> <local_sha> <remote_ref> <remote_sha>

The "protected remote" is determined per-clone by git config:
  git config anonymity.expected-gh-account <handle>

If that key is unset, the guard is inactive (exits 0). External clones and
forks therefore get a no-op by default; only clones whose maintainer has
explicitly configured the expected handle run the checks.

When active and the remote URL matches `github.com[:/]<handle>/`:
  1. Walks every commit being pushed and rejects if any commit's author or
     committer name/email matches a forbidden pattern in `.anonymity-patterns`
     (best-effort: if `.anonymity-patterns` is absent, the commit walk is
     skipped but the gh-account check still runs).
  2. Verifies the active `gh` account equals the configured handle. This
     catches the case where the credential helper would push using the wrong
     account's token.

For any other remote, exits 0 immediately.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _anonymity_patterns import PATTERNS_FILE, load_patterns

EXPECTED_ACCOUNT_CONFIG_KEY = "anonymity.expected-gh-account"
ZERO_SHA = "0" * 40


def _git_config(key: str) -> str | None:
    result = subprocess.run(
        ["git", "config", "--get", key],
        capture_output=True,
        text=True,
        check=False,
    )
    value = result.stdout.strip()
    return value or None


def expected_account() -> str | None:
    return _git_config(EXPECTED_ACCOUNT_CONFIG_KEY)


def remote_matches_account(url: str, account: str) -> bool:
    pattern = re.compile(rf"github\.com[:/]{re.escape(account)}/", re.IGNORECASE)
    return bool(pattern.search(url))


def commits_to_check(local_sha: str, remote_sha: str) -> list[str]:
    """Return SHAs being newly pushed. Empty list if the ref is being deleted."""
    if local_sha == ZERO_SHA:
        return []  # ref deletion
    rev_range = local_sha if remote_sha == ZERO_SHA else f"{remote_sha}..{local_sha}"
    result = subprocess.run(
        ["git", "rev-list", rev_range],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def commit_identity(sha: str) -> list[tuple[str, str]]:
    """Return [(label, value), ...] for the commit's author + committer name/email."""
    fmt = "%an%n%ae%n%cn%n%ce"
    result = subprocess.run(
        ["git", "show", "-s", f"--format={fmt}", sha],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    lines = result.stdout.splitlines()
    if len(lines) < 4:
        return []
    return [
        ("author name", lines[0]),
        ("author email", lines[1]),
        ("committer name", lines[2]),
        ("committer email", lines[3]),
    ]


def check_commits(patterns: list[re.Pattern[str]]) -> list[str]:
    """Read refs from stdin; return failure messages (empty if all clean)."""
    failures: list[str] = []
    for raw in sys.stdin:
        parts = raw.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        for sha in commits_to_check(local_sha, remote_sha):
            for label, value in commit_identity(sha):
                for pat in patterns:
                    if pat.search(value):
                        failures.append(
                            f"  {sha[:7]} {label} = {value!r} "
                            f"matches forbidden pattern /{pat.pattern}/"
                        )
                        break
    return failures


def check_gh_account(expected: str) -> str | None:
    """Return None if active gh account equals expected, else an error message."""
    result = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return (
            "could not determine active gh account "
            f"(gh api user failed: {result.stderr.strip()})"
        )
    active = result.stdout.strip()
    if active != expected:
        return (
            f"active gh account is {active!r}, expected {expected!r}.\n"
            f"  Fix: gh auth switch -u {expected}"
        )
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return 0
    remote_url = argv[1]  # argv[0] = remote name, argv[1] = remote URL

    account = expected_account()
    if account is None:
        return 0  # guard not configured on this clone
    if not remote_matches_account(remote_url, account):
        return 0  # remote is not the protected one

    patterns = load_patterns() if PATTERNS_FILE.exists() else []

    commit_failures = check_commits(patterns) if patterns else []
    gh_error = check_gh_account(account)

    if not commit_failures and gh_error is None:
        print(
            f"anonymity push guard: identity OK for push to {remote_url}",
            file=sys.stderr,
        )
        return 0

    print(
        f"anonymity push guard: refusing push to {remote_url}",
        file=sys.stderr,
    )
    if commit_failures:
        print("forbidden identity in pushed commits:", file=sys.stderr)
        for line in commit_failures:
            print(line, file=sys.stderr)
    if gh_error:
        print(gh_error, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
