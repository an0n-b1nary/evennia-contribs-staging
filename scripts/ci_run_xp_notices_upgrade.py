# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Verify a populated XP 0.6.0 upgrade with a real Inbox removal and restoration."""

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

SESSIONS = "evennia.server.sessionhandler.SESSIONS.get_sessions"
ATTRIBUTE = "last_xp_summary_week"


def accounting():
    from evennia_xp.models import CharacterXP, XPLog, XPSpend

    return {
        model.__name__: json.loads(
            json.dumps(list(model.objects.order_by("pk").values()), default=str)
        )
        for model in (CharacterXP, XPLog, XPSpend)
    }


def payout(character, week, amount="1.25"):
    from evennia_xp.awards import record_xp
    from evennia_xp.models import XPLog

    return record_xp(
        character.pk,
        amount,
        XPLog.SourceType.MANUAL_GRANT,
        0,
        week=week,
        character_name=character.key,
        reason="Private synthetic audit note",
    )


def seed():
    from django.db import connection
    from evennia.utils.create import create_account, create_object

    from evennia_xp.spending import spend_xp

    assert metadata.version("evennia-xp") == "0.6.0"
    assert "evennia_xp_xpnoticereceipt" not in connection.introspection.table_names()
    owner = create_account("XP Upgrade Owner", None, secrets.token_urlsafe(48))
    characters = [
        create_object("evennia.DefaultCharacter", key=f"XP Upgrade Character {index}", nohome=True)
        for index in range(4)
    ]
    character, alt, empty, npc = characters
    for puppet in (character, alt, empty):
        owner.characters.add(puppet)
    for week in ("2025-W50", "2026-W02", "2025-W52"):
        payout(character, week)
    character.attributes.add(ATTRIBUTE, "2026-W02")
    payout(alt, "2026-W03")
    alt.attributes.add(ATTRIBUTE, "2026-01-19")
    payout(npc, "2026-W03")
    assert spend_xp(character.pk, "0.75", ref_key="upgrade-fixture")
    return {
        "owner": owner.pk,
        "ids": [puppet.pk for puppet in characters],
        "accounting": accounting(),
    }


def connected(account, character):
    character.account = account
    session = Mock(logged_in=True)
    session.get_account.return_value = account
    session.get_puppet.return_value = character
    return session


def verify(state, phase):
    from django.apps import apps
    from evennia.accounts.models import AccountDB
    from evennia.objects.models import ObjectDB

    from evennia_links.notices import NoticeContext
    from evennia_xp.models import XPNoticeReceipt
    from evennia_xp.summary import notify_xp_summary

    assert metadata.version("evennia-xp") == "0.6.1"
    account = AccountDB.objects.get(pk=state["owner"])
    character, alt, empty, npc = [ObjectDB.objects.get(pk=pk) for pk in state["ids"]]
    session = connected(account, character)
    context = NoticeContext(account, character, session)
    rows = XPNoticeReceipt.objects.filter(summary__character_id=character.pk)
    S = XPNoticeReceipt.State
    if phase == "absent":
        assert find_spec("evennia_notices") is None
        assert not apps.is_installed("evennia_notices")
        try:
            metadata.distribution("evennia-notices")
        except metadata.PackageNotFoundError:
            pass
        else:
            raise AssertionError("Inbox distribution remains installed")
        with patch(SESSIONS, return_value=[session]), patch.object(character, "msg") as message:
            assert not notify_xp_summary(character)
            message.assert_not_called()
            payout(character, "2026-W08")
            assert notify_xp_summary(character)
            assert not notify_xp_summary(character)
            message.assert_called_once()
        assert rows.get(week="2026-W08").state == S.DELIVERED
        return

    from evennia_notices.models import DeliveryReceipt
    from evennia_notices.services import mutate, project, set_preference

    deliveries = DeliveryReceipt.objects.filter(source="xp", recipient__character_id=character.pk)
    if phase == "after":
        assert accounting() == state["accounting"]
        assert not XPNoticeReceipt.objects.exists()
        assert character.attributes.get(ATTRIBUTE) == "2026-W02"
        assert alt.attributes.get(ATTRIBUTE) == "2026-01-19"
        assert not project(context, source="xp")
        payout(character, "2026-W04")
        assert rows.get(week="2025-W52").state == S.PENDING
        assert deliveries.count() == 1
        with patch(SESSIONS, return_value=[session]):
            notify_xp_summary(character)
            notify_xp_summary(character)
        assert deliveries.count() == 2
        assert set(rows.values_list("week", flat=True)) == {"2026-W04", "2025-W52"}
        assert not XPNoticeReceipt.objects.filter(
            summary__character_id__in=[alt.pk, empty.pk, npc.pk]
        ).exists()
        for item in project(context, source="xp"):
            if "2025-W52" in item.text:
                mutate(context, item.notice.public_ref, "clear")
        set_preference(context, "xp", "off")
        payout(character, "2026-W05")
        set_preference(context, "xp", "summary")
        assert rows.get(week="2026-W05").state == S.SUPPRESSED
        with patch("evennia_notices.services.route", side_effect=RuntimeError("unavailable")):
            payout(character, "2026-W06")
            payout(character, "2026-W07")
        assert rows.filter(week__in=["2026-W06", "2026-W07"], state=S.PENDING).count() == 2
    elif phase == "disabled":
        with (
            patch(SESSIONS, return_value=[session]),
            patch.object(
                character, "msg", side_effect=RuntimeError("transport started")
            ) as message,
        ):
            assert not notify_xp_summary(character)
            assert not notify_xp_summary(character)
            message.assert_called_once()
        assert rows.get(week="2026-W07").state == S.UNCERTAIN
        assert rows.get(week="2026-W06").state == S.PENDING
    elif phase == "restored":
        assert deliveries.count() == 3
        with patch(SESSIONS, return_value=[session]), patch.object(character, "msg") as message:
            assert not notify_xp_summary(character)
            assert not notify_xp_summary(character)
            message.assert_not_called()
        assert deliveries.count() == 4
        assert rows.get(week="2026-W06").state == S.TRANSFERRED
        weeks = {
            event.subject["key"] for item in project(context, source="xp") for event in item.events
        }
        assert weeks == {"2026-W04", "2026-W06"}
        old_data = state["accounting"]
        new_data = accounting()
        for key in ("XPLog", "XPSpend"):
            assert new_data[key][: len(old_data[key])] == old_data[key]


def worker(game, phase):
    os.chdir(game)
    sys.path.insert(0, str(game))
    os.environ["DJANGO_SETTINGS_MODULE"] = "server.conf.settings"
    import django

    django.setup()
    import evennia

    evennia._init()
    from django.core.management import call_command

    if phase in {"before", "after"}:
        call_command("migrate", interactive=False, verbosity=0)
    state_path = game / "xp-upgrade-state.json"
    if phase == "before":
        state_path.write_text(json.dumps(seed()))
    else:
        verify(json.loads(state_path.read_text()), phase)
    print(f"XP populated upgrade phase passed: {phase}", flush=True)


def main(argv=None):
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
    with tempfile.TemporaryDirectory(prefix="xp-notices-upgrade-", dir=game.parent) as temporary:
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
