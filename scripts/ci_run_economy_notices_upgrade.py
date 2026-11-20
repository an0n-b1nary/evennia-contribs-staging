# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Verify a populated Economy 0.4.2 upgrade, disable, removal and restoration."""

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
from types import SimpleNamespace
from unittest.mock import patch

from ci_install_contribs import pip_install_command
from ci_run_notices_upgrade import ROOT, install

MARKER = "last_economy_summary"
FULL = "economy_full_notified"
INCOME = "Weekly income: 100 coins. See +balance."


def accounting():
    """Capture purses, the journal and payments before any notice migration or routing."""
    from evennia_economy.models import LedgerEntry, Purse, StipendPayment, UBIPayment

    return {
        model.__name__: json.loads(
            json.dumps(list(model.objects.order_by("pk").values()), default=str)
        )
        for model in (Purse, LedgerEntry, UBIPayment, StipendPayment)
    }


def plain(value):
    """Turn Evennia's saved containers into JSON-comparable values."""
    if isinstance(value, (str, bytes, int, float, bool)) or value is None:
        return value
    return [plain(item) for item in value]


def markers(characters):
    return {
        str(character.pk): [
            plain(character.attributes.get(MARKER)),
            plain(character.attributes.get(FULL)),
        ]
        for character in characters
    }


def pay(character, period):
    """Run the actual Economy batch for one synthetic character."""
    from evennia_economy.batch import run_weekly_batch

    assert not run_weekly_batch(period, characters=[character])["errors"]


def seed():
    """Create seen, malformed and capped histories plus unseen payments on 0.4.2."""
    from django.db import connection
    from evennia.utils.create import create_account, create_object

    from evennia_economy.models import StipendPayment
    from evennia_economy.services import credit
    from evennia_economy.summary import notify_economy_summary
    from evennia_links import runtime

    assert metadata.version("evennia-economy") == "0.4.2"
    assert "evennia_economy_economynoticereceipt" not in connection.introspection.table_names()
    owner = create_account("Economy Upgrade Owner", None, secrets.token_urlsafe(48))
    seen, malformed, capped = (
        create_object("evennia.DefaultCharacter", key=f"Economy Upgrade {key}", nohome=True)
        for key in ("A", "B", "C")
    )
    for character in (seen, malformed, capped):
        owner.characters.add(character)
    pay(seen, "old-seen")
    with patch.object(seen, "msg"):
        assert notify_economy_summary(seen)
    credit(capped, 10000)
    pay(capped, "cap-seen")
    with patch.object(capped, "msg") as message:
        assert notify_economy_summary(capped)
    assert "at its income cap" in message.call_args.args[0]
    assert capped.attributes.get(FULL) is True
    pay(malformed, "b-week")
    malformed.attributes.add(MARKER, ["2026-10-26", 1])
    runtime.set("RP_ECONOMY_REVEALED", False)
    runtime.set("RP_ECONOMY_REVEALED", True)
    ids = [seen.pk, malformed.pk, capped.pk]
    assert set(
        StipendPayment.objects.filter(kind="reveal", character_id__in=ids).values_list(
            "character_id", flat=True
        )
    ) == set(ids)
    pay(seen, "old-historical")
    pay(seen, "old-current")
    pay(capped, "cap-unseen")
    return {
        "owner": owner.pk,
        "characters": ids,
        "accounting": accounting(),
        "markers": markers((seen, malformed, capped)),
    }


