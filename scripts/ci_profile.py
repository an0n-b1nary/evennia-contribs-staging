# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Run one partner profile's runner in a fresh environment of its own.

Creates a new venv and an `evennia --init` game in a new temporary directory,
installs Evennia and the profile's contribs into that venv, then runs the
command with the venv's executables first on PATH. `{game}` in the command
stands for the game directory. The directory is removed afterwards.

By default every contrib is installed and registered through
`ci_install_contribs.py`, less any `--exclude`. With `--package`, only those
contrib directories are installed, editable and unregistered, for runners that
write their own settings.

Each profile gets its own venv, so a partner one profile excludes is physically
absent there however many profiles a CI job runs in sequence. uv creates the
venv and installs when it's on PATH, as it is in CI; otherwise venv and pip do.

Example, from the repo root:

    python scripts/ci_profile.py --exclude evennia-scenes -- \\
        python scripts/ci_run_rp_contest_tests.py {game} --absent evennia_scenes
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

from ci_install_contribs import pip_install_command

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "scripts" / "ci_install_contribs.py"
# Pinned to the Evennia version the source project runs on. ci.yml sets the
# same value for jobs that install without this script.
EVENNIA_REQUIREMENT = os.environ.get("EVENNIA_REQUIREMENT", "evennia==6.0.0")


def create_venv(path: pathlib.Path) -> pathlib.Path:
    """Create an empty venv at `path` from this interpreter; return its python."""
    uv = shutil.which("uv")
    if uv:
        command = [uv, "venv", "--quiet", "--python", sys.executable, str(path)]
    else:
        command = [sys.executable, "-m", "venv", str(path)]
    subprocess.run(command, check=True, stdin=subprocess.DEVNULL)
    return path / "bin" / "python"


def activated(venv: pathlib.Path) -> dict[str, str]:
    """Return this process's environment with `venv` activated."""
    env = dict(os.environ, VIRTUAL_ENV=str(venv))
    env["PATH"] = os.pathsep.join([str(venv / "bin"), env.get("PATH", "")])
    env.pop("PYTHONHOME", None)
    return env


def prepare(
    workdir: pathlib.Path, exclude: tuple[str, ...] = (), packages: tuple[str, ...] = ()
) -> tuple[pathlib.Path, dict[str, str]]:
    """Build the profile's venv and game in `workdir`; return the game and environment."""
    venv, game = workdir / "venv", workdir / "game"
    python = str(create_venv(venv))
    env = activated(venv)
    pip = pip_install_command(python)
    run = {"check": True, "stdin": subprocess.DEVNULL, "env": env}
    subprocess.run([*pip, EVENNIA_REQUIREMENT], **run)
    subprocess.run([str(venv / "bin" / "evennia"), "--init", str(game)], cwd=workdir, **run)
    if packages:
        editables = [arg for package in packages for arg in ("-e", package)]
        subprocess.run([*pip, *editables], cwd=REPO_ROOT, **run)
    else:
        excludes = [arg for name in exclude for arg in ("--exclude", name)]
        subprocess.run([python, str(INSTALLER), str(game), *excludes], cwd=REPO_ROOT, **run)
    return game, env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--exclude", action="append", default=[], metavar="CONTRIB")
    selection.add_argument("--package", action="append", default=[], metavar="PATH")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("give the runner command after --")

    grouped = os.environ.get("GITHUB_ACTIONS") == "true"
    workdir = pathlib.Path(
        tempfile.mkdtemp(prefix="ci-profile-", dir=os.environ.get("RUNNER_TEMP"))
    )
    try:
        if grouped:
            print("::group::Fresh environment", flush=True)
        started = time.monotonic()
        try:
            game, env = prepare(workdir, tuple(args.exclude), tuple(args.package))
        except subprocess.CalledProcessError as exc:
            print(f"Setting up the profile failed: {exc}", file=sys.stderr)
            return 1
        finally:
            if grouped:
                print("::endgroup::", flush=True)
        print(f"Fresh environment ready in {time.monotonic() - started:.1f} s", flush=True)
        command = [part.replace("{game}", str(game)) for part in command]
        executable = shutil.which(command[0], path=env["PATH"]) or command[0]
        return subprocess.run(
            [executable, *command[1:]], cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL
        ).returncode
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
