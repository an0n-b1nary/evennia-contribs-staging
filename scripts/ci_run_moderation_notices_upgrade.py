# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Populated Moderation upgrade with physical Inbox removal and restoration."""

import argparse
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import Mock, patch

from ci_install_contribs import pip_install_command
from ci_run_notices_upgrade import ROOT, install, snapshot, source_columns


def worker(game, phase):
    """Use fresh app registries with one disposable populated source database."""
    os.chdir(game)
    sys.path.insert(0, str(game))
    os.environ["DJANGO_SETTINGS_MODULE"] = "server.conf.settings"
    import django

    django.setup()
    import evennia

    evennia._init()
    from django.apps import apps
    from django.core.management import call_command
    from django.utils import timezone
    from evennia.accounts.models import AccountDB
    from evennia.utils.create import create_account

    from evennia_moderation.models import Notice

    state_path = game / "moderation-upgrade-state.json"
    if phase == "before":
        call_command("migrate", interactive=False, verbosity=0)
        account = create_account("Moderation upgrade fixture", None, secrets.token_urlsafe(48))
        guest = create_account(
            "Guest moderation fixture",
            None,
            secrets.token_urlsafe(48),
            typeclass="evennia.accounts.accounts.DefaultGuest",
        )
        rows = [
            Notice.objects.create(account=account, text="Legacy private outcome").pk,
            Notice.objects.create(
                account=account, text="Legacy consumed", delivered_at=timezone.now()
            ).pk,
            Notice.objects.create(account=guest, text="Legacy guest private outcome").pk,
        ]
        state = {
            "account": account.pk,
            "guest": guest.pk,
            "legacy": rows,
            "columns": source_columns(),
        }
        state["sources"] = snapshot(state["columns"])
        state_path.write_text(json.dumps(state, default=str))
        print("Populated pre-adapter Moderation pending/delivered/guest history captured")
        return
    if phase == "after":
        call_command("migrate", interactive=False, verbosity=0)
    state = json.loads(state_path.read_text())
    account = AccountDB.objects.get(pk=state["account"])
    from evennia_links.notices import NoticeContext
    from evennia_moderation import notices

    def fixture(number):
        # Source-owned system outcome fixtures exercise transport; actual domain
        # approval/decline/expiry is covered by the source behavioral suite.
        return notices.record_outcome(
            account,
            kind="lapsed",
            submission_id=number,
            applicant_name="Synthetic referral application",
        )

    if phase == "after":
        assert json.loads(json.dumps(snapshot(state["columns"]), default=str)) == state["sources"]
        with patch.object(notices, "_safe_route", return_value="retry"):
            accepted, pending = fixture(701), fixture(702)
        assert notices.route_notice(accepted.pk) == "inbox"
        assert notices.route_notice(accepted.pk) == "inbox"
        assert notices.route_notice(state["legacy"][0]) == "held"
        assert notices.route_notice(state["legacy"][1]) == "fallback"
        from evennia_notices.services import mutate, project

        context = NoticeContext(account)
        items = project(context)
        assert len(items) == 1 and "Legacy" not in items[0].text
        mutate(context, items[0].notice.public_ref, "clear")
        assert project(context) == []
        state.update(accepted=accepted.pk, pending=pending.pk)
        state_path.write_text(json.dumps(state))
        print(
            "Additive upgrade preserved original columns/timestamps; typed outcome imported once; unknown legacy held"
        )
    elif phase == "absent":
        assert find_spec("evennia_notices") is None and not apps.is_installed("evennia_notices")
        try:
            metadata.distribution("evennia-notices")
        except metadata.PackageNotFoundError:
            pass
        else:
            raise AssertionError("Inbox distribution remains installed")
        assert notices.route_notice(state["accepted"]) == "inbox"
        session = Mock()
        session.get_account.return_value = account
        session.get_puppet.return_value = None
        context = NoticeContext(account, None, session)
        with patch.object(notices, "connected_contexts", return_value=[context]):
            assert notices.route_notice(state["pending"]) == "fallback"
            assert notices.route_notice(state["pending"]) == "fallback"
            fallback = fixture(703)
        fallback.refresh_from_db()
        assert fallback.route_state == "fallback" and session.msg.call_count == 2
        pending = fixture(704)
        state.update(fallback=fallback.pk, restored_pending=pending.pk)
        state_path.write_text(json.dumps(state))
        assert notices.transfer_pending(account)["held"] == 1
        assert notices.route_notice(state["legacy"][2]) == "held"
        print(
            "Inbox distribution/import/app absent; consumed source receipt did not replay; future fallback delivered once"
        )
    else:
        from evennia_notices.models import DeliveryReceipt

        assert notices.route_notice(state["accepted"]) == "inbox"
        assert notices.route_notice(state["pending"]) == "fallback"
        assert notices.route_notice(state["fallback"]) == "fallback"
        assert notices.route_notice(state["restored_pending"]) == "inbox"
        assert notices.route_notice(state["restored_pending"]) == "inbox"
        assert DeliveryReceipt.objects.filter(source="moderation").count() == 2
        assert Notice.objects.filter(pk__in=state["legacy"], provenance_known=False).count() == 3
        assert Notice.objects.filter(
            pk=state["legacy"][0], delivered_at=None, acknowledged_at=None
        ).exists()
        print(
            "Restored Inbox: retained/cleared/fallback outcomes never replayed; known pending imported once; legacy preserved"
        )


def main(argv=None):
    """Temporarily install archived base packages and always restore current metadata."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--base", required=True)
    parser.add_argument("--worker", choices=("before", "after", "absent", "restored"))
    args = parser.parse_args(argv)
    game = args.game_dir.resolve()
    if args.worker:
        worker(game, args.worker)
        return 0
    if not (game / "server/conf/settings.py").exists():
        parser.error("Supply an initialized disposable profile game")
    with tempfile.TemporaryDirectory(prefix="moderation-upgrade-", dir=game.parent) as temporary:
        base, host = Path(temporary) / "base", Path(temporary) / "host"
        base.mkdir()
        archive = subprocess.check_output(["git", "archive", "--format=tar", args.base], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(base, filter="data")
        shutil.copytree(
            base / "example_game",
            host,
            ignore=shutil.ignore_patterns("*.db3*", "secret_settings.py", "__pycache__"),
        )
        settings_path = host / "server/conf/settings.py"
        suffix = "\nPASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']\n"
        current = (ROOT / "example_game/server/conf/settings.py").read_text() + suffix

        def run(phase):
            subprocess.run(
                [sys.executable, __file__, str(host), "--base", args.base, "--worker", phase],
                stdin=subprocess.DEVNULL,
                check=True,
            )

        try:
            install(base)
            settings_path.write_text(settings_path.read_text() + suffix)
            run("before")
            install(ROOT)
            settings_path.write_text(current)
            run("after")
            uninstall = pip_install_command()
            uninstall[uninstall.index("install")] = "uninstall"
            if "-m" in uninstall:
                uninstall.append("-y")
            subprocess.run([*uninstall, "evennia-notices"], stdin=subprocess.DEVNULL, check=True)
            settings_path.write_text(
                current
                + "\nINSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'evennia_notices']\n"
            )
            run("absent")
            install(ROOT)
            settings_path.write_text(current)
            run("restored")
        finally:
            install(ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
