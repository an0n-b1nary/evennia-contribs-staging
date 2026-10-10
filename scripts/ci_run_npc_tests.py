# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Exercise NPCs with real partners present or physically absent."""

import argparse
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from ci_run_partner_tests import test_exit_code

PARTNERS = (
    "evennia_scenes",
    "evennia_plots",
    "evennia_rp_contest",
    "evennia_posing",
    "evennia_rptracker",
    "evennia_rp_chargen",
    "evennia_xp",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--absent", action="append", default=[], choices=PARTNERS)
    args = parser.parse_args(argv)
    for partner in args.absent:
        if find_spec(partner) is not None:
            parser.error(f"{partner} is importable; use a fresh environment with it excluded")
    game = args.game_dir.resolve()
    if not (game / "server/conf/settings.py").is_file():
        parser.error("Supply an initialized disposable game directory")
    launcher = shutil.which("evennia")
    if launcher is None:
        parser.error("evennia is not on PATH")
    shutil.copyfile(
        Path(__file__).with_name("ci_npc_partner_tests.py"), game / "ci_npc_partner_tests.py"
    )
    (game / "server/conf/npc_test_settings.py").write_text(
        "from server.conf.settings import *\nNPCS_REVEALED = True\nNPCS_FROZEN = False\n"
        "NPCS_TYPECLASS = 'evennia_npcs.typeclasses.NPCCharacter'\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            launcher,
            "test",
            "--settings=npc_test_settings.py",
            "evennia_npcs",
            "ci_npc_partner_tests",
        ],
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
