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
from importlib.util import find_spec
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# For suites long enough to repay worker start-up: one worker per CPU, each
# with its own copy of the test database (DJANGO_TEST_PROCESSES overrides the
# count). File-backed race runs stay serial.
PARALLEL = "--parallel=auto"
# Evennia 6.0's test mixin leaves a login task and queued log writes behind per
# test, so a serial run slows with every test. Hosts that
# ci_install_contribs.py doesn't configure add this line to their settings;
# see evennia_links/testing.py.
LINKS_TEST_RUNNER = 'TEST_RUNNER = "evennia_links.testing.TestRunner"\n'


def building_profile(game, absent, launcher):
    """Use a standalone URLconf so no optional URL import survives removal."""
    for label in absent:
        if find_spec(label) is not None:
            raise ValueError(
                f"{label} is still importable; use a fresh environment with it excluded"
            )
    shutil.copyfile(
        REPO_ROOT / "scripts/ci_building_partner_tests.py", game / "ci_building_partner_tests.py"
    )
    (game / "server/conf/building_test_settings.py").write_text(
        "from server.conf.settings import *\n"
        'ROOT_URLCONF = "ci_building_partner_tests"\n'
        f"BUILDING_ABSENT_PARTNERS = {absent!r}\n"
        "BUILDING_REVEALED = True\n"
        'LINKS_ROOM_PERMISSION = "evennia_building.access.room_permission"\n'
        'LINKS_ROOM_OWNER = "evennia_building.access.owner_of"\n'
        'LOCK_FUNC_MODULES = (*LOCK_FUNC_MODULES, "evennia_building.lockfuncs")\n'
        'MAPS_ROOM_VISIBILITY = "evennia_building.visibility.room_visibility"\n'
        "REGIONS_ROOM_VISIBILITY = MAPS_ROOM_VISIBILITY\n"
        "REST_API_ENABLED = False\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            launcher,
            "test",
            "--settings=building_test_settings.py",
            PARALLEL,
            "ci_building_partner_tests",
        ],
        cwd=game,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    code = test_exit_code(result)
    if code:
        return code
    # SQLite in-memory databases reject a competing writer immediately. A
    # separate file-backed run exercises real commit ordering and stale states.
    (game / "server/conf/building_race_settings.py").write_text(
        "from server.conf.building_test_settings import *\n"
        "from copy import deepcopy\n"
        "DATABASES = deepcopy(DATABASES)\n"
        f"DATABASES['default']['TEST'] = {{'NAME': {str(game / 'building-races.sqlite3')!r}}}\n",
        encoding="utf-8",
    )
    labels = ["evennia_building.test_concurrency"]
    if find_spec("evennia_jobs") is not None:
        labels.append("evennia_jobs.test_concurrency")
    result = subprocess.run(
        [launcher, "test", "--noinput", "--settings=building_race_settings.py", *labels],
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
    parser.add_argument("--calendar", choices=("present", "absent"))
    parser.add_argument("--building", action="store_true")
    parser.add_argument(
        "--absent",
        action="append",
        default=[],
        choices=(
            "evennia_maps",
            "evennia_regions",
            "evennia_jobs",
            "evennia_economy",
            "evennia_social",
        ),
    )
    parser.add_argument("--labels", nargs="+", default=["ci_partner_tests", "evennia_maps"])
    args = parser.parse_args(argv)
    game = args.game_dir.resolve()
    conf = game / "server" / "conf"
    if not (conf / "settings.py").is_file():
        parser.error(f"no Evennia settings.py in {conf}")
    launcher = shutil.which("evennia")
    if not launcher:
        parser.error("evennia is not on PATH; activate the test environment")
    if args.building:
        return building_profile(game, args.absent, launcher)
    if args.calendar is None:
        parser.error("Supply --calendar or --building")
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
        [launcher, "test", "--settings=partner_test_settings.py", PARALLEL, *args.labels],
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
