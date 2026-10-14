# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Run Crafting with only Links and Resources in a fresh initialized game."""

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
    args = parser.parse_args(argv)
    for partner in (
        "evennia_economy",
        "evennia_rp_equipment",
        "evennia_accessibility",
        "evennia_building",
        "evennia_scenes",
        "evennia_social",
        "evennia_rp_combat",
    ):
        if find_spec(partner) is not None:
            parser.error(f"{partner} is still importable; use a fresh environment")
    game = args.game_dir.resolve()
    if not (game / "server/conf/settings.py").exists():
        parser.error("initialize a disposable Evennia game first")
    launcher = shutil.which("evennia")
    if not launcher:
        parser.error("evennia is not on PATH")
    (game / "server/conf/core_crafting_settings.py").write_text(
        "from server.conf.settings import *\n"
        "INSTALLED_APPS += ['evennia_links', 'evennia_rp_resources', 'evennia_rp_crafting']\n"
        "PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [launcher, "test", "--settings=core_crafting_settings.py", "evennia_rp_crafting"],
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
