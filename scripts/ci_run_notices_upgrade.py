# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Populated upgrade in a disposable profile venv and game, never a live host.

Run through ci_profile.py. The profile must install all current contribs. This
runner temporarily installs the requested base checkout's local packages, seeds
legacy queues/markers, restores current packages, then verifies an additive upgrade.
"""

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
from pathlib import Path

from ci_install_contribs import pip_install_command

ROOT = Path(__file__).resolve().parent.parent
PREFIXES = ("evennia_calendar_", "evennia_lore_", "evennia_moderation_", "evennia_boards_")


def install(tree):
    """Replace local editable packages together without fetching dependencies."""
    packages = sorted((tree / "contribs").glob("*/*/pyproject.toml"))
    subprocess.run(
        [
            *pip_install_command(),
            "--no-deps",
            "--no-build-isolation",
            *[part for p in packages for part in ("-e", str(p.parent))],
        ],
        stdin=subprocess.DEVNULL,
        check=True,
    )


def snapshot():
    """Serialize complete source rows, including receipts and source-owned history."""
    from django.db import connection

    with connection.cursor() as cursor:
        names = [n for n in connection.introspection.table_names() if n.startswith(PREFIXES)]
        result = {}
        for name in names:
            cursor.execute(f'SELECT * FROM "{name}" ORDER BY rowid')
            result[name] = cursor.fetchall()
    return result


def worker(game, phase):
    """Each phase initializes a fresh process and model/app registry."""
    os.chdir(game)
    sys.path.insert(0, str(game))
    os.environ["DJANGO_SETTINGS_MODULE"] = "server.conf.settings"
    import django

    django.setup()
    import evennia

    evennia._init()
    from django.core.management import call_command
    from django.utils import timezone
    from evennia.accounts.models import AccountDB
    from evennia.objects.models import ObjectDB
    from evennia.utils.create import create_account, create_object
    from evennia.utils.dbserialize import deserialize

    state_path = game / "upgrade-state.json"
    if phase == "before":
        call_command("migrate", interactive=False, verbosity=0)
        account = create_account("Upgrade fixture", None, secrets.token_urlsafe(48))
        room = create_object(
            "evennia.objects.objects.DefaultRoom", key="Upgrade fixture room", nohome=True
        )
        character = create_object(
            "evennia.objects.objects.DefaultCharacter",
            key="Upgrade fixture character",
            location=room,
            home=room,
        )
        account.characters.add(character)
        now = timezone.now()
        from evennia_boards.models import Board, Post, PostReadSuppression, Subscription
        from evennia_calendar.models import RSVP, CalendarEvent, CalendarNotice
        from evennia_lore.models import LoreNotice
        from evennia_moderation.models import Notice as ModerationNotice

        event = CalendarEvent.objects.create(
            title="Upgrade fixture", creator=character, scheduled_time=now + timedelta(days=2)
        )
        rsvp = RSVP.objects.create(event=event, character=character, status=RSVP.Status.INVITED)
        CalendarNotice.objects.create(
            rsvp=rsvp,
            character=character,
            kind="invited",
            status=rsvp.status,
            message="Pending fixture",
        )
        CalendarNotice.objects.create(
            rsvp=rsvp,
            character=character,
            kind="reminder",
            status=rsvp.status,
            message="Delivered fixture",
            delivered_at=now,
        )
        LoreNotice.objects.create(character=character, message="Pending lore fixture")
        ModerationNotice.objects.create(account=account, text="Pending moderation fixture")
        board = Board.objects.create(name="Upgrade fixture board")
        post = Post.objects.create(
            board=board, post_number=1, author=character, title="Fixture", content="Fixture"
        )
        Subscription.objects.create(account=account, board=board, last_notified_at=now)
        PostReadSuppression.objects.create(account=account, post=post)
        account.db.boards_web_read = {str(board.pk): 1}
        markers = {
            "last_page_seen": now.isoformat(),
            "last_xp_summary_week": "2026-10-26",
            "last_resource_summary_week": "2026-10-26",
            "last_economy_summary": ["2026-10-26", 1],
        }
        for key, value in markers.items():
            character.attributes.add(key, value)
        state_path.write_text(
            json.dumps(
                {
                    "account": account.pk,
                    "character": character.pk,
                    "sources": snapshot(),
                    "markers": markers,
                    "board_read": deserialize(account.db.boards_web_read),
                },
                default=str,
            )
        )
        print("Created populated pre-foundation source fixture")
        return
    state = json.loads(state_path.read_text())
    call_command("migrate", interactive=False, verbosity=0)
    assert json.loads(json.dumps(snapshot(), default=str)) == state["sources"], (
        "Source rows changed during upgrade"
    )
    account = AccountDB.objects.get(pk=state["account"])
    character = ObjectDB.objects.get(pk=state["character"])
    assert deserialize(account.db.boards_web_read) == state["board_read"]
    for key, value in state["markers"].items():
        assert (
            json.loads(json.dumps(deserialize(character.attributes.get(key)), default=str)) == value
        ), key
    from evennia_links.notices import NoticeContext, NoticeEvent
    from evennia_notices.models import DeliveryReceipt
    from evennia_notices.services import maintain, mutate, route

    assert not DeliveryReceipt.objects.exists(), "Foundation must not import production queues"
    context = NoticeContext(account, character)
    result = route(
        account,
        source="fixture",
        event=NoticeEvent("upgrade-transition", timezone.now()),
        context=context,
    )
    assert result.status == "retained"
    receipt = DeliveryReceipt.objects.get()
    mutate(context, receipt.stored_event.notice.public_ref, "read")
    mutate(context, receipt.stored_event.notice.public_ref, "clear")
    call_command("migrate", interactive=False, verbosity=0)
    maintain()
    maintain()
    assert DeliveryReceipt.objects.count() == 1
    assert json.loads(json.dumps(snapshot(), default=str)) == state["sources"]
    # Legacy delivery remains active and exactly one pass consumes its own pending rows.
    from unittest.mock import patch

    from evennia_calendar.notices import deliver_pending as calendar_delivery
    from evennia_lore.notices import deliver_pending as lore_delivery
    from evennia_moderation.admissions import deliver_notices
    from evennia_moderation.models import Notice as ModerationNotice

    with patch.object(type(character), "msg") as msg:
        assert calendar_delivery(character) == 1
        assert calendar_delivery(character) == 0
        assert lore_delivery(character) == 1
        assert lore_delivery(character) == 0
        assert msg.call_count == 2
    with (
        patch.object(type(account), "msg") as msg,
        patch.object(type(account.sessions), "count", return_value=1),
    ):
        deliver_notices(account)
        deliver_notices(account)
        assert msg.call_count == 1
    assert ModerationNotice.objects.filter(delivered_at__isnull=True).count() == 0
    print(
        "Populated upgrade preserved all source rows/markers; legacy hooks and inbox lifecycle passed"
    )


def main(argv=None):
    """Materialize a base tree locally and always restore current package metadata."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--base", required=True)
    parser.add_argument("--worker", choices=("before", "after"))
    args = parser.parse_args(argv)
    game = args.game_dir.resolve()
    if args.worker:
        worker(game, args.worker)
        return 0
    if not (game / "server/conf/settings.py").exists():
        parser.error("Supply a disposable profile game")
    with tempfile.TemporaryDirectory(prefix="notices-upgrade-", dir=game.parent) as temporary:
        base = Path(temporary) / "base"
        base.mkdir()
        archive = subprocess.run(
            ["git", "archive", "--format=tar", args.base],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(base, filter="data")
        host = Path(temporary) / "host"
        shutil.copytree(
            base / "example_game",
            host,
            ignore=shutil.ignore_patterns("*.db3*", "secret_settings.py", "__pycache__"),
        )
        shutil.copyfile(
            ROOT / "scripts/ci_notices_partner_tests.py", host / "ci_notices_partner_tests.py"
        )
        settings_path = host / "server/conf/settings.py"
        current_settings = (ROOT / "example_game/server/conf/settings.py").read_text()
        suffix = "\nPASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']\n"
        try:
            install(base)
            settings_path.write_text(settings_path.read_text() + suffix)
            subprocess.run(
                [sys.executable, __file__, str(host), "--base", args.base, "--worker", "before"],
                stdin=subprocess.DEVNULL,
                check=True,
            )
        finally:
            install(ROOT)
        settings_path.write_text(
            current_settings
            + suffix
            + "\nLINKS_NOTICE_SOURCES = {'fixture': 'ci_notices_partner_tests.FixtureSource'}\n"
        )
        subprocess.run(
            [sys.executable, __file__, str(host), "--base", args.base, "--worker", "after"],
            stdin=subprocess.DEVNULL,
            check=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
