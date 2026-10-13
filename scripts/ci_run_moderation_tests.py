"""Run Moderation with only selected communication partners, then SQLite races."""

import argparse
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from ci_run_partner_tests import test_exit_code

PARTNERS = (
    "evennia_posing",
    "evennia_social",
    "evennia_boards",
    "evennia_rptracker",
    "evennia_npcs",
    "evennia_rp_party",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--absent", action="append", default=[], choices=PARTNERS)
    args = parser.parse_args()
    game = args.game_dir.resolve()
    for label in args.absent:
        if find_spec(label) is not None:
            parser.error(f"{label} is still importable; use a fresh environment")
    launcher = shutil.which("evennia")
    if launcher is None or not (game / "server/conf/settings.py").is_file():
        parser.error("Activate the test environment and supply a throwaway game")
    labels = ["evennia_links", "evennia_jobs", "evennia_moderation"] + [
        label for label in PARTNERS if find_spec(label) is not None
    ]
    (game / "server/conf/moderation_test_settings.py").write_text(
        "from server.conf.settings import *\n"
        f"INSTALLED_APPS += [label for label in {labels!r} if label not in INSTALLED_APPS]\n"
        f"MODERATION_ABSENT_PARTNERS = {args.absent!r}\n"
        "PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']\n",
        encoding="utf-8",
    )
    for settings_file, labels in (
        ("moderation_test_settings.py", ["evennia_moderation"]),
        ("moderation_race_settings.py", ["evennia_moderation.test_concurrency"]),
    ):
        if "race" in settings_file:
            (game / "server/conf" / settings_file).write_text(
                "from server.conf.moderation_test_settings import *\n"
                "from copy import deepcopy\nDATABASES = deepcopy(DATABASES)\n"
                f"DATABASES['default']['TEST'] = {{'NAME': {str(game / 'moderation-races.sqlite3')!r}}}\n",
                encoding="utf-8",
            )
        result = subprocess.run(
            [launcher, "test", "--noinput", "--settings", settings_file, *labels],
            cwd=game,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        code = test_exit_code(result)
        if code:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
