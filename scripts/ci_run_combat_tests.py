# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Run combat in a disposable host with verified physical partner absence.

Install the selected contribs into a fresh venv first. This runner changes
only its explicitly supplied disposable game's test settings.
"""

import argparse
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from ci_run_partner_tests import LINKS_TEST_RUNNER, test_exit_code

PARTNERS = (
    "evennia_rp_party",
    "evennia_rp_chargen",
    "evennia_npcs",
    "evennia_scenes",
    "evennia_posing",
    "evennia_social",
    "evennia_accessibility",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--absent", action="append", default=[], choices=PARTNERS)
    args = parser.parse_args(argv)
    for partner in args.absent:
        if find_spec(partner) is not None:
            parser.error(f"{partner} is importable; use a fresh environment excluding it")
    game = args.game_dir.resolve()
    if not (game / "server/conf/settings.py").is_file():
        parser.error("Supply an initialized disposable game directory")
    launcher = str(Path(sys.executable).with_name("evennia"))
    if not Path(launcher).is_file():
        parser.error("evennia is not on PATH")
    (game / "server/conf/combat_test_settings.py").write_text(
        "from server.conf.settings import *\n"
        "PASSWORD_HASHERS = ('django.contrib.auth.hashers.MD5PasswordHasher',)\n"
        + LINKS_TEST_RUNNER,
        encoding="utf-8",
    )
    result = subprocess.run(
        [launcher, "test", "--settings=combat_test_settings.py", "evennia_rp_combat"],
        cwd=game,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return test_exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
