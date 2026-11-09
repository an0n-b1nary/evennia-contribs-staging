# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Run real installed/physically absent notice partner profiles."""

import argparse
import importlib.metadata
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from ci_run_partner_tests import LINKS_TEST_RUNNER, test_exit_code


def main(argv=None):
    """Configure only a disposable game and require a positive test count."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--absent", action="append", default=[])
    parser.add_argument("--minimal", action="store_true")
    args = parser.parse_args(argv)
    for name in args.absent:
        if find_spec(name) is not None:
            parser.error(f"{name} remains importable; create a fresh excluded profile")
        try:
            importlib.metadata.distribution(name.replace("_", "-"))
        except importlib.metadata.PackageNotFoundError:
            pass
        else:
            parser.error(f"{name} distribution remains installed")
    game = args.game_dir.resolve()
    settings = game / "server/conf/settings.py"
    if not settings.is_file():
        parser.error("Supply an initialized disposable game")
    shutil.copyfile(
        Path(__file__).with_name("ci_notices_partner_tests.py"),
        game / "ci_notices_partner_tests.py",
    )
    extras = ""
    if args.minimal:
        extras = "\nINSTALLED_APPS += ['evennia_links', 'evennia_notices']\n"
    (game / "server/conf/notices_test_settings.py").write_text(
        "from server.conf.settings import *\n"
        + extras
        + f"NOTICES_ABSENT_PARTNERS = {args.absent!r}\n"
        + LINKS_TEST_RUNNER
        + "PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']\n"
        + "LINKS_NOTICE_SOURCES = {'fixture': 'ci_notices_partner_tests.FixtureSource'}\n"
    )
    labels = ["ci_notices_partner_tests", "evennia_links.test_notices"]
    if find_spec("evennia_notices") is not None:
        labels.append("evennia_notices")
    else:
        labels.extend(
            name
            for name in ("evennia_calendar", "evennia_lore", "evennia_moderation")
            if find_spec(name)
        )
    if find_spec("evennia_social") is not None:
        labels.extend(
            [
                "evennia_social.tests.test_notice_ignores",
                "evennia_social.tests.test_notice_ownership",
            ]
        )
    result = subprocess.run(
        [shutil.which("evennia"), "test", "--settings=notices_test_settings.py", *labels],
        cwd=game,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return test_exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
