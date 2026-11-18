# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Prove Boards 0001 upgrades populated legacy data into sparse exclusions."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4


def worker(game: Path, settings_name: str) -> int:
    """Create historical data at 0001, upgrade, then remove both ignore forms."""
    os.chdir(game)
    sys.path.insert(0, str(game))
    os.environ["DJANGO_SETTINGS_MODULE"] = f"server.conf.{settings_name}"

    import django

    django.setup()
    import evennia

    evennia._init()

    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from django.utils import timezone
    from evennia.accounts.models import AccountDB
    from evennia.server import initial_setup
    from evennia.server.models import ServerConfig
    from evennia.utils import create

    from evennia_boards.models import Board, Post, PostReadSuppression, Subscription
    from evennia_boards.presentation import unread_post_count
    from evennia_social import ignore

    call_command("migrate", interactive=False, verbosity=0)
    AccountDB.objects.create_superuser(
        username="admin", email="", password="boards-upgrade-test-only"
    )
    initial_setup.create_objects()
    initial_setup.at_initial_setup()
    ServerConfig.objects.conf("last_initial_setup_step", "done")
    initial_target = [("evennia_boards", "0001_initial")]
    executor = MigrationExecutor(connection)
    executor.migrate(initial_target)
    initial_apps = executor.loader.project_state(initial_target).apps
    LegacyBoard = initial_apps.get_model("evennia_boards", "Board")
    LegacyPost = initial_apps.get_model("evennia_boards", "Post")
    LegacySubscription = initial_apps.get_model("evennia_boards", "Subscription")
    assert "evennia_boards_postreadsuppression" not in connection.introspection.table_names()

    reader_account = create.create_account("UpgradeReader", None, "upgrade-test-password")
    author_account = create.create_account("NamedAuthor", None, "upgrade-test-password")
    legacy_account = create.create_account("LegacyAuthor", None, "upgrade-test-password")
    reader = create.create_object(
        "evennia.objects.objects.DefaultCharacter", key="UpgradeReader", location=None
    )
    named_author = create.create_object(
        "evennia.objects.objects.DefaultCharacter", key="NamedAuthor", location=None
    )
    legacy_author = create.create_object(
        "evennia.objects.objects.DefaultCharacter", key="LegacyAuthor", location=None
    )
    reader_account.characters.add(reader)
    author_account.characters.add(named_author)
    legacy_account.characters.add(legacy_author)
    reader_account.permissions.clear()
    reader_account.is_superuser = False
    reader_account.save()

    ignore.set_entry(reader_account, named_author)
    reader_account.attributes.add("ignore_list", [legacy_account.pk])
    ignore.set_boards_preference(reader_account, "hide")
    legacy_board = LegacyBoard.objects.create(name="Upgrade board")

    def create_legacy_post(number, author, title, content, **fields):
        return LegacyPost.all_objects.create(
            board=legacy_board,
            post_number=number,
            author_id=author.pk,
            author_name=author.key,
            title=title,
            content=content,
            **fields,
        )

    visible_a = create_legacy_post(1, reader, "A", "visible A")
    hidden_named = create_legacy_post(2, named_author, "B", "named hidden")
    visible_reply = create_legacy_post(
        3, reader, "Visible reply", "reply stays unread", parent_post=hidden_named
    )
    visible_c = create_legacy_post(4, reader, "C", "visible C")
    hidden_legacy = create_legacy_post(
        5,
        legacy_author,
        "D",
        "legacy hidden",
        is_archived=True,
        archived_at=timezone.now(),
        archived_by_id=legacy_author.pk,
        archived_by_name=legacy_author.key,
    )
    cutoff = timezone.now() - timedelta(hours=1)
    legacy_subscription = LegacySubscription.objects.create(
        account_id=reader_account.pk, board=legacy_board, last_notified_at=cutoff
    )
    reader_account.attributes.add("boards_web_read", {str(legacy_board.pk): visible_a.post_number})

    # Both ignore forms predate the suppression table. On the current
    # schema, the first policy mutation snapshots both before clearing them.
    suppression_target = [("evennia_boards", "0002_postreadsuppression")]
    executor = MigrationExecutor(connection)
    executor.migrate(suppression_target)
    suppression_apps = executor.loader.project_state(suppression_target).apps
    assert not suppression_apps.get_model("evennia_boards", "PostReadSuppression").objects.exists()
    call_command("migrate", "evennia_boards", interactive=False, verbosity=0)

    board = Board.objects.get(pk=legacy_board.pk)
    subscription = Subscription.objects.get(pk=legacy_subscription.pk)
    hidden_legacy = Post.all_objects.get(pk=hidden_legacy.pk)
    assert hidden_legacy.is_archived
    assert ignore.clear(reader_account) == 2

    hidden_legacy.unarchive()
    new_post = Post.create_post(board, named_author, "New B", "new after clear")
    reader_account.attributes.reset_cache()
    markers = dict(reader_account.attributes.get("boards_web_read"))
    assert markers == {str(board.pk): visible_a.post_number}
    assert set(
        PostReadSuppression.objects.filter(account=reader_account).values_list("post_id", flat=True)
    ) == {hidden_named.pk, hidden_legacy.pk}
    assert subscription.unread_count() == 4  # A, reply, C, and the genuinely new B.
    assert (
        unread_post_count(
            reader_account,
            Post.objects.filter(board=board, post_number__gt=markers[str(board.pk)]),
        )
        == 3
    )  # Reply, C, and the genuinely new B; the web marker did not move.
    assert not PostReadSuppression.objects.filter(
        account=reader_account, post_id=visible_reply.pk
    ).exists()
    assert new_post.post_number > visible_c.post_number
    subscription.refresh_from_db()
    assert subscription.last_notified_at == cutoff
    print("Populated Boards 0001 → 0002 upgrade preserved legacy and named suppression state.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Prepare a file-backed disposable game and run the isolated worker."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    args = parser.parse_args(argv)
    game = args.game_dir.resolve()
    conf = game / "server" / "conf"
    if not (conf / "settings.py").is_file():
        parser.error(f"no Evennia settings.py in {conf}")
    run_id = uuid4().hex
    settings_name = f"boards_upgrade_{run_id}_settings"
    settings_path = conf / f"{settings_name}.py"
    database_path = game / f"boards-upgrade-{run_id}.sqlite3"
    settings_path.write_text(
        "from copy import deepcopy\n"
        "from server.conf.settings import *\n"
        "DATABASES = deepcopy(DATABASES)\n"
        f"DATABASES['default']['NAME'] = {str(database_path)!r}\n"
        "PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                str(game),
                settings_name,
            ],
            cwd=game,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    finally:
        settings_path.unlink(missing_ok=True)
        database_path.unlink(missing_ok=True)
        Path(f"{database_path}-wal").unlink(missing_ok=True)
        Path(f"{database_path}-shm").unlink(missing_ok=True)
    return result.returncode


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--worker":
        sys.exit(worker(Path(sys.argv[2]).resolve(), sys.argv[3]))
    sys.exit(main())
