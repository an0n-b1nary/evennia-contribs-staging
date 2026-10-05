# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Run contest seams in a disposable host, verifying real partner absence.

Run after ci_install_contribs.py in a fresh venv. Repeat --absent for each
partner excluded from installation. A positive test count is mandatory.
"""

import argparse
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from ci_run_partner_tests import test_exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument(
        "--absent",
        action="append",
        default=[],
        choices=(
            "evennia_scenes",
            "evennia_rptracker",
            "evennia_rp_chargen",
        ),
    )
    args = parser.parse_args(argv)
    for partner in args.absent:
        if find_spec(partner) is not None:
            parser.error(f"{partner} is still importable; use a fresh environment with it excluded")
    game = args.game_dir.resolve()
    if not (game / "server/conf/settings.py").is_file():
        parser.error(f"no disposable game settings in {game}")
    launcher = shutil.which("evennia")
    if not launcher:
        parser.error("evennia is not on PATH")
    result = subprocess.run(
        [launcher, "test", "--settings=settings.py", "evennia_rp_contest"],
        cwd=game,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return test_exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
