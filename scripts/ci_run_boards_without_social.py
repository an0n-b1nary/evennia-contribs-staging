# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Run the Boards suite in a disposable game with Social physically absent."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from ci_run_partner_tests import LINKS_TEST_RUNNER, test_exit_code


def main(argv: list[str] | None = None) -> int:
    """Generate isolated settings and require a positive Boards test run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    args = parser.parse_args(argv)
    if find_spec("evennia_social") is not None:
        parser.error("evennia-social is importable; use a fresh environment without it")

    game = args.game_dir.resolve()
    conf = game / "server" / "conf"
    if not (conf / "settings.py").is_file():
        parser.error(f"no Evennia settings.py in {conf}")
    launcher = shutil.which("evennia")
    if not launcher:
        parser.error("evennia is not on PATH; activate the isolated test environment")

    (conf / "boards_no_social_settings.py").write_text(
        "from server.conf.settings import *\n"
        "INSTALLED_APPS = [\n"
        "    app for app in INSTALLED_APPS\n"
        "    if app != 'evennia_social' and not app.startswith('evennia_social.')\n"
        "]\n"
        "REST_API_ENABLED = True\n" + LINKS_TEST_RUNNER,
        encoding="utf-8",
    )
    result = subprocess.run(
        [launcher, "test", "--settings=boards_no_social_settings.py", "evennia_boards"],
        cwd=game,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return test_exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
