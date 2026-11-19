# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Run real installed/physically absent notice partner profiles."""

import argparse
import importlib.metadata
import shutil
import subprocess
import sys
import tempfile
from email import message_from_bytes
from importlib.util import find_spec
from pathlib import Path
from zipfile import ZipFile

from ci_run_partner_tests import LINKS_TEST_RUNNER, test_exit_code


def check_plots_metadata():
    """Exercise the real wheel and editable metadata outside the inventory tree."""
    source = Path(__file__).resolve().parents[1] / "contribs/game_systems/evennia_plots"
    installed = importlib.metadata.distribution("evennia-plots")
    expected = {"evennia>=6.0", "evennia-links>=0.8.15"}

    def dependencies(requirements):
        return {item for item in requirements if ";" not in item}

    if dependencies(installed.requires or ()) != expected:
        raise ValueError("Installed Plots dependencies differ from the minimal profile")
    with tempfile.TemporaryDirectory(prefix="plots-wheel-") as temporary:
        scratch = Path(temporary)
        copy = scratch / "source"
        shutil.copytree(source, copy, ignore=shutil.ignore_patterns("*.egg-info", "__pycache__"))
        uv = shutil.which("uv")
        command = (
            [uv, "build", "--wheel", "--out-dir", str(scratch), str(copy)]
            if uv
            else [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(scratch), str(copy)]
        )
        subprocess.run(command, check=True, stdin=subprocess.DEVNULL)
        (wheel,) = scratch.glob("evennia_plots-*.whl")
        with ZipFile(wheel) as contents:
            (meta,) = [name for name in contents.namelist() if name.endswith(".dist-info/METADATA")]
            built = message_from_bytes(contents.read(meta))
            if dependencies(built.get_all("Requires-Dist", [])) != expected:
                raise ValueError("Plots wheel dependencies differ from the minimal profile")
            if "evennia_plots/integrations/notices.py" not in contents.namelist():
                raise ValueError("Plots wheel is missing its notice source")


