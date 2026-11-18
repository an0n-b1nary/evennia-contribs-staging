# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Populated Boards upgrade with physical Inbox removal and restoration."""

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
from datetime import timedelta
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path

from ci_install_contribs import pip_install_command
from ci_run_notices_upgrade import ROOT, install, snapshot, source_columns


def worker(game, phase):
    """Verify the same populated Boards state under each optional Inbox configuration."""
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
    from evennia.utils.create import create_account, create_object
    from evennia.utils.dbserialize import deserialize

    from evennia_boards.models import Board, Post, PostReadSuppression, Subscription

    state_path = game / "boards-upgrade-state.json"
    if phase == "before":
        call_command("migrate", interactive=False, verbosity=0)
        account = create_account("Boards upgrade fixture", None, secrets.token_urlsafe(48))
        room = create_object("evennia.objects.objects.DefaultRoom", key="Fixture room", nohome=True)
        author = create_object(
            "evennia.objects.objects.DefaultCharacter",
            key="Fixture author",
            location=room,
            home=room,
        )
        board = Board.objects.create(name="Upgrade fixture board")
        sub = Subscription.objects.create(
            account=account, board=board, last_notified_at=timezone.now() - timedelta(days=1)
        )
        previously_read = Post.create_post(board, author, "Read title", "Read prose")
        PostReadSuppression.objects.create(account=account, post=previously_read)
        pending = Post.create_post(board, author, "Protected title", "Protected prose")
        Post.create_post(board, None, "Ambiguous title", "Ambiguous prose")
        account.db.boards_web_read = {str(board.pk): 1}
        columns = {
            table: fields
            for table, fields in source_columns().items()
            if table.startswith("evennia_boards_")
        }
        state_path.write_text(
            json.dumps(
                {
                    "account": account.pk,
                    "board": board.pk,
                    "subscription": sub.pk,
                    "pending": pending.pk,
                    "suppression": previously_read.pk,
                    "columns": columns,
                    "source": snapshot(columns),
                },
                default=str,
            )
        )
        print("Populated Boards subscriptions, suppression receipts and historical posts captured")
        return

    from evennia_boards.notice_test_helpers import connected_session
    from evennia_boards.notices import notify_login, prepare_account
    from evennia_links.notices import NoticeContext

    if phase == "after":
        call_command("migrate", interactive=False, verbosity=0)
    state = json.loads(state_path.read_text())
    account = AccountDB.objects.get(pk=state["account"])
    board = Board.objects.get(pk=state["board"])
    assert deserialize(account.db.boards_web_read) == {str(board.pk): 1}
    assert list(
        PostReadSuppression.objects.filter(account=account).values_list("post_id", flat=True)
    ) == [state["suppression"]]
    if phase == "after":
        from evennia_notices.services import mutate, project

        assert json.loads(json.dumps(snapshot(state["columns"]), default=str)) == state["source"]
        sub = Subscription.objects.get(pk=state["subscription"])
        assert sub.inbox_start_post_id is None and sub.discovery_post_id is None
        context = NoticeContext(account)
        prepare_account(account.pk)
        prepare_account(account.pk)
        [item] = project(context)
        assert item.events[0].payload["post"] == state["pending"]
        assert item.text == "New activity on Upgrade fixture board"
        mutate(context, item.notice.public_ref, "clear")
        assert not project(context)
        print("Legacy rows preserved, eligible activity transferred quietly once")
    elif phase in {"disabled", "absent"}:
        if phase == "absent":
            assert find_spec("evennia_notices") is None and not apps.is_installed("evennia_notices")
            try:
                metadata.distribution("evennia-notices")
            except metadata.PackageNotFoundError:
                pass
            else:
                raise AssertionError("Inbox distribution remains installed")
        with connected_session(account) as session:
            notify_login(account, session)
            session.msg.assert_not_called()
            Post.create_post(board, None, f"{phase} fixture title", "Standalone fixture")
            notify_login(account, session)
            session.msg.assert_called_once()
            assert "1 new post" in session.msg.call_args.args[0]
            notify_login(account, session)
            session.msg.assert_called_once()
        if phase == "absent":
            Post.create_post(board, None, "Deferred fixture title", "Restoration fixture")
        print(
            f"{phase}: previously delivered Inbox activity stayed consumed, new standalone sent once"
        )
    else:
        from evennia_notices.models import DeliveryReceipt
        from evennia_notices.services import project

        prepare_account(account.pk)
        prepare_account(account.pk)
        [item] = project(NoticeContext(account))
        assert item.events[0].payload["post"] == Post.objects.get(title="Deferred fixture title").pk
        assert DeliveryReceipt.objects.filter(source="boards").count() == 2
        print(
            "Restored Inbox: only new pending Boards activity transferred; consumed scopes stayed sealed"
        )


def main(argv=None):
    """Temporarily install archived base packages and always restore current metadata."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--base", required=True)
    parser.add_argument("--worker", choices=("before", "after", "disabled", "absent", "restored"))
    args = parser.parse_args(argv)
    game = args.game_dir.resolve()
    if args.worker:
        worker(game, args.worker)
        return 0
    if not (game / "server/conf/settings.py").exists():
        parser.error("Supply an initialized disposable profile game")
    with tempfile.TemporaryDirectory(prefix="boards-upgrade-", dir=game.parent) as temporary:
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
            settings_path.write_text(current + "\nNOTICES_ENABLED = False\n")
            run("disabled")
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
