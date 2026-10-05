"""Run the reference game's RP seams in a fresh host with verified absence.

Install selected contribs in a fresh venv first with ci_install_contribs.py.
The destination must be new; existing accounts, databases and secrets are
never copied. With all partners present, run the entire sandbox gate.
"""

import argparse
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from ci_run_partner_tests import test_exit_code

ROOT = Path(__file__).resolve().parents[1]
PARTNERS = (
    "evennia_scenes",
    "evennia_rptracker",
    "evennia_xp",
    "evennia_rp_chargen",
    "evennia_rp_contest",
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
    settings.write_text(source, encoding="utf-8")
    labels = (
        ["world.sandbox.test_rp_partners"] if args.absent else ["typeclasses", "commands", "world"]
    )
    result = subprocess.run(
        [launcher, "test", "--settings=test_settings.py", *labels],
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
