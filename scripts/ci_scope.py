# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Select the CI partner jobs a change can affect.

A pull request runs lint and the main suite, plus only the partner jobs whose
contribs, or the files they read, it touches. Pushes to main, the nightly run
and manual runs pass --all and run every job.

A job runs when a changed contrib, or any contrib depending on it through hard
dependencies or optional extras (transitively), is one the job installs. It
also runs when a file it reads outside contribs/ changes. Top-level docs and
lint-only files select nothing. Any other path selects every job, so an
unclassified file fails safe.

Prints `jobs=<JSON list>` for $GITHUB_OUTPUT and explains the choice on stderr.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import pathlib
import subprocess
import sys
import tomllib

from ci_install_contribs import discover_contribs, requirement_name

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
EVERY_CONTRIB = None

# Job name in ci.yml -> (contribs it installs and exercises, other paths it
# reads). EVERY_CONTRIB marks jobs that load the whole example game. Partners
# a job only verifies as absent aren't listed: their changes can't reach it.
JOBS = {
    "lore-items-partners": (
        {"evennia_lore", "evennia_rp_crafting", "evennia_rp_resources", "evennia_rp_equipment"},
        ("scripts/ci_run_lore_item_tests.py", "example_game/"),
    ),
    "calendar-partners": (
        {
            "evennia_calendar",
            "evennia_maps",
            "evennia_regions",
            "evennia_scenes",
            "evennia_building",
            "evennia_lore",
            "evennia_social",
        },
        (
            "scripts/ci_partner_tests.py",
            "example_game/web/templates/rest_framework/api.html",
        ),
    ),
    "building-partners": (
        {
            "evennia_building",
            "evennia_maps",
            "evennia_regions",
            "evennia_jobs",
            "evennia_moderation",
            "evennia_economy",
            "evennia_social",
        },
        ("scripts/ci_building_partner_tests.py",),
    ),
    "resources-partners": (
        {
            "evennia_rp_resources",
            "evennia_maps",
            "evennia_regions",
            "evennia_plots",
            "evennia_social",
            "evennia_rptracker",
            "evennia_economy",
        },
        ("scripts/ci_run_resources_tests.py", "scripts/ci_resources_partner_tests.py"),
    ),
    "economy-partners": (
        {
            "evennia_economy",
            "evennia_rp_resources",
            "evennia_rp_crafting",
            "evennia_jobs",
            "evennia_moderation",
            "evennia_building",
            "evennia_rp_equipment",
        },
        ("scripts/ci_run_economy_tests.py", "scripts/ci_economy_partner_tests.py"),
    ),
    "crafting-partners": (
        {
            "evennia_rp_crafting",
            "evennia_economy",
            "evennia_rp_equipment",
            "evennia_accessibility",
            "evennia_building",
            "evennia_scenes",
        },
        ("scripts/ci_run_crafting_tests.py", "example_game/"),
    ),
    "rp-contest-partners": (
        {
            "evennia_rp_contest",
            "evennia_scenes",
            "evennia_rptracker",
            "evennia_rp_chargen",
            "evennia_rp_equipment",
        },
        ("scripts/ci_run_rp_contest_tests.py",),
    ),
    "sandbox": (EVERY_CONTRIB, ("scripts/ci_run_rp_sandbox_tests.py", "example_game/")),
    "rp-sandbox": (
        {
            "evennia_scenes",
            "evennia_rptracker",
            "evennia_xp",
            "evennia_rp_chargen",
            "evennia_rp_equipment",
            "evennia_rp_contest",
        },
        ("scripts/ci_run_rp_sandbox_tests.py", "example_game/"),
    ),
    "crafting-independent": (
        {"evennia_rp_crafting", "evennia_rp_resources"},
        ("scripts/ci_run_crafting_core_tests.py",),
    ),
    "npc-partners": (
        {
            "evennia_npcs",
            "evennia_scenes",
            "evennia_plots",
            "evennia_rp_contest",
            "evennia_posing",
            "evennia_social",
            "evennia_rptracker",
            "evennia_xp",
            "evennia_rp_chargen",
            "evennia_rp_equipment",
        },
        ("scripts/ci_run_npc_tests.py", "scripts/ci_npc_partner_tests.py"),
    ),
    "live-playtest": (
        EVERY_CONTRIB,
        (
            "example_game/",
            "scripts/playtest.py",
            "scripts/playtesting/",
            "scripts/test_playtest.py",
            "scripts/test_playtest_interactive.py",
        ),
    ),
    "moderation-partners": (
        {
            "evennia_jobs",
            "evennia_moderation",
            "evennia_posing",
            "evennia_social",
            "evennia_boards",
            "evennia_rptracker",
        },
        ("scripts/ci_run_moderation_tests.py",),
    ),
    "combat-independent": (
        {"evennia_rp_rules", "evennia_rp_combat", "evennia_npcs"},
        ("scripts/ci_run_combat_tests.py",),
    ),
    "party-independent": (
        {"evennia_rp_rules", "evennia_rp_combat", "evennia_rp_party", "evennia_rp_contest"},
        ("scripts/ci_run_party_tests.py",),
    ),
}

