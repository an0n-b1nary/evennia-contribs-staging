# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Check contrib versions without importing Django apps or configuring a game.

The exported version must match package metadata and the latest released
changelog heading. A leading Unreleased section is allowed for future work,
including a new contrib whose first release is still being prepared.
Use --installed after editable installation to check distribution metadata too.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

CONTRIBS_ROOT = Path(__file__).resolve().parent.parent / "contribs"
HEADING = re.compile(r"^##\s+\[?(Unreleased|\d+\.\d+\.\d+)\]?(?=\s|$)", re.MULTILINE)


def exported_version(path: Path) -> str:
    """Read the literal __version__ assignment without executing package code."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__version__"
                for target in node.targets
            )
        ) or (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__version__"
        ):
            values.append(ast.literal_eval(node.value))
    if len(values) != 1 or not isinstance(values[0], str):
        raise ValueError("expected exactly one literal string __version__ assignment")
    return values[0]


def check_contrib(path: Path, *, installed: bool = False) -> list[str]:
    """Return version/changelog errors for one contrib, optionally checking its install."""
    errors = []
    try:
        with (path / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]
        declared = project["version"]
        exported = exported_version(path / "__init__.py")
        if exported != declared:
            errors.append(f"__version__ {exported!r} != project version {declared!r}")
        headings = HEADING.findall((path / "CHANGELOG.md").read_text(encoding="utf-8"))
        if not headings:
            errors.append("changelog has no release or Unreleased heading")
        elif "Unreleased" in headings[1:]:
            errors.append("Unreleased must appear once, before all released versions")
        releases = [heading for heading in headings if heading != "Unreleased"]
        if releases and releases[0] != declared:
            errors.append(
                f"latest changelog release {releases[0]!r} != project version {declared!r}"
            )
        if installed:
            actual = version(project["name"])
            if actual != declared:
                errors.append(f"installed version {actual!r} != project version {declared!r}")
    except (OSError, ValueError, SyntaxError, KeyError, TypeError, PackageNotFoundError) as exc:
        errors.append(str(exc))
    return [f"{path.name}: {error}" for error in errors]


def main(argv: list[str] | None = None) -> int:
    """Check every discovered contrib and return a failing status on any drift."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args(argv)
    paths = sorted(path.parent for path in CONTRIBS_ROOT.glob("*/*/pyproject.toml"))
    if not paths:
        print("No contribs found; refusing an empty version check.", file=sys.stderr)
        return 1
    errors = [error for path in paths for error in check_contrib(path, installed=args.installed)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Version and changelog checks passed for {len(paths)} contribs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
