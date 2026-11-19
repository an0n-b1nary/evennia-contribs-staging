# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Populated Plots upgrade through active, disabled, absent and restored Inbox."""

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
from importlib import import_module, metadata
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import Mock, patch

from ci_install_contribs import pip_install_command
from ci_run_notices_upgrade import ROOT, install

SESSIONS = "evennia.server.sessionhandler.SESSIONS.get_sessions"


def domain_snapshot(ids):
    from evennia_plots.models import PlotOwner, PlotThread, StoryThread

    return json.loads(
        json.dumps(
            {
                "plots": list(PlotThread.objects.filter(pk__in=ids).order_by("pk").values()),
                "owners": list(PlotOwner.objects.filter(plot_id__in=ids).order_by("pk").values()),
                "threads": list(
                    StoryThread.objects.filter(plot_id__in=ids).order_by("pk").values()
                ),
            },
            default=str,
        )
    )


def prior_history():
    from evennia.utils.create import create_account, create_object

    from evennia_plots import threads
    from evennia_plots.models import PlotThread

    accounts = [
        create_account(f"Plot upgrade account {number}", None, secrets.token_urlsafe(48))
        for number in range(3)
    ]
    characters = [
        create_object(
            "evennia.DefaultCharacter", key=f"Plot upgrade character {number}", nohome=True
        )
        for number in range(3)
    ]
    for account, character in zip(accounts, characters, strict=True):
        account.characters.add(character)
    owner, requester, staff = characters
    staff.permissions.add("Builder")
    public = PlotThread.create_thread(
        "Historical public plot", owner, thread_policy=PlotThread.ThreadPolicy.REQUEST
    )
    public.activate()
    threads.add_thread(public, requester, "Historical pending")
    open_thread = threads.add_thread(public, requester, "Historical accepted")
    threads.accept(open_thread, staff)
    declined = threads.add_thread(public, requester, "Historical declined")
    threads.decline(declined, owner, "Historical reason")
    private = PlotThread.create_thread("Historical private plot", owner, privacy="private")
    private.activate()
    threads.add_owner(private, owner, requester)
    threads.add_thread(private, requester, "Historical owned thread")
    private.archive()
    ownerless = PlotThread.create_thread("Historical ownerless plot", None)
    ids = [public.pk, private.pk, ownerless.pk]
    print("Populated the prior Plots schema with private and public history, decisions and audit")
    return {
        "account": accounts[0].pk,
        "characters": [character.pk for character in characters],
        "plots": ids,
        "history": domain_snapshot(ids),
    }


def _session(account, character, writer_error=False):
    session = Mock(logged_in=True)
    session.get_account.return_value = account
    session.get_puppet.return_value = character
    if writer_error:
        session.msg.side_effect = OSError("Fixture transport failed")
    return session


def _receipt(request):
    from evennia_plots.models import PlotNoticeReceipt

    return PlotNoticeReceipt.objects.get(thread=request)


