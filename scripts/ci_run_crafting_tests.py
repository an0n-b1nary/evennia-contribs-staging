# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Fresh reference host with actual crafting partners present or physically absent."""

import argparse
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from ci_run_partner_tests import test_exit_code

ROOT = Path(__file__).resolve().parents[1]
PARTNERS = (
    "evennia_economy",
    "evennia_rp_equipment",
    "evennia_accessibility",
    "evennia_building",
    "evennia_scenes",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--absent", action="append", default=[], choices=PARTNERS)
    args = parser.parse_args(argv)
    for partner in args.absent:
        if find_spec(partner) is not None:
            parser.error(f"{partner} is still importable; use a fresh environment with it excluded")
    game = args.game_dir.resolve()
    if game.exists():
        parser.error("destination must be a new disposable directory")
    launcher = shutil.which("evennia")
    if not launcher:
        parser.error("evennia is not on PATH")
    shutil.copytree(
        ROOT / "example_game",
        game,
        ignore=shutil.ignore_patterns(
            "*.db3*",
            "secret_settings.py",
            "__pycache__",
            "*.pyc",
            "*.log*",
            "*.pid",
            "*.restart",
            ".static",
            ".media",
        ),
    )
    settings = game / "server/conf/settings.py"
    source = settings.read_text(encoding="utf-8")
    for partner in args.absent:
        entry = f'    "{partner}",\n'
        if source.count(entry) != 1:
            parser.error(f"expected one app entry for {partner}")
        source = source.replace(entry, "")
    # No crafting web surface: avoid importing other packages' optional web
    # extras (which require accessibility) in its physically absent profile.
    source += '\nROOT_URLCONF = "crafting_test_urls"\n'
    if "evennia_building" in args.absent:
        source += "\nLINKS_ROOM_PERMISSION = None\nLINKS_ROOM_OWNER = None\nLINKS_ROOM_LIVE = None\nLINKS_ROOM_LOCK = None\nLINKS_OWNED_ROOMS = None\nSOCIAL_ROOM_MOOD_PERMISSION = None\n"
    settings.write_text(source, encoding="utf-8")
    (game / "crafting_test_urls.py").write_text("urlpatterns = []\n", encoding="utf-8")
    result = subprocess.run(
        [
            launcher,
            "test",
            "--settings=test_settings.py",
            "evennia_rp_crafting",
            "world.sandbox.test_crafting",
            "world.sandbox.test_wave_two",
        ],
        cwd=game,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    code = test_exit_code(result)
    if code or "evennia_building" in args.absent:
        return code
    (game / "server/conf/crafting_race_settings.py").write_text(
        "from server.conf.test_settings import *\n"
        "from copy import deepcopy\n"
        "DATABASES = deepcopy(DATABASES)\n"
        f"DATABASES['default']['TEST'] = {{'NAME': {str(game / 'crafting-races.sqlite3')!r}}}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            launcher,
            "test",
            "--noinput",
            "--settings=crafting_race_settings.py",
            "evennia_rp_crafting.test_concurrency",
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
