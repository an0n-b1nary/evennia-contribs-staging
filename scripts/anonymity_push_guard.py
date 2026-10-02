"""Refuse protected pushes when commit identity or the active account could leak.

Configure a maintainer clone with ``git config anonymity.expected-gh-account HANDLE``.
Unconfigured clones and remotes outside that account are unaffected. Protected pushes
require a readable, nonempty ``.anonymity-patterns`` file and a matching active gh account.

Native Git hooks provide remote name/URL as arguments and pushed refs on stdin.
The pre-commit framework instead provides PRE_COMMIT_REMOTE_* environment variables
and consumes stdin itself. In that mode, check its selected range plus every local
branch/tag commit absent from the remote-tracking refs. This conservative check also
covers a multi-ref push, since pre-commit only forwards the first changed ref's range.
It can reject an unpublished identity on a branch that is not part of this push.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _anonymity_patterns import PATTERNS_FILE, load_patterns

EXPECTED_ACCOUNT_CONFIG_KEY = "anonymity.expected-gh-account"
ZERO_SHA = "0" * 40


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def expected_account() -> str | None:
    result = subprocess.run(
        ["git", "config", "--get", EXPECTED_ACCOUNT_CONFIG_KEY],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 1:
        return None  # key is unset
    if result.returncode != 0:
        raise RuntimeError(f"could not read guard configuration: {result.stderr.strip()}")
    return result.stdout.strip() or None


def remote_matches_account(url: str, account: str) -> bool:
    pattern = re.compile(rf"github\.com[:/]{re.escape(account)}/", re.IGNORECASE)
    return bool(pattern.search(url))


def commits_to_check(local_sha: str, remote_sha: str) -> list[str]:
    """Return newly pushed commits; a ref deletion has no commits to inspect."""
    for sha in (local_sha, remote_sha):
        if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            raise RuntimeError("invalid commit SHA in pushed ref")
    if local_sha == ZERO_SHA:
        return []
    rev_range = local_sha if remote_sha == ZERO_SHA else f"{remote_sha}..{local_sha}"
    return _git("rev-list", rev_range).splitlines()


def commit_identity(sha: str) -> list[tuple[str, str]]:
    """Return every author/committer identity field, refusing unreadable commits."""
    lines = _git("show", "-s", "--format=%an%n%ae%n%cn%n%ce", sha).splitlines()
    if len(lines) != 4:
        raise RuntimeError(f"could not read all identity fields for {sha[:7]}")
    return list(
        zip(
            ("author name", "author email", "committer name", "committer email"), lines, strict=True
        )
    )


def _precommit_commits(remote_name: str) -> set[str]:
    local_ref = os.environ.get("PRE_COMMIT_TO_REF") or os.environ.get("PRE_COMMIT_LOCAL_BRANCH")
    if not local_ref or local_ref.startswith("-") or remote_name.startswith("-"):
        raise RuntimeError("missing or invalid pre-commit push context")
    commits = set(
        _git(
            "rev-list", "--branches", "--tags", local_ref, "--not", f"--remotes={remote_name}"
        ).splitlines()
    )
    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")
    if from_ref and to_ref:
        commits.update(commits_to_check(to_ref, from_ref))
    return commits


def check_commits(patterns: list[re.Pattern[str]], *, remote_name: str | None = None) -> list[str]:
    """Check native pushed refs or the framework's conservative outgoing commit set."""
    commits: set[str] = set()
    if remote_name is not None:
        commits = _precommit_commits(remote_name)
    else:
        for raw in sys.stdin:
            parts = raw.split()
            if len(parts) != 4:
                raise RuntimeError("malformed pushed ref input")
            _local_ref, local_sha, _remote_ref, remote_sha = parts
            commits.update(commits_to_check(local_sha, remote_sha))
    failures: list[str] = []
    for sha in sorted(commits):
        for label, value in commit_identity(sha):
            for pat in patterns:
                if pat.search(value):
                    failures.append(
                        f"  {sha[:7]} {label} = {value!r} matches forbidden pattern /{pat.pattern}/"
                    )
                    break
    return failures


def check_gh_account(expected: str) -> str | None:
    """Return an error unless the active gh account equals the configured handle."""
    result = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return (
            f"could not determine active gh account (gh api user failed: {result.stderr.strip()})"
        )
    active = result.stdout.strip()
    if active != expected:
        return (
            f"active gh account is {active!r}, expected {expected!r}.\n"
            f"  Fix: gh auth switch -u {expected}"
        )
    return None


def main(argv: list[str]) -> int:
    try:
        account = expected_account()
        if account is None:
            return 0
        native = len(argv) == 2
        remote_name = argv[0] if native else os.environ.get("PRE_COMMIT_REMOTE_NAME")
        remote_url = argv[1] if native else os.environ.get("PRE_COMMIT_REMOTE_URL")
        if not remote_name or not remote_url:
            raise RuntimeError(
                "missing remote context; run through Git/pre-commit or pass NAME URL"
            )
        if not remote_matches_account(remote_url, account):
            return 0
        if not PATTERNS_FILE.exists():
            raise RuntimeError(".anonymity-patterns not found; refusing protected push unchecked")
        patterns = load_patterns()
        if not patterns:
            raise RuntimeError(
                ".anonymity-patterns contains no patterns; refusing protected push unchecked"
            )
        failures = check_commits(patterns, remote_name=None if native else remote_name)
        if failures:
            print(f"anonymity push guard: refusing push to {remote_url}", file=sys.stderr)
            print("forbidden identity in outgoing commits:", file=sys.stderr)
            for line in failures:
                print(line, file=sys.stderr)
            return 1
        gh_error = check_gh_account(account)
        if gh_error:
            raise RuntimeError(gh_error)
    except (OSError, RuntimeError, UnicodeError) as exc:
        print(f"anonymity push guard: refusing push: {exc}", file=sys.stderr)
        return 1
    print(f"anonymity push guard: identity OK for push to {remote_url}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
