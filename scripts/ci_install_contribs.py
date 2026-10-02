# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Iterate contribs, pip-install each, append app labels to INSTALLED_APPS.

Contribs are installed in dependency order: each package's hard
`[project] dependencies` on *other contribs in this repo* are honoured, so a
contrib is always installed (and registered in INSTALLED_APPS) after every
contrib it requires. Without this, `pip install -e` of a dependent package
would try to fetch an unpublished sibling from PyPI and fail. Ties are broken
by path, which keeps the order stable and close to the old alphabetical one.

Optional dependencies (`[project.optional-dependencies]`) are deliberately not
ordering edges: optional partners are wired through gated `AppConfig.ready()`
blocks and settings seams that must work in any order, and two partners may
legitimately name each other as extras.

Also swaps in a fast (test-only) password hasher so the throwaway game's test
run isn't dominated by PBKDF2 hashing of the accounts EvenniaTest creates.

Invoked by `.github/workflows/ci.yml` from the repo root with one argument:
the path to the throwaway Evennia game directory created by `evennia --init`.
Optional --exclude arguments prepare a fresh environment without selected partners;
run this in a clean venv so previously installed packages cannot mask missing partners.
"""

from __future__ import annotations

import argparse
import heapq
import pathlib
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass

CONTRIBS_ROOT = pathlib.Path("contribs")

# PEP 508 distribution name at the start of a requirement string; anything
# after it (extras, version specifiers, markers) is irrelevant to ordering.
_REQUIREMENT_NAME = re.compile(r"\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")


class ContribGraphError(Exception):
    """The contribs' declared dependencies can't be ordered."""


@dataclass(frozen=True)
class Contrib:
    """One installable contrib package.

    Attributes:
        path: The package directory (holds `pyproject.toml`).
        name: The PEP 503-normalized distribution name.
        requires: Normalized names of every hard dependency, local or not.
    """

    path: pathlib.Path
    name: str
    requires: frozenset[str]

    @property
    def label(self) -> str:
        """str: The Django app label, which is the package directory name."""
        return self.path.name


def normalize_name(name: str) -> str:
    """Normalize a distribution name per PEP 503 (`Evennia_Links` -> `evennia-links`)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(requirement: str) -> str:
    """Return the normalized distribution name a PEP 508 requirement refers to.

    Raises:
        ContribGraphError: If the string doesn't start with a valid name.
    """
    match = _REQUIREMENT_NAME.match(requirement)
    if not match:
        raise ContribGraphError(f"can't parse requirement {requirement!r}")
    return normalize_name(match.group(1))


def load_contrib(path: pathlib.Path) -> Contrib:
    """Read a contrib's name and hard dependencies from its `pyproject.toml`."""
    with (path / "pyproject.toml").open("rb") as f:
        project = tomllib.load(f).get("project", {})
    if "name" not in project:
        raise ContribGraphError(f"{path / 'pyproject.toml'} has no [project] name")
    requires = frozenset(requirement_name(req) for req in project.get("dependencies", []))
    return Contrib(path=path, name=normalize_name(project["name"]), requires=requires)


def discover_contribs(root: pathlib.Path = CONTRIBS_ROOT) -> list[Contrib]:
    """Find every `<category>/<name>/` directory under `root` with a pyproject."""
    return [
        load_contrib(path)
        for path in sorted(root.glob("*/*/"))
        if (path / "pyproject.toml").exists()
    ]