def upgrade_phase(state, phase):
    from django.apps import apps
    from django.conf import settings
    from evennia.accounts.models import AccountDB
    from evennia.objects.models import ObjectDB
    from evennia.server.signals import SIGNAL_OBJECT_POST_PUPPET

    from evennia_links.notices import NoticeContext, RouteResult
    from evennia_plots import notices, threads
    from evennia_plots.models import PlotNoticeReceipt, PlotThread

    owner, requester, _ = [ObjectDB.objects.get(pk=pk) for pk in state["characters"]]
    account = AccountDB.objects.get(pk=state["account"])
    context = NoticeContext(account, owner)
    State = PlotNoticeReceipt.State

    def make_request(title):
        plot = PlotThread.objects.get(pk=state["active_plot"])
        return threads.add_thread(plot, requester, title)

    if phase == "after":
        from evennia_notices.models import DeliveryReceipt
        from evennia_notices.services import mutate, project, set_preference

        assert state["history"] == domain_snapshot(state["plots"])
        assert not PlotNoticeReceipt.objects.exists()
        session = _session(account, owner)
        with patch(SESSIONS, return_value=[session]):
            SIGNAL_OBJECT_POST_PUPPET.send(sender=owner, account=account, session=session)
        session.msg.assert_not_called()
        assert not DeliveryReceipt.objects.filter(source="plots").exists()
        assert not project(context, source="plots")

        plot = PlotThread.create_thread(
            "New upgrade fixture", owner, thread_policy=PlotThread.ThreadPolicy.REQUEST
        )
        plot.activate()
        state["active_plot"] = plot.pk
        with patch(SESSIONS, return_value=[]):
            retained = make_request("Retained while offline")
            cleared = make_request("Read and cleared")
            [item] = [
                item
                for item in project(context, source="plots")
                if item.text.endswith(f"({cleared.ref}).")
            ]
            mutate(context, item.notice.public_ref, "read")
            mutate(context, item.notice.public_ref, "clear")
            set_preference(context, "plots", "off")
            suppressed = make_request("Suppressed by preference")
            set_preference(context, "plots", "summary")
            with patch.object(notices, "notify", return_value=RouteResult("retry")):
                pending = make_request("Waiting after active path failure")
        state["terminal"] = {
            str(_receipt(retained).pk): State.INBOX,
            str(_receipt(cleared).pk): State.INBOX,
            str(_receipt(suppressed).pk): State.SUPPRESSED,
        }
        state["quiet_pending"] = [_receipt(pending).pk]
        assert _receipt(pending).state == State.PENDING
        print("Migrated real historical data with zero reconstructed alerts; staged new activity")
    elif phase in ("disabled", "absent"):
        if phase == "disabled":
            assert apps.is_installed("evennia_notices") and not settings.NOTICES_ENABLED
        else:
            assert find_spec("evennia_notices") is None and not apps.is_installed("evennia_notices")
            try:
                metadata.distribution("evennia-notices")
            except metadata.PackageNotFoundError:
                pass
            else:
                raise AssertionError("Inbox distribution remains installed")
            try:
                import_module("evennia_notices")
            except ModuleNotFoundError:
                pass
            else:
                raise AssertionError("Inbox package remains importable")
        with patch(SESSIONS, return_value=[]):
            offline = make_request("Offline standalone fixture")
        delivered_session = _session(account, owner)
        with patch(SESSIONS, return_value=[delivered_session]):
            delivered = make_request("Connected standalone fixture")
        delivered_session.msg.assert_called_once()
        uncertain_session = _session(account, owner, writer_error=True)
        with patch(SESSIONS, return_value=[uncertain_session]):
            uncertain = make_request("Ambiguous standalone fixture")
        uncertain_session.msg.assert_called_once()
        no_send = _session(account, owner)
        no_send.msg = None
        with patch(SESSIONS, return_value=[no_send]):
            remaining = make_request("Observed exact puppet without writable connection")
        assert _receipt(remaining).state == State.PENDING
        for request, disposition in (
            (offline, State.STANDALONE_OFFLINE),
            (delivered, State.FALLBACK_DELIVERED),
            (uncertain, State.UNCERTAIN),
        ):
            row = _receipt(request)
            assert row.state == disposition
            state["terminal"][str(row.pk)] = disposition
        state["quiet_pending"].append(_receipt(remaining).pk)
        print(
            f"Inbox {phase}: checked terminal offline, delivered and uncertain plus pending no-send"
        )
    else:
        from evennia_notices.models import DeliveryReceipt
        from evennia_notices.services import project, set_preference

        set_preference(context, "plots", "immediate")
        session = _session(account, owner)
        with patch(SESSIONS, return_value=[session]):
            notices.prepare(NoticeContext(account, owner, session))
            notices.prepare(NoticeContext(account, owner, session))
        session.msg.assert_not_called()
        for pk, disposition in state["terminal"].items():
            assert PlotNoticeReceipt.objects.get(pk=pk).state == disposition
        for pk in state["quiet_pending"]:
            row = PlotNoticeReceipt.objects.get(pk=pk)
            assert row.state == State.INBOX
            assert (
                DeliveryReceipt.objects.get(source="plots", event_id=row.event_key).transfer_id
                == row.event_key
            )
        assert DeliveryReceipt.objects.filter(source="plots").count() == 3 + len(
            state["quiet_pending"]
        )
        assert len(project(context, source="plots")) == 1 + len(state["quiet_pending"])
        with patch(SESSIONS, return_value=[session]):
            live = make_request("New post-restoration live event")
        session.msg.assert_called_once()
        assert _receipt(live).state == State.INBOX
        assert (
            DeliveryReceipt.objects.get(
                source="plots", event_id=_receipt(live).event_key
            ).transfer_id
            is None
        )
        print(
            "Restored Inbox and transferred only eligible pending work exactly once, without hints"
        )


def worker(game, phase):
    os.chdir(game)
    sys.path.insert(0, str(game))
    os.environ["DJANGO_SETTINGS_MODULE"] = "server.conf.settings"
    import django

    django.setup()
    import evennia

    evennia._init()
    from django.core.management import call_command

    if phase in ("before", "after"):
        call_command("migrate", interactive=False, verbosity=0)
    state_path = game / "plots-upgrade-state.json"
    if phase == "before":
        state = prior_history()
    else:
        state = json.loads(state_path.read_text())
        upgrade_phase(state, phase)
    state_path.write_text(json.dumps(state))


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
    with tempfile.TemporaryDirectory(prefix="plots-notices-upgrade-", dir=game.parent) as temporary:
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
