# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Run resources in a disposable host and verify physical partner absence."""

import argparse
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distribution
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
            "evennia_maps",
            "evennia_regions",
            "evennia_plots",
            "evennia_notices",
            "evennia_economy",
            "evennia_social",
            "evennia_rptracker",
        ),
    )
    args = parser.parse_args(argv)
    for name in args.absent:
        if find_spec(name) is not None:
            parser.error(f"{name} is still importable; use a fresh environment with it excluded")
        try:
            distribution(name.replace("_", "-"))
        except PackageNotFoundError:
            pass
        else:
            parser.error(f"{name} distribution remains installed")
    game = args.game_dir.resolve()
    if not (game / "server/conf/settings.py").is_file():
        parser.error("Supply an initialized disposable game directory.")
    launcher = shutil.which("evennia")
    if not launcher:
        parser.error("evennia is not on PATH")
    shutil.copyfile(
        Path(__file__).with_name("ci_resources_partner_tests.py"),
        game / "ci_resources_partner_tests.py",
    )
    # ci_profile's package selection installs only the requested packages.
    # Its blank game leaves registration to the profile runner.
    installed = [
        name
        for name in ("evennia_links", "evennia_rp_resources", "evennia_notices")
        if find_spec(name) is not None
    ]
    (game / "server/conf/resources_test_settings.py").write_text(
        "from server.conf.settings import *\n"
        + "INSTALLED_APPS = list(INSTALLED_APPS)\n"
        + f"INSTALLED_APPS += [label for label in {installed!r} if label not in INSTALLED_APPS]\n"
        + f"RESOURCES_ABSENT_PARTNERS = {args.absent!r}\n"
        + "PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']\n"
        + "TEST_RUNNER = 'evennia_links.testing.TestRunner'\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            launcher,
            "test",
            "--settings=resources_test_settings.py",
            "evennia_rp_resources",
            "ci_resources_partner_tests",
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
