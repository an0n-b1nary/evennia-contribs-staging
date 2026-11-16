# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Populated Lore upgrade and actual Inbox removal/restoration in disposable hosts."""

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
    """Every phase has a fresh app registry and the same disposable database."""
    os.chdir(game)
    sys.path.insert(0, str(game))
    os.environ["DJANGO_SETTINGS_MODULE"] = "server.conf.settings"
    import django

    django.setup()
    import evennia

    evennia._init()
    from django.apps import apps
    from django.core.management import call_command
    from evennia.accounts.models import AccountDB
    from evennia.objects.models import ObjectDB
    from evennia.utils.create import create_account, create_object

    from evennia_lore.models import LoreAcquisition, LoreEntry, LoreNotice

    state_path = game / "lore-upgrade-state.json"
    if phase == "before":
        call_command("migrate", interactive=False, verbosity=0)
        account = create_account("Lore upgrade fixture", None, secrets.token_urlsafe(48))
        character = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Lore upgrade character", nohome=True
        )
        account.characters.add(character)
        entry = LoreEntry.create_entry(
            "Historical Lore", author=character, body="Preserved content"
        )
        LoreAcquisition.objects.create(entry=entry, character=character, source="share")
        rows = [
            LoreNotice.objects.create(character=character, entry=entry, message=text).pk
            for text in ("Old private decline", "Old unsealing")
        ]
        rows.append(LoreNotice.objects.create(character=character, message="Old advisory").pk)
        guest_account = create_account(
            "Guest lore fixture",
            None,
            secrets.token_urlsafe(48),
            typeclass="evennia.accounts.accounts.DefaultGuest",
        )
        guest = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Guest lore character", nohome=True
        )
        guest.tags.add("character", category="guest")
        guest_account.characters.add(guest)
        rows.append(
            LoreNotice.objects.create(character=guest, entry=entry, message="Old guest history").pk
        )
        state = {
            "account": account.pk,
            "character": character.pk,
            "entry": entry.pk,
            "guest": guest.pk,
            "legacy": rows,
            "columns": source_columns(),
        }
        state["sources"] = snapshot(state["columns"])
        state_path.write_text(json.dumps(state, default=str))
        print(
            "Populated pre-adapter Lore: decisions, advisory, acquisition and guest history recorded"
        )
        return
    if phase == "after":
        call_command("migrate", interactive=False, verbosity=0)
    state = json.loads(state_path.read_text())
    account = AccountDB.objects.get(pk=state["account"])
    character = ObjectDB.objects.get(pk=state["character"])
    entry = LoreEntry.objects.get(pk=state["entry"])
    from evennia_links.notices import NoticeContext
    from evennia_lore import notices

    if phase == "after":
        call_command("migrate", interactive=False, verbosity=0)
        assert json.loads(json.dumps(snapshot(state["columns"]), default=str)) == state["sources"]
        assert (
            LoreNotice.objects.filter(
                pk__in=state["legacy"], provenance_known=False, route_state="pending"
            ).count()
            == 4
        )
        with patch.object(notices, "_safe_route", return_value="retry"):
            entry.affirm()
        known = LoreNotice.objects.get(kind="affirmed")
        assert notices.route_notice(known.pk) == "inbox"
        assert notices.route_notice(known.pk) == "inbox"
        # An unchanged decision cannot recreate an alert after reconnect.
        entry.affirm()
        assert LoreNotice.objects.filter(kind="affirmed").count() == 1
        with patch.object(notices, "_safe_route", return_value="retry"):
            entry.decline(note="Known pending decision")
        pending = LoreNotice.objects.get(kind="declined")
        state.update(accepted=known.pk, pending=pending.pk)
        state_path.write_text(json.dumps(state))
        print(
            "Additive Lore upgrade preserved original rows/markers; typed event imports once and legacy provenance held"
        )
    elif phase == "absent":
        assert find_spec("evennia_notices") is None
        assert not apps.is_installed("evennia_notices")
        try:
            metadata.distribution("evennia-notices")
        except metadata.PackageNotFoundError:
            pass
        else:
            raise AssertionError("Inbox distribution remains installed")
        assert notices.route_notice(state["accepted"]) == "inbox"
        session = Mock()
        session.get_account.return_value = account
        session.get_puppet.return_value = character
        context = NoticeContext(account, character, session)
        with patch.object(notices, "connected_contexts", return_value=[context]):
            assert notices.route_notice(state["pending"]) == "fallback"
            assert notices.route_notice(state["pending"]) == "fallback"
            entry.affirm()
        fallback = LoreNotice.objects.order_by("pk").last()
        assert fallback.route_state == "fallback"
        assert session.msg.call_count == 2
        # Keep a genuinely pending new decision for restoration.
        entry.decline(note="Awaiting restoration")
        restored_pending = LoreNotice.objects.order_by("pk").last()
        state.update(fallback=fallback.pk, restored_pending=restored_pending.pk)
        state_path.write_text(json.dumps(state))
        assert notices.transfer_pending(character)["held"] >= 3
        print(
            "Inbox distribution/import/app physically absent; old transfer never replayed, future fallback delivered once"
        )
    else:
        from evennia_notices.models import DeliveryReceipt

        assert notices.route_notice(state["accepted"]) == "inbox"
        assert notices.route_notice(state["pending"]) == "fallback"
        assert notices.route_notice(state["fallback"]) == "fallback"
        assert notices.route_notice(state["restored_pending"]) == "inbox"
        assert notices.route_notice(state["restored_pending"]) == "inbox"
        assert DeliveryReceipt.objects.filter(source="lore").count() == 2
        assert LoreNotice.objects.filter(pk__in=state["legacy"], route_state="pending").count() == 4
        print(
            "Restored Inbox: consumed events did not replay; pending known event imported once; all legacy source history preserved"
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
    with tempfile.TemporaryDirectory(prefix="lore-upgrade-", dir=game.parent) as temporary:
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
