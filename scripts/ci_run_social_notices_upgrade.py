# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Populated Social page upgrade with physical Inbox removal and restoration."""

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
from ci_run_notices_upgrade import ROOT, install


def worker(game, phase):
    """Open the same populated database with each installed package state."""
    os.chdir(game)
    sys.path.insert(0, str(game))
    os.environ["DJANGO_SETTINGS_MODULE"] = "server.conf.settings"
    import django

    django.setup()
    import evennia

    evennia._init()
    from datetime import timedelta

    from django.apps import apps
    from django.core.management import call_command
    from django.utils import timezone
    from evennia.accounts.models import AccountDB
    from evennia.comms.models import Msg
    from evennia.objects.models import ObjectDB
    from evennia.utils.create import create_account, create_object

    from evennia_social.commands.messaging import CmdPage

    def send(sender, receiver, body):
        command = CmdPage()
        command.caller = sender
        command._send_page(sender, [receiver], body)
        return Msg.objects.latest("pk")

    state_path = game / "social-page-upgrade-state.json"
    if phase == "before":
        call_command("migrate", interactive=False, verbosity=0)
        accounts = [
            create_account(f"Page upgrade fixture {number}", None, secrets.token_urlsafe(48))
            for number in range(4)
        ]
        guest = create_account(
            "Guest page upgrade fixture",
            None,
            secrets.token_urlsafe(48),
            typeclass="evennia.accounts.accounts.DefaultGuest",
        )
        characters = [
            create_object(
                "typeclasses.characters.Character", key=f"Fixture Character {number}", nohome=True
            )
            for number in range(5)
        ]
        for owner, character in zip([*accounts, guest], characters, strict=True):
            owner.characters.add(character)
        accounts[2].characters.add(characters[1])
        sender, receiver, _, no_cutoff, guest_character = characters
        guest_character.tags.add("character", category="guest")
        cutoff = timezone.now()
        receiver.last_page_seen = cutoff.isoformat()
        legacy_ids = []
        for offset in (-1, 0, 1):
            page = send(sender, receiver, f"Legacy page fixture {offset}")
            Msg.objects.filter(pk=page.pk).update(
                db_date_created=cutoff + timedelta(seconds=offset)
            )
            legacy_ids.append(page.pk)
        kept = send(sender, no_cutoff, "Legacy page with no previous puppet")
        guest_page = send(sender, guest_character, "Legacy guest page")
        receiver.db.account = accounts[1]
        from evennia_social import ignore

        ignored = create_object("typeclasses.characters.Character", key="Ignored page sender")
        ignored_actor = create_account("Ignored fixture account", None, secrets.token_urlsafe(48))
        ignored_actor.characters.add(ignored)
        ignore.set_entry(accounts[1], ignored)
        hidden = send(ignored, receiver, "Legacy hidden page")
        state = {
            "accounts": [account.pk for account in [*accounts, guest]],
            "characters": [character.pk for character in characters],
            "legacy": [*legacy_ids, kept.pk, guest_page.pk, hidden.pk],
            "history": list(Msg.objects.values_list("pk", "db_message").order_by("pk")),
        }
        state_path.write_text(json.dumps(state))
        print("Populated Social page history with cutoffs, shared ownership, ignore and guest")
        return

    if phase == "after":
        call_command("migrate", interactive=False, verbosity=0)
    state = json.loads(state_path.read_text())
    _, owner, co_owner, no_cutoff_owner, guest = [
        AccountDB.objects.get(pk=pk) for pk in state["accounts"]
    ]
    sender, receiver, alt, no_cutoff, guest_character = [
        ObjectDB.objects.get(pk=pk) for pk in state["characters"]
    ]
    from evennia_links.notices import NoticeContext
    from evennia_social import notices
    from evennia_social.models import PageDelivery

    def connect(account, character):
        session = Mock()
        session.get_account.return_value = account
        session.get_puppet.return_value = character
        return session

    context = NoticeContext(owner, receiver)
    sessions = "evennia.server.sessionhandler.SESSIONS.get_sessions"
    if phase == "after":
        from evennia.server.signals import SIGNAL_OBJECT_POST_PUPPET

        from evennia_notices.services import project, set_preference

        assert [
            list(row) for row in Msg.objects.values_list("pk", "db_message").order_by("pk")
        ] == state["history"]
        session = connect(owner, receiver)
        receiver.account = owner
        with patch(sessions, return_value=[session]):
            SIGNAL_OBJECT_POST_PUPPET.send(sender=receiver, account=owner, session=session)
        assert PageDelivery.objects.get(character=receiver).message_id == state["legacy"][2]
        assert len(project(context, source="social-pages")) == 1
        assert len(project(NoticeContext(co_owner, receiver), source="social-pages")) == 1
        assert not project(NoticeContext(co_owner, alt), source="social-pages")
        call_command("transfer_social_page_notices", character=no_cutoff.dbref, limit=1)
        assert len(project(NoticeContext(no_cutoff_owner, no_cutoff), source="social-pages")) == 1
        guest_character.account = guest
        guest_session = connect(guest, guest_character)
        with patch(sessions, return_value=[guest_session]):
            guest_character._notify_unread_pages()
            guest_character._notify_unread_pages()
        guest_session.msg.assert_called_once()
        assert "You have 1 unread page" in guest_session.msg.call_args.args[0]
        assert not PageDelivery.objects.filter(character=guest_character).exists()
        assert guest_character.last_page_seen is None
        set_preference(context, "social-pages", "off")
        set_preference(NoticeContext(co_owner, receiver), "social-pages", "off")
        consumed = send(sender, receiver, "Page with Inbox source off")
        assert PageDelivery.objects.get(message=consumed).state == "suppressed"
        set_preference(context, "social-pages", "summary")
        with patch.object(notices, "_safe_route", return_value="retry"):
            pending = send(sender, receiver, "Page awaiting a route")
        state.update(consumed=consumed.pk, pending=pending.pk)
        print("Migrated, re-puppeted and transferred legacy pages with exact ownership")
    elif phase == "absent":
        assert find_spec("evennia_notices") is None and not apps.is_installed("evennia_notices")
        try:
            metadata.distribution("evennia-notices")
        except metadata.PackageNotFoundError:
            pass
        else:
            raise AssertionError("Inbox distribution remains installed")
        session = connect(owner, receiver)
        with patch(sessions, return_value=[session]):
            receiver._notify_unread_pages()
            receiver._notify_unread_pages()
        session.msg.assert_called_once()
        assert "You have 1 unread page" in session.msg.call_args.args[0]
        assert PageDelivery.objects.get(message_id=state["pending"]).state == "fallback"
        state["restore_pending"] = send(sender, receiver, "Pending until Inbox returns").pk
        print("Physically absent Inbox delivered one standalone aggregate")
    else:
        from evennia_notices.models import DeliveryReceipt

        assert notices.prepare(context)[0]["inbox"] == 1
        notices.prepare(context)
        assert PageDelivery.objects.get(message_id=state["pending"]).state == "fallback"
        assert PageDelivery.objects.get(message_id=state["consumed"]).state == "suppressed"
        assert PageDelivery.objects.get(message_id=state["restore_pending"]).state == "inbox"
        assert DeliveryReceipt.objects.filter(source="social-pages").count() == 4
        print("Restored Inbox with one newly retained page and no replay")
    state_path.write_text(json.dumps(state))


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
    with tempfile.TemporaryDirectory(prefix="social-page-upgrade-", dir=game.parent) as temporary:
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