def main(argv=None):
    """Configure only a disposable game and require a positive test count."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--absent", action="append", default=[])
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--minimal", action="store_true")
    selection.add_argument("--minimal-boards", action="store_true")
    selection.add_argument("--minimal-calendar", action="store_true")
    selection.add_argument("--minimal-lore", action="store_true")
    selection.add_argument("--minimal-moderation", action="store_true")
    selection.add_argument("--minimal-social", action="store_true")
    selection.add_argument("--minimal-plots", action="store_true")
    selection.add_argument("--minimal-xp", action="store_true")
    args = parser.parse_args(argv)
    if args.minimal_xp:
        args.absent = sorted(
            set(args.absent) | {"evennia_links", "evennia_notices", "evennia_accessibility"}
        )
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
    if args.minimal_xp:
        (game / "server/conf/notices_test_settings.py").write_text(
            "from server.conf.settings import *\n"
            + "\nif 'evennia_xp' not in INSTALLED_APPS: INSTALLED_APPS += ['evennia_xp']\n"
            + f"XP_ABSENT_PARTNERS = {args.absent!r}\n"
            + "PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']\n"
        )
        return run_suite(game, ["evennia_xp.test_notice_standalone"])
    shutil.copyfile(
        Path(__file__).with_name("ci_notices_partner_tests.py"),
        game / "ci_notices_partner_tests.py",
    )
    extras = ""
    if args.minimal:
        extras = "\nINSTALLED_APPS += ['evennia_links', 'evennia_notices']\n"
    elif args.minimal_boards:
        extras = "\nINSTALLED_APPS += ['evennia_links', 'evennia_boards']\n"
    elif args.minimal_calendar:
        extras = "\nINSTALLED_APPS += ['evennia_links', 'evennia_calendar']\n"
    elif args.minimal_lore:
        extras = "\nINSTALLED_APPS += ['evennia_links', 'evennia_lore']\n"
    elif args.minimal_moderation:
        extras = "\nINSTALLED_APPS += ['evennia_links', 'evennia_jobs', 'evennia_moderation']\n"
    elif args.minimal_social:
        extras = "\nINSTALLED_APPS += ['evennia_links', 'evennia_posing', 'evennia_social']\n"
    elif args.minimal_plots:
        extras = "\nINSTALLED_APPS += ['evennia_links', 'evennia_plots']\n"
        check_plots_metadata()
    sources = {"fixture": "ci_notices_partner_tests.FixtureSource"}
    if find_spec("evennia_boards") is not None:
        sources["boards"] = "evennia_boards.integrations.notices.BoardNoticeSource"
    if find_spec("evennia_calendar") is not None:
        sources["calendar"] = "evennia_calendar.integrations.notices.CalendarNoticeSource"
    if find_spec("evennia_lore") is not None:
        sources["lore"] = "evennia_lore.integrations.notices.LoreNoticeSource"
    if find_spec("evennia_moderation") is not None:
        sources["moderation"] = "evennia_moderation.integrations.notices.ModerationNoticeSource"
    if find_spec("evennia_social") is not None:
        sources["social-pages"] = "evennia_social.integrations.notices.SocialPageNoticeSource"
    if find_spec("evennia_plots") is not None:
        sources["plots"] = "evennia_plots.integrations.notices.PlotNoticeSource"
    if find_spec("evennia_xp") is not None:
        sources["xp"] = "evennia_xp.integrations.notices.XPNoticeSource"
    if find_spec("evennia_rp_resources") is not None:
        sources["resources"] = "evennia_rp_resources.integrations.notices.ResourcesNoticeSource"
    (game / "server/conf/notices_test_settings.py").write_text(
        "from server.conf.settings import *\n"
        + extras
        + f"NOTICES_ABSENT_PARTNERS = {args.absent!r}\n"
        + LINKS_TEST_RUNNER
        + "PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']\n"
        + f"LINKS_NOTICE_SOURCES = {sources!r}\n"
    )
    labels = ["ci_notices_partner_tests", "evennia_links.test_notices"]
    if find_spec("evennia_notices") is not None:
        labels.append("evennia_notices")
    if find_spec("evennia_moderation") is not None:
        labels.append("evennia_moderation")
    if find_spec("evennia_boards") is not None:
        if find_spec("evennia_notices") is None:
            labels.append("evennia_boards.test_notice_adapter.StandaloneActivityTests")
        else:
            labels.extend(
                ["evennia_boards.test_notice_adapter", "evennia_boards.test_notice_concurrency"]
            )
    if find_spec("evennia_lore") is not None:
        labels.append("evennia_lore.test_notice_adapter" if args.minimal_lore else "evennia_lore")
    if find_spec("evennia_calendar") is not None:
        labels.extend(
            ["evennia_calendar.test_notice_adapter", "evennia_calendar.test_notice_repairs"]
            if args.minimal_calendar
            else ["evennia_calendar"]
        )
    if find_spec("evennia_social") is not None:
        labels.extend(
            [
                "evennia_social.tests.test_notice_ignores",
                "evennia_social.tests.test_notice_ownership",
            ]
        )
        if find_spec("evennia_notices") is None:
            labels.append("evennia_social.tests.test_page_notices.StandalonePageTests")
        else:
            labels.extend(
                [
                    "evennia_social.tests.test_page_notices",
                    "evennia_social.tests.test_page_notice_concurrency",
                ]
            )
    if find_spec("evennia_plots") is not None:
        if find_spec("evennia_notices") is None:
            labels.append("evennia_plots.test_notice_adapter.StandalonePlotNoticeTests")
        else:
            labels.extend(
                ["evennia_plots.test_notice_adapter", "evennia_plots.test_notice_concurrency"]
            )
    if find_spec("evennia_rp_resources") is not None:
        labels.extend(
            ["evennia_rp_resources.test_notices", "evennia_rp_resources.test_notice_concurrency"]
        )
    if find_spec("evennia_xp") is not None:
        labels.append("evennia_xp.test_notice_standalone")
        if find_spec("evennia_notices") is not None:
            labels.extend(["evennia_xp.test_notice_inbox", "evennia_xp.test_notice_concurrency"])
    return run_suite(game, labels)


def run_suite(game, labels):
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
