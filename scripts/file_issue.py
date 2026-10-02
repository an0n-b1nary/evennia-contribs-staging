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
    python scripts/file_issue.py comment 7 --repo owner/private-game --private --body-file reply.md

Both the title and the body are scanned. In the default mode, a pattern match
aborts before `gh` is invoked, and the offending lines are printed here —
in your terminal, which is private, unlike everything downstream of this script.

An explicit --private requires an explicit owner/name target and a successful
GitHub privacy check. It still scans and reports hits, but permits them on that
verified private target. Missing patterns or uncertain visibility fail closed.

This is a convenience, not a guarantee: nothing stops anyone opening
github.com and typing. The server-side sweep in
`.github/workflows/anonymity-issues.yml` is the backstop for that path.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _anonymity_text import PatternsUnavailable, require_patterns, scan_text


def read_body(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def check(fields: list[tuple[str, str]], *, private: bool = False) -> int:
    """Scan (label, text) pairs. Return count of offending lines."""
    patterns = require_patterns()
    hits: list[str] = []
    for label, text in fields:
        hits.extend(scan_text(label, text, patterns))
    if hits:
        message = "warning: private-repository text matches anonymity patterns."
        if not private:
            message = "anonymity guard: refusing to publish."
        print(message, file=sys.stderr)
        for hit in hits:
            print(hit, file=sys.stderr)
        if not private:
            print(
                "\nNothing was sent to GitHub. Rewrite the offending lines: "
                "'the source game' / 'a private Evennia game project' is the "
                "established public phrasing.",
                file=sys.stderr,
            )
    return len(hits)


def verify_private_repo(repo: str) -> None:
    """Require an explicit repository whose identity and privacy GitHub confirms."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("--private requires --repo owner/name")
    result = subprocess.run(
        ["gh", "repo", "view", repo, "--json", "nameWithOwner,isPrivate"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("could not verify repository visibility; nothing was published")
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid repository metadata; nothing was published") from exc
    if (
        not isinstance(metadata, dict)
        or not isinstance(metadata.get("nameWithOwner"), str)
        or metadata["nameWithOwner"].casefold() != repo.casefold()
        or metadata.get("isPrivate") is not True
    ):
        raise ValueError("--private requires the named repository to be verified private")


def run_gh(args: list[str]) -> int:
    print(f"+ gh {' '.join(args)}", file=sys.stderr)
    return subprocess.run(["gh", *args], check=False).returncode


def main(argv: list[str]) -> int:
    # Target and mode options go on both subcommands rather than the top level, so
    # they work in either position and the usage line reads like gh's.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="owner/name; defaults to the current repo")
    common.add_argument(
        "--private",
        action="store_true",
        help="require --repo to be verified private; report pattern hits as warnings",
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="scan and report (verify visibility with --private), but never publish",
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

    if args.private:
        try:
            verify_private_repo(args.repo or "")
        except (OSError, ValueError) as exc:
            print(f"anonymity guard: {exc}", file=sys.stderr)
            return 2
        print(f"verified private target: {args.repo}", file=sys.stderr)

    try:
        body = read_body(args.body_file)
    except OSError as exc:
        print(f"cannot read body file: {exc}", file=sys.stderr)
        return 2

    fields = [("body", body)]
    if args.command == "create":
        fields.insert(0, ("title", args.title))

    try:
        hits = check(fields, private=args.private)
        if hits and not args.private:
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

    if args.private:
        print(f"private publication: {args.repo}; {hits} matching line(s).", file=sys.stderr)
    else:
        print("anonymity guard: clean.", file=sys.stderr)
    if args.dry_run:
        print(f"dry run - would call: gh {' '.join(gh_args)}", file=sys.stderr)
        return 0
    return run_gh(gh_args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
