"""Server-side anonymity sweep for GitHub issues and issue comments.

Runs from `.github/workflows/anonymity-issues.yml` on every issue opened or
edited and every comment created or edited, including ones filed through the
web UI by anyone — the path `scripts/file_issue.py` cannot cover.

On a match it removes the text: the issue's title and body are replaced with a
placeholder, it is labelled, closed and locked; an offending comment is
deleted outright. Then it exits non-zero so the run shows red.

**This is mitigation, not prevention, and the difference is not academic.**
GitHub emails watchers the original text the moment it is submitted, and the
Events API exposes it to anyone streaming the public firehose. Neither can be
recalled by editing. Redaction closes the web-visible copy — the copy already
delivered stays delivered. Treat a red run here as an incident to assess, not
as a problem that has been solved.

Deliberately, this script never prints the matched line or the pattern that
caught it. Actions logs on a public repo are world-readable, so echoing either
would republish exactly what was just removed, in a place that outlives the
issue. Counts only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _anonymity_text import PatternsUnavailable, count_hits, require_patterns

BOT_LOGINS = {"github-actions[bot]", "github-actions"}

REDACTED_TITLE = "[redacted by the anonymity guard]"
REDACTED_BODY = (
    "This issue's title and body were removed automatically: they matched a "
    "pattern this repository refuses to publish.\n\n"
    "The original text was **not** preserved anywhere. If the report is still "
    "worth filing, please rewrite it without the offending reference and open "
    "a new issue.\n\n"
    "See `CONTRIBUTING.md` for what this repository does not name and the "
    "phrasing to use instead."
)


def gh_api(args: list[str]) -> tuple[int, str]:
    result = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        # stderr from `gh api` echoes the request, not the issue body.
        print(f"  gh api failed: {result.stderr.strip()}", file=sys.stderr)
    return result.returncode, result.stdout


def load_event() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        print("GITHUB_EVENT_PATH unset — not running in Actions?", file=sys.stderr)
        sys.exit(2)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def redact_issue(repo: str, number: int) -> None:
    print(f"redacting issue #{number}")
    gh_api(
        [
            "-X",
            "PATCH",
            f"/repos/{repo}/issues/{number}",
            "-f",
            f"title={REDACTED_TITLE}",
            "-f",
            f"body={REDACTED_BODY}",
            "-f",
            "state=closed",
            "-f",
            "state_reason=not_planned",
        ]
    )
    gh_api(
        [
            "-X",
            "POST",
            f"/repos/{repo}/issues/{number}/labels",
            "-f",
            "labels[]=anonymity-hold",
        ]
    )
    # Locking stops the thread accumulating comments that repeat the same
    # reference while the maintainer is still working out what leaked.
    gh_api(["-X", "PUT", f"/repos/{repo}/issues/{number}/lock", "-f", "lock_reason=off-topic"])


def delete_comment(repo: str, comment_id: int) -> None:
    print(f"deleting comment {comment_id}")
    gh_api(["-X", "DELETE", f"/repos/{repo}/issues/comments/{comment_id}"])


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event = load_event()

    sender = (event.get("sender") or {}).get("login", "")
    if sender in BOT_LOGINS:
        print("sender is this workflow; skipping to avoid an edit loop")
        return 0

    try:
        patterns = require_patterns()
    except PatternsUnavailable as exc:
        # Fail closed and loudly. A sweep that silently checks nothing is worse
        # than no sweep, because it looks like protection.
        print(f"anonymity sweep: {exc}", file=sys.stderr)
        return 2

    if event_name == "issue_comment":
        comment = event.get("comment") or {}
        hits = count_hits(comment.get("body", ""), patterns)
        if hits:
            print(f"comment matched on {hits} line(s)")
            delete_comment(repo, comment["id"])
            return 1
        print("comment clean")
        return 0

    if event_name == "issues":
        issue = event.get("issue") or {}
        number = issue.get("number")
        hits = count_hits(issue.get("title", ""), patterns)
        hits += count_hits(issue.get("body", ""), patterns)
        if hits:
            print(f"issue #{number} matched on {hits} line(s)")
            redact_issue(repo, number)
            return 1
        print(f"issue #{number} clean")
        return 0

    print(f"anonymity sweep: nothing to do for event {event_name!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