def verify(state, phase, registered):
    """Check persisted deduplication while replacing optional packages on the same DB."""
    from django.apps import apps
    from evennia.accounts.models import AccountDB
    from evennia.objects.models import ObjectDB

    from evennia_economy import notices
    from evennia_economy.models import EconomyNoticeReceipt, StipendPayment, UBIPayment
    from evennia_economy.summary import notify_economy_summary
    from evennia_links.notices import NoticeContext

    assert metadata.version("evennia-economy") == "0.5.0"
    account = AccountDB.objects.get(pk=state["owner"])
    seen, malformed, capped = (ObjectDB.objects.get(pk=pk) for pk in state["characters"])
    sessions = {}
    for character in (seen, malformed, capped):
        character.account = account
        sessions[character.pk] = SimpleNamespace(
            logged_in=True,
            get_account=lambda: account,
            get_puppet=lambda character=character: character,
        )
    registered.side_effect = lambda: list(sessions.values())
    rows = EconomyNoticeReceipt.objects.filter(character=seen)
    state_cls = EconomyNoticeReceipt.State

    def prepare(character):
        context = NoticeContext(account, character, sessions[character.pk])
        notices.prepare_character(character, context=context)

    if phase == "absent":
        assert find_spec("evennia_notices") is None and not apps.is_installed("evennia_notices")
        try:
            metadata.distribution("evennia-notices")
        except metadata.PackageNotFoundError:
            pass
        else:
            raise AssertionError("Inbox distribution remains installed")
        for character in (seen, malformed, capped):
            with patch.object(character, "msg") as message:
                assert not notify_economy_summary(character)
                message.assert_not_called()
        with patch.object(seen, "msg") as message:
            pay(seen, "absent")
            assert notify_economy_summary(seen)
            assert not notify_economy_summary(seen)
            message.assert_called_once()
        assert message.call_args.args[0] == (
            "Your latest income: 100 coins. Stipends received: 150 coins. See +balance."
        )
        assert rows.get(ubi__week="absent").state == state_cls.DELIVERED
        return

    from evennia_notices.models import DeliveryReceipt
    from evennia_notices.services import mutate, project, set_preference

    def items(character):
        return sorted(
            item.text for item in project(NoticeContext(account, character), source=notices.SOURCE)
        )

    def deliveries(character):
        return DeliveryReceipt.objects.filter(
            source="economy", recipient__character_id=character.pk
        )

    if phase == "after":
        assert accounting() == state["accounting"]
        assert not EconomyNoticeReceipt.objects.exists()
        assert markers((seen, malformed, capped)) == state["markers"]
        for character in (seen, malformed, capped):
            prepare(character)
        assert items(seen) == sorted([INCOME, "Stipend received: 50 coins. See +balance."])
        assert not rows.filter(ubi__week__in=("old-historical", "old-seen")).exists()
        assert not rows.filter(stipend__kind="starting").exists()
        assert items(malformed) == sorted(
            [
                INCOME,
                "Stipend received: 100 coins. See +balance.",
                "Stipend received: 50 coins. See +balance.",
            ]
        )
        assert items(capped) == ["Stipend received: 50 coins. See +balance."]
        assert (
            EconomyNoticeReceipt.objects.get(ubi__week="cap-unseen").state == state_cls.SUPPRESSED
        )
        assert capped.attributes.get(notices.FULL_KEY) is True
        assert [deliveries(c).count() for c in (seen, malformed, capped)] == [2, 3, 1]
        stipends = sorted(
            StipendPayment.objects.filter(character=seen).values_list("pk", flat=True)
        )
        current = UBIPayment.objects.get(character=seen, week="old-current")
        assert plain(seen.attributes.get(MARKER)) == [current.pk, stipends]
        for item in project(NoticeContext(account, seen), source=notices.SOURCE):
            mutate(NoticeContext(account, seen), item.notice.public_ref, "clear")
        set_preference(NoticeContext(account, seen), "economy", "off")
        pay(seen, "suppressed")
        set_preference(NoticeContext(account, seen), "economy", "summary")
        assert rows.get(ubi__week="suppressed").state == state_cls.SUPPRESSED
        with patch("evennia_notices.services.route", side_effect=RuntimeError("unavailable")):
            pay(seen, "retry")
        assert rows.get(ubi__week="retry").state == state_cls.PENDING
    elif phase == "disabled":
        pay(seen, "disabled")
        with patch.object(seen, "msg", side_effect=RuntimeError("send started")) as message:
            assert not notify_economy_summary(seen)
            assert not notify_economy_summary(seen)
            message.assert_called_once()
        assert rows.get(ubi__week="disabled").state == state_cls.UNCERTAIN
        assert rows.get(ubi__week="retry").state == state_cls.PENDING
    elif phase == "restored":
        assert deliveries(seen).count() == 3
        for character in (seen, malformed, capped):
            prepare(character)
        assert rows.get(ubi__week="retry").state == state_cls.TRANSFERRED
        assert set(
            rows.filter(state=state_cls.TRANSFERRED, ubi__isnull=False).values_list(
                "ubi__week", flat=True
            )
        ) == {"old-current", "retry"}
        assert items(seen) == [INCOME]
        assert [deliveries(c).count() for c in (seen, malformed, capped)] == [4, 3, 1]
        previous, after = state["accounting"], accounting()
        for name in ("Purse", "LedgerEntry", "UBIPayment", "StipendPayment"):
            if name != "Purse":
                assert after[name][: len(previous[name])] == previous[name]


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
    state_path = game / "economy-upgrade-state.json"
    if phase == "before":
        state_path.write_text(json.dumps(seed()))
    else:
        from evennia_economy import notices

        with patch.object(notices, "_registered_sessions") as registered:
            verify(json.loads(state_path.read_text()), phase, registered)
    print(f"Economy populated upgrade phase passed: {phase}", flush=True)


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
    with tempfile.TemporaryDirectory(
        prefix="economy-notices-upgrade-", dir=game.parent
    ) as temporary:
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
        # A 10000-coin cap keeps the first character's income untapered.
        suffix = (
            "\nPASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']\n"
            "RP_ECONOMY_REVEALED = True\n"
            "RP_ECONOMY_BASE_CAP_WEEKS = 100\n"
            "RP_ECONOMY_STARTING_STIPEND = 100\n"
            "RP_ECONOMY_REVEAL_STIPEND = 50\n"
        )
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