def install_order(contribs: list[Contrib]) -> list[Contrib]:
    """Topologically sort contribs so local dependencies come first.

    Kahn's algorithm, breaking ties by path so the result is deterministic.
    Dependencies that aren't contribs in this repo (`evennia`, `djangorestframework`)
    are left to pip and play no part in the ordering.

    Raises:
        ContribGraphError: On a duplicate distribution name or a dependency cycle.
    """
    by_name: dict[str, Contrib] = {}
    for contrib in contribs:
        if contrib.name in by_name:
            raise ContribGraphError(
                f"{contrib.path} and {by_name[contrib.name].path} both declare {contrib.name!r}"
            )
        by_name[contrib.name] = contrib

    local_requires = {
        c.name: {dep for dep in c.requires if dep in by_name and dep != c.name} for c in contribs
    }
    dependents: dict[str, list[str]] = {name: [] for name in by_name}
    for name, deps in local_requires.items():
        for dep in deps:
            dependents[dep].append(name)

    pending = {name: len(deps) for name, deps in local_requires.items()}
    ready = [(by_name[name].path.as_posix(), name) for name, count in pending.items() if count == 0]
    heapq.heapify(ready)
    ordered: list[Contrib] = []
    while ready:
        _, name = heapq.heappop(ready)
        ordered.append(by_name[name])
        for dependent in dependents[name]:
            pending[dependent] -= 1
            if pending[dependent] == 0:
                heapq.heappush(ready, (by_name[dependent].path.as_posix(), dependent))

    if len(ordered) != len(contribs):
        stuck = sorted(name for name, count in pending.items() if count > 0)
        raise ContribGraphError(f"dependency cycle among: {', '.join(stuck)}")
    return ordered


def select_contribs(contribs: list[Contrib], exclude: tuple[str, ...] = ()) -> list[Contrib]:
    """Select a subset without allowing pip to reinstall an excluded hard dependency.

    Exclusions accept distribution names or app labels. Unknown names and retained
    packages requiring an excluded sibling fail before installation or settings edits.
    """
    excluded = {normalize_name(name) for name in exclude}
    known = {contrib.name for contrib in contribs}
    unknown = excluded - known
    if unknown:
        raise ContribGraphError(f"unknown excluded contribs: {', '.join(sorted(unknown))}")
    selected = [contrib for contrib in contribs if contrib.name not in excluded]
    for contrib in selected:
        missing = contrib.requires & excluded
        if missing:
            raise ContribGraphError(
                f"{contrib.name} requires excluded contribs: {', '.join(sorted(missing))}"
            )
    return install_order(selected)


def main(game_dir: pathlib.Path, exclude: tuple[str, ...] = ()) -> int:
    """Install each contrib and append its app label to the game's settings.

    Args:
        game_dir: Path to the Evennia game directory created by `evennia --init`.
        exclude: Distribution names or app labels to omit from installation.

    Returns:
        int: Process exit code (0 on success).
    """
    settings_path = game_dir / "server" / "conf" / "settings.py"
    if not settings_path.exists():
        print(f"settings.py not found at {settings_path}", file=sys.stderr)
        return 1

    try:
        contribs = select_contribs(discover_contribs(CONTRIBS_ROOT), exclude)
    except ContribGraphError as exc:
        print(f"Can't order contribs: {exc}", file=sys.stderr)
        return 1

    labels: list[str] = []
    for contrib in contribs:
        print(f"Installing {contrib.path}")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", str(contrib.path)],
            check=True,
            stdin=subprocess.DEVNULL,
        )
        labels.append(contrib.label)

    if not labels:
        print("No contribs to install yet.")
        return 0

    with settings_path.open("a", encoding="utf-8") as f:
        f.write("\n# Auto-added by scripts/ci_install_contribs.py (dependency order)\n")
        f.write("INSTALLED_APPS += [\n")
        for label in labels:
            f.write(f'    "{label}",\n')
        f.write("]\n")
        # Swap in a fast (insecure) password hasher for the test run. Every
        # contrib built on EvenniaTest creates two accounts per test in setUp,
        # and each create_account() runs "testpassword" through Django's default
        # PBKDF2 hasher, which is deliberately slow. MD5 makes those hashes
        # effectively free without changing behavior (they still verify). This
        # mirrors Evennia's own dummyrunner profiling mixin. CI/test only.
        f.write("\n# Fast test-only password hasher (see comment in this script).\n")
        f.write('PASSWORD_HASHERS = ("django.contrib.auth.hashers.MD5PasswordHasher",)\n')
    print(f"Registered {len(labels)} contrib app(s) in {settings_path}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=pathlib.Path)
    parser.add_argument("--exclude", action="append", default=[], metavar="CONTRIB")
    args = parser.parse_args()
    sys.exit(main(args.game_dir, tuple(args.exclude)))
