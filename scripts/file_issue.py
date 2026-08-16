"""Create a GitHub issue or comment only after the anonymity guard clears it.

`gh issue create` publishes instantly and irreversibly: GitHub emails every
watcher the original text within seconds, and those emails cannot be recalled
even if the issue is edited or deleted a moment later. There is no pre-commit
hook in front of it, because nothing is being committed.

So use this instead of `gh` directly:

    python scripts/file_issue.py create --title "..." --body-file draft.md
    python scripts/file_issue.py create --title "..." --body-file draft.md --label chore
    python scripts/file_issue.py comment 7 --body-file reply.md
    python scripts/file_issue.py create --title "..." --body-file draft.md --dry-run

Both the title and the body are scanned. Anything matching `.anonymity-patterns`
aborts before `gh` is invoked at all, and the offending lines are printed here —
in your terminal, which is private, unlike everything downstream of this script.

This is a convenience, not a guarantee: nothing stops anyone opening
github.com and typing. The server-side sweep in
`.github/workflows/anonymity-issues.yml` is the backstop for that path.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _anonymity_text import PatternsUnavailable, require_patterns, scan_text


def read_body(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def check(fields: list[tuple[str, str]]) -> int:
    """Scan (label, text) pairs. Return count of offending lines."""
    patterns = require_patterns()
    hits: list[str] = []
    for label, text in fields:
        hits.extend(scan_text(label, text, patterns))
    if hits:
        print("anonymity guard: refusing to publish.", file=sys.stderr)
        for hit in hits:
            print(hit, file=sys.stderr)
        print(
            "\nNothing was sent to GitHub. Rewrite the offending lines: "
            "'the source game' / 'a private Evennia game project' is the "
            "established public phrasing.",
            file=sys.stderr,
        )
    return len(hits)


def run_gh(args: list[str]) -> int:
    print(f"+ gh {' '.join(args)}", file=sys.stderr)
    return subprocess.run(["gh", *args], check=False).returncode


def main(argv: list[str]) -> int:
    # --repo/--dry-run go on both subcommands rather than the top level, so
    # they work in either position and the usage line reads like gh's.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="owner/name; defaults to the current repo")
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="scan and report, but never call gh",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", parents=[common], help="create an issue")
    create.add_argument("--title", required=True)
    create.add_argument("--body-file", required=True)
    create.add_argument("--label", action="append", default=[])
    create.add_argument("--assignee", action="append", default=[])

    comment = sub.add_parser("comment", parents=[common], help="comment on an issue")
    comment.add_argument("number")
    comment.add_argument("--body-file", required=True)

    args = parser.parse_args(argv)

    try:
        body = read_body(args.body_file)
    except OSError as exc:
        print(f"cannot read body file: {exc}", file=sys.stderr)
        return 2

    fields = [("body", body)]
    if args.command == "create":
        fields.insert(0, ("title", args.title))

    try:
        if check(fields):
            return 1
    except PatternsUnavailable as exc:
        print(f"anonymity guard: {exc}", file=sys.stderr)
        return 2

    gh_args: list[str] = ["issue", args.command]
    if args.command == "create":
        gh_args += ["--title", args.title, "--body-file", args.body_file]
        for label in args.label:
            gh_args += ["--label", label]
        for assignee in args.assignee:
            gh_args += ["--assignee", assignee]
    else:
        gh_args += [args.number, "--body-file", args.body_file]
    if args.repo:
        gh_args += ["--repo", args.repo]

    print("anonymity guard: clean.", file=sys.stderr)
    if args.dry_run:
        print(f"dry run - would call: gh {' '.join(gh_args)}", file=sys.stderr)
        return 0
    return run_gh(gh_args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
