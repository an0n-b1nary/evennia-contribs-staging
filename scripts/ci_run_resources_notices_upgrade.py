# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Verify a populated Resources 0.3.0 upgrade, disable, removal and restoration."""

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

WEEK = "last_resource_summary_week"


def accounting():
    """Capture award rows and holdings before any notice migration or routing."""
    from evennia_rp_resources.models import (
        PlotPayoutReceipt,
        PlotPayoutRun,
        ResourceGrant,
        ResourceHolding,
    )

    return {
        model.__name__: json.loads(
            json.dumps(list(model.objects.order_by("pk").values()), default=str)
        )
        for model in (ResourceHolding, ResourceGrant, PlotPayoutRun, PlotPayoutReceipt)
    }


def payout(character, period):
    """Run actual Resources accrual for the known synthetic fixture."""
    from evennia_rp_resources.batch import run_weekly_batch

    assert not run_weekly_batch(period, characters=[character])["errors"]


def seed():
    """Create historical weeks plus paid, seen, and unpaid plot records on 0.3.0."""
    from django.db import connection
    from django.utils import timezone
    from evennia.utils.create import create_account, create_object

    from evennia_plots.models import PlotThread
    from evennia_rp_resources import payouts
    from evennia_rp_resources.models import PlotPayoutReceipt, PlotPayoutRun, ResourceDefinition

    assert metadata.version("evennia-rp-resources") == "0.3.0"
    assert (
        "evennia_rp_resources_resourcenoticereceipt" not in connection.introspection.table_names()
    )
    owner = create_account("Resource Upgrade Owner", None, secrets.token_urlsafe(48))
    character = create_object("evennia.DefaultCharacter", key="Resource Upgrade", nohome=True)
    owner.characters.add(character)
    ResourceDefinition.objects.create(key="grain", name="Grain", category="provisions")
    for period in ("old-sent", "old-historical", "old-current"):
        payout(character, period)
    character.attributes.add(WEEK, "old-sent")
    character.attributes.add("resource_full_notified", False)
    for label in ("seen", "pending", "unpaid"):
        plot = PlotThread.create_thread(f"Upgrade plot {label}", character)
        run = PlotPayoutRun.objects.create(
            thread_id=plot.pk,
            plot_name=plot.name,
            amounts={"grain": 1},
            approvals={"grain": character.pk},
        )
        award = PlotPayoutReceipt.objects.create(
            run=run, character_id=character.pk, character_name=character.key
        )
        if label != "unpaid":
            assert payouts.deliver(run.pk)["paid"] == [character.pk]
        if label == "seen":
            PlotPayoutReceipt.objects.filter(pk=award.pk).update(notified_at=timezone.now())
    return {"owner": owner.pk, "character": character.pk, "accounting": accounting()}


def verify(state, phase, registered):
    """Check persisted deduplication while replacing optional packages on the same DB."""
    from django.apps import apps
    from evennia.accounts.models import AccountDB
    from evennia.objects.models import ObjectDB

    from evennia_links.notices import NoticeContext
    from evennia_rp_resources import notices
    from evennia_rp_resources.models import PlotPayoutReceipt, ResourceNoticeReceipt
    from evennia_rp_resources.summary import notify_plot_summary, notify_resource_summary

    assert metadata.version("evennia-rp-resources") == "0.3.1"
    account = AccountDB.objects.get(pk=state["owner"])
    character = ObjectDB.objects.get(pk=state["character"])
    character.account = account
    session = SimpleNamespace(
        logged_in=True, get_account=lambda: account, get_puppet=lambda: character
    )
    registered.return_value = [session]
    context = NoticeContext(account, character)
    rows = ResourceNoticeReceipt.objects.filter(character=character)
    state_cls = ResourceNoticeReceipt.State
    if phase == "absent":
        assert find_spec("evennia_notices") is None and not apps.is_installed("evennia_notices")
        try:
            metadata.distribution("evennia-notices")
        except metadata.PackageNotFoundError:
            pass
        else:
            raise AssertionError("Inbox distribution remains installed")
        with patch.object(character, "msg") as message:
            assert not notify_plot_summary(character)
            assert not notify_resource_summary(character)
            payout(character, "absent")
            assert notify_resource_summary(character)
            assert not notify_resource_summary(character)
            message.assert_called_once()
        assert rows.get(weekly__week="absent").state == state_cls.DELIVERED
        return

    from evennia_notices.models import DeliveryReceipt
    from evennia_notices.services import mutate, project, set_preference

    deliveries = DeliveryReceipt.objects.filter(
        source="resources", recipient__character_id=character.pk
    )
    if phase == "after":
        assert accounting() == state["accounting"]
        assert not rows.exists()
        assert character.attributes.get(WEEK) == "old-sent"
        notices.prepare_character(character, context=NoticeContext(account, character, session))
        current = project(context, source="resources")
        assert len(current) == 2 and deliveries.count() == 2
        assert set(rows.values_list("weekly__week", flat=True)) == {None, "old-current"}
        assert rows.filter(plot__isnull=False, plot__notified_at__isnull=True).count() == 1
        for item in current:
            mutate(context, item.notice.public_ref, "clear")
        set_preference(context, "resources", "off")
        payout(character, "suppressed")
        set_preference(context, "resources", "summary")
        assert rows.get(weekly__week="suppressed").state == state_cls.SUPPRESSED
        with patch("evennia_notices.services.route", side_effect=RuntimeError("unavailable")):
            payout(character, "retry")
        assert rows.get(weekly__week="retry").state == state_cls.PENDING
    elif phase == "disabled":
        payout(character, "disabled")
        with patch.object(character, "msg", side_effect=RuntimeError("send started")) as message:
            assert not notify_resource_summary(character)
            assert not notify_resource_summary(character)
            message.assert_called_once()
        assert rows.get(weekly__week="disabled").state == state_cls.UNCERTAIN
        assert rows.get(weekly__week="retry").state == state_cls.PENDING
    elif phase == "restored":
        assert deliveries.count() == 3
        notices.prepare_character(character, context=NoticeContext(account, character, session))
        assert rows.get(weekly__week="retry").state == state_cls.TRANSFERRED
        assert {
            row.weekly.week for row in rows if row.state == state_cls.TRANSFERRED and row.weekly_id
        } == {"old-current", "retry"}
        assert len(project(context, source="resources")) == 1
        assert PlotPayoutReceipt.objects.filter(paid_at=None).count() == 1
        previous, after = state["accounting"], accounting()
        for name in ("ResourceGrant", "PlotPayoutRun", "PlotPayoutReceipt"):
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
    state_path = game / "resources-upgrade-state.json"
    if phase == "before":
        state_path.write_text(json.dumps(seed()))
    else:
        from evennia_rp_resources import notices

        with patch.object(notices, "_registered_sessions") as registered:
            verify(json.loads(state_path.read_text()), phase, registered)
    print(f"Resources populated upgrade phase passed: {phase}", flush=True)


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
        prefix="resources-notices-upgrade-", dir=game.parent
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
        suffix = (
            "\nPASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']\n"
            "RP_RESOURCES_BASE_CAP = 1000\n"
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
