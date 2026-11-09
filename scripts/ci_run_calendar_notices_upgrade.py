# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Populated Calendar upgrade, physical Inbox removal, and restoration.

Run only in a disposable ci_profile environment: this switches editable package
metadata and never reads a deployed database or copies secret settings.
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
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ci_install_contribs import pip_install_command
from ci_run_notices_upgrade import ROOT, install, snapshot, source_columns


def worker(game, phase):
    """Every phase uses a fresh process/app registry over one disposable database."""
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

    from evennia_calendar.models import RSVP, CalendarEvent, CalendarNotice

    state_path = game / "calendar-upgrade-state.json"
    if phase == "before":
        call_command("migrate", interactive=False, verbosity=0)
        account = create_account("Calendar upgrade fixture", None, secrets.token_urlsafe(48))
        character = create_object(
            "evennia.objects.objects.DefaultCharacter",
            key="Calendar fixture character",
            nohome=True,
        )
        account.characters.add(character)
        event = CalendarEvent.objects.create(
            title="Populated selection", scheduled_time=timezone.now() + timedelta(days=4)
        )
        selected = RSVP.objects.create(
            event=event, character=character, status=RSVP.Status.LOTTERY_SELECTED
        )
        pending = [
            CalendarNotice.objects.create(
                rsvp=selected,
                character=character,
                kind="drawn",
                status=selected.status,
                message="Legacy selected",
            ).pk
            for _ in range(2)
        ]
        ambiguous = CalendarNotice.objects.create(
            rsvp=selected,
            character=character,
            kind="drawn",
            status=selected.status,
            message="Older same status",
            created_at=selected.updated_at - timedelta(seconds=1),
        )
        invite_event = CalendarEvent.objects.create(
            title="Unknown legacy invitation", scheduled_time=timezone.now() + timedelta(days=4)
        )
        invitation = RSVP.objects.create(
            event=invite_event, character=character, status=RSVP.Status.INVITED
        )
        held = CalendarNotice.objects.create(
            rsvp=invitation,
            character=character,
            kind="invited",
            status=invitation.status,
            message="Unrecoverable historical sender",
        )
        reminder_event = CalendarEvent.objects.create(
            title="Delivered reminder", scheduled_time=timezone.now() + timedelta(days=1)
        )
        confirmed = RSVP.objects.create(
            event=reminder_event, character=character, status=RSVP.Status.CONFIRMED
        )
        receipt = CalendarNotice.objects.create(
            rsvp=confirmed,
            character=character,
            kind="reminder",
            status=confirmed.status,
            message="Already delivered",
            delivered_at=timezone.now(),
        )
        character.db.last_xp_summary_week = "2026-11-02"
        state_path.write_text(
            json.dumps(
                {
                    "account": account.pk,
                    "character": character.pk,
                    "pending": pending,
                    "ambiguous": ambiguous.pk,
                    "held": held.pk,
                    "receipt": receipt.pk,
                    "selected": selected.pk,
                    "confirmed": confirmed.pk,
                    "sources": snapshot(),
                    "columns": source_columns(),
                },
                default=str,
            )
        )
        print(
            "Created populated Calendar0004 fixture: 2 duplicate pending selections, 2 provenance holds, delivered reminder"
        )
        return
    state = json.loads(state_path.read_text())
    account, character = (
        AccountDB.objects.get(pk=state["account"]),
        ObjectDB.objects.get(pk=state["character"]),
    )
    from evennia_calendar import notices

    if phase == "after":
        call_command("migrate", interactive=False, verbosity=0)
        assert (
            json.loads(json.dumps(snapshot(state["columns"]), default=str)) == state["sources"]
        ), "Original source columns changed during additive migration"
        assert character.db.last_xp_summary_week == "2026-11-02"
        first = notices.transfer_pending()
        assert first["transferred"] == 2 and first["held"] == 2, first
        from evennia_links.notices import NoticeContext
        from evennia_notices.models import DeliveryReceipt, NoticeEvent
        from evennia_notices.services import mutate, project

        assert DeliveryReceipt.objects.filter(source="calendar").count() == 1
        context = NoticeContext(account, character)
        item = project(context)[0]
        assert item.outstanding
        mutate(context, item.notice.public_ref, "read")
        assert len(project(context, "pending")) == 1
        for pk in state["pending"]:
            assert CalendarNotice.objects.get(pk=pk).route_state == "inbox"
        # Source receipts remain authoritative after inbox content pruning.
        NoticeEvent.objects.filter(notice__source="calendar").delete()
        assert notices.transfer_pending()["transferred"] == 0
        notices.notify(
            RSVP.objects.get(pk=state["confirmed"]),
            "reminder",
            "Repeated reminder",
            origin="reminder",
        )
        assert (
            CalendarNotice.objects.filter(rsvp_id=state["confirmed"], kind="reminder").count() == 1
        )
        print(
            "Populated Calendar upgrade preserved source IDs/history/reminder receipt; imported one canonical event and held2 uncertain rows"
        )
    elif phase == "absent":
        assert find_spec("evennia_notices") is None
        try:
            metadata.distribution("evennia-notices")
        except metadata.PackageNotFoundError:
            pass
        else:
            raise AssertionError("Inbox distribution remains installed")
        from django.apps import apps

        assert not apps.is_installed("evennia_notices")
        for pk in state["pending"]:
            assert notices.route_notice(pk) == "duplicate"
        assert notices.route_notice(state["held"]) == "held"
        event = CalendarEvent.objects.create(
            title="Standalone post-upgrade", scheduled_time=timezone.now() + timedelta(days=4)
        )
        rsvp = RSVP.objects.create(
            event=event, character=character, status=RSVP.Status.LOTTERY_SELECTED
        )
        session = SimpleNamespace(get_account=lambda: account, get_puppet=lambda: character)
        with (
            patch.object(notices, "_connected_sessions", return_value=[session]),
            patch.object(type(character), "msg") as message,
        ):
            assert notices.notify(rsvp, "drawn", notices.drawn_message(event), origin="lottery")
            assert not notices.notify(rsvp, "drawn", notices.drawn_message(event), origin="lottery")
            assert message.call_count == 1
        state["fallback"] = CalendarNotice.objects.get(rsvp=rsvp).pk
        state_path.write_text(json.dumps(state))
        print(
            "Inbox distribution/import/app physically absent; old transfers did not replay, new fallback delivered once"
        )
    else:
        from evennia_notices.models import DeliveryReceipt

        for pk in [*state["pending"], state["fallback"]]:
            assert notices.route_notice(pk) == "duplicate"
        assert notices.transfer_pending()["transferred"] == 0
        assert DeliveryReceipt.objects.filter(source="calendar").count() == 1
        assert CalendarNotice.objects.get(pk=state["receipt"]).message == "Already delivered"
        assert CalendarNotice.objects.get(pk=state["held"]).delivered_at is None
        assert CalendarNotice.objects.get(pk=state["ambiguous"]).delivered_at is None
        print(
            "Restored inbox: no replay after physical removal/fallback, all source history and held rows preserved"
        )


def main(argv=None):
    """Use an archived local base tree and restore current metadata on every exit."""
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
    with tempfile.TemporaryDirectory(prefix="calendar-upgrade-", dir=game.parent) as temporary:
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
