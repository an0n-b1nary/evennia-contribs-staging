# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Configure a disposable CI game and run fresh-process partner integration tests.

Run after ci_install_contribs.py, never against a live game. The game gets its
own copied test URLconf/fixture and browsable API override. Its original settings
are unchanged. The calendar expectation is explicit, so an allegedly absent
partner that remains importable or installed makes the tests fail.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_exit_code(result: subprocess.CompletedProcess) -> int:
    """Fail a launcher that exits zero without actually running any tests."""
    print(result.stdout, end="")
    if result.returncode:
        return result.returncode
    if not re.search(r"^Ran [1-9]\d* tests?\b", result.stdout, re.MULTILINE):
        print("No positive test count; refusing a silently-green Evennia run.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Prepare the throwaway game and invoke tests with a bare settings filename."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--calendar", required=True, choices=("present", "absent"))
    parser.add_argument("--labels", nargs="+", default=["ci_partner_tests", "evennia_maps"])
    args = parser.parse_args(argv)
    game = args.game_dir.resolve()
    conf = game / "server" / "conf"
    if not (conf / "settings.py").is_file():
        parser.error(f"no Evennia settings.py in {conf}")
    launcher = shutil.which("evennia")
    if not launcher:
        parser.error("evennia is not on PATH; activate the test environment")
    shutil.copyfile(REPO_ROOT / "scripts" / "ci_partner_tests.py", game / "ci_partner_tests.py")
    template = game / "web" / "templates" / "rest_framework" / "api.html"
    template.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        REPO_ROOT / "example_game" / "web" / "templates" / "rest_framework" / "api.html", template
    )
    (conf / "partner_test_settings.py").write_text(
        "from server.conf.settings import *\n"
        'ROOT_URLCONF = "ci_partner_tests"\n'
        'MAPS_UNMAPPABLE_ROOM_TYPES = ("ooc",)\n'
        "REST_API_ENABLED = False\n"
        f"PARTNER_TEST_CALENDAR = {args.calendar == 'present'}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [launcher, "test", "--settings=partner_test_settings.py", *args.labels],
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
