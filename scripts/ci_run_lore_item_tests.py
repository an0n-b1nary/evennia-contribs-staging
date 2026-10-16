# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Exercise lore/items with each optional partner actually uninstalled."""

import argparse
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from ci_run_partner_tests import test_exit_code

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--absent", choices=("evennia_lore", "evennia_rp_crafting"))
    args = parser.parse_args(argv)
    if args.absent and find_spec(args.absent) is not None:
        parser.error(f"{args.absent} is still importable; use a fresh environment")
    game = args.game_dir.resolve()
    if game.exists():
        parser.error("destination must be a new disposable directory")
    launcher = shutil.which("evennia")
    if not launcher:
        parser.error("evennia is not on PATH")
    if args.absent == "evennia_lore":
        subprocess.run([launcher, "--init", str(game)], stdin=subprocess.DEVNULL, check=True)
        with (game / "server/conf/settings.py").open("a", encoding="utf-8") as settings:
            settings.write(
                '\nINSTALLED_APPS += ["evennia_links", "evennia_rp_resources", "evennia_rp_crafting"]\n'
            )
            settings.write('PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]\n')
        labels, setting_name = ["evennia_rp_crafting"], "settings.py"
    else:
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
        if args.absent:
            source = settings.read_text(encoding="utf-8")
            entry = f'    "{args.absent}",\n'
            if source.count(entry) != 1:
                parser.error(f"expected one app entry for {args.absent}")
            settings.write_text(source.replace(entry, ""), encoding="utf-8")
        labels = ["evennia_lore", "world.sandbox.test_lore_items"]
        if not args.absent:
            labels += [
                "world.sandbox.test_readables",
                "evennia_rp_crafting",
                "evennia_rp_equipment",
                "evennia_links.test_pagination",
            ]
        setting_name = "test_settings.py"
    result = subprocess.run(
        [launcher, "test", "--noinput", f"--settings={setting_name}", *labels],
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