# Paths no partner job reads: top-level docs, editor and repo settings, and
# files only lint, the main suite or other workflows use. Lint and the main
# suite run on every pull request.
NO_PARTNER_JOB = (
    "*.md",
    "LICENSE",
    ".editorconfig",
    ".gitignore",
    ".anonymity-patterns.example",
    "*.code-workspace",
    "pyproject.toml",
    ".pre-commit-config.yaml",
    ".github/workflows/anonymity-issues.yml",
    ".github/workflows/downstream.yml",
    "scripts/*.md",
    "scripts/*anonymity*.py",
    "scripts/*file_issue.py",
    "scripts/*check_contrib_versions.py",
    "scripts/*check_templates.py",
    "scripts/*check_command_syntax.py",
    "scripts/command_syntax_allowlist.txt",
    "scripts/*downstream*.py",
    "scripts/calibrate_*.py",
    "scripts/ui_shots.py",
    "scripts/ci_run_tests.py",
    "scripts/test_ci_install_contribs.py",
    "scripts/test_ci_profile.py",
    "scripts/test_ci_run_partner_tests.py",
    "scripts/test_ci_scope.py",
)


def partner_graph(root: pathlib.Path) -> dict[str, set[str]]:
    """Map each contrib's app label to the sibling labels it requires or can use."""
    contribs = discover_contribs(root)
    labels = {contrib.name: contrib.label for contrib in contribs}
    graph = {}
    for contrib in contribs:
        with (contrib.path / "pyproject.toml").open("rb") as f:
            project = tomllib.load(f).get("project", {})
        extras = project.get("optional-dependencies", {}).values()
        names = set(contrib.requires).union(
            requirement_name(req) for reqs in extras for req in reqs
        )
        graph[contrib.label] = {labels[name] for name in names if name in labels} - {contrib.label}
    return graph


def dependents(changed: set[str], graph: dict[str, set[str]]) -> set[str]:
    """Return `changed` plus every contrib that reaches one of them through `graph`."""
    affected = set(changed)
    grew = True
    while grew:
        grew = False
        for label, partners in graph.items():
            if label not in affected and partners & affected:
                affected.add(label)
                grew = True
    return affected


def select_jobs(
    paths: list[str], root: pathlib.Path = REPO_ROOT / "contribs"
) -> tuple[list[str], list[str]]:
    """Return the jobs to run for changed repo-relative `paths`, and why."""
    changed, direct, reasons = set(), set(), []
    for path in paths:
        parts = path.split("/")
        if parts[0] == "contribs" and len(parts) > 3:
            changed.add(parts[2])
            continue
        readers = {
            job for job, (_, reads) in JOBS.items() if any(path.startswith(r) for r in reads)
        }
        if readers:
            direct |= readers
            reasons.append(f"{path}: read by {', '.join(sorted(readers))}")
        elif not any(
            # `*` would cross `/`, so a pattern only matches at its own depth.
            path.count("/") == pattern.count("/") and fnmatch.fnmatchcase(path, pattern)
            for pattern in NO_PARTNER_JOB
        ):
            return list(JOBS), [f"{path}: not classified, so every job runs"]
    affected = dependents(changed, partner_graph(root))
    if changed:
        reasons.append(f"changed contribs: {', '.join(sorted(changed))}")
        reasons.append(f"with dependents: {', '.join(sorted(affected))}")
    for job, (contribs, _) in JOBS.items():
        if affected and (contribs is EVERY_CONTRIB or contribs & affected):
            direct.add(job)
    return [job for job in JOBS if job in direct], reasons


def changed_paths(base: str, head: str) -> list[str]:
    """List files changed between two revisions, renames as both old and new paths."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", base, head],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--all", action="store_true", help="run every job")
    source.add_argument("--diff", nargs=2, metavar=("BASE", "HEAD"))
    source.add_argument("--paths", nargs="+", metavar="PATH")
    args = parser.parse_args(argv)
    if args.all:
        jobs, reasons = list(JOBS), ["full run"]
    else:
        jobs, reasons = select_jobs(args.paths or changed_paths(*args.diff))
    for reason in reasons:
        print(reason, file=sys.stderr)
    print(f"selected: {', '.join(jobs) or 'no partner jobs'}", file=sys.stderr)
    print(f"jobs={json.dumps(jobs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
