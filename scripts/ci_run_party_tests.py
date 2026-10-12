# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Party package tests and populated cross-process uninstall/reinstall checks.

Supply a disposable initialized game, never a live host. Fixture phases use
its migrated database; the suite uses Django's separate test database.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from ci_run_partner_tests import test_exit_code

OPTIONAL = (
    "evennia_rp_chargen",
    "evennia_npcs",
    "evennia_scenes",
    "evennia_posing",
    "evennia_social",
    "evennia_accessibility",
    "evennia_rp_party",
)


class ROLL:
    """Fixed d100: exchange outcomes move Spirit, which the boost averages."""

    @staticmethod
    def randint(low, high):
        return 50


def fixture(game, phase):
    os.chdir(game)
    sys.path.insert(0, str(game))
    os.environ["DJANGO_SETTINGS_MODULE"] = "server.conf.party_test_settings"
    import django

    django.setup()
    import evennia

    evennia._init()
    from copy import deepcopy
    from unittest.mock import patch

    from evennia.objects.models import ObjectDB
    from evennia.utils.create import create_object
    from evennia_rp_combat import engine, partners, services
    from evennia_rp_combat.data import Build
    from evennia_rp_combat.models import Fight

    path = game / "party-fixture.json"
    if phase == "create":
        from evennia_rp_party import rules
        from evennia_rp_party import services as party

        room = create_object(
            "evennia.objects.objects.DefaultRoom", key="Party fixture room", nohome=True
        )
        first, second, supporter = [
            create_object(
                "evennia.objects.objects.DefaultCharacter", key=key, location=room, home=room
            )
            for key in ("Fixture ally", "Fixture opponent", "Fixture supporter")
        ]
        frozen = Build(
            tuple(
                (key, "0")
                for key in (
                    "attack",
                    "attack_defense",
                    "spell",
                    "spell_defense",
                    "dispirit",
                    "will",
                    "agility",
                )
            )
        )
        with patch("evennia_rp_combat.services.snapshot", return_value=frozen):
            services.setup(first)
            services.join(first, "one")
            services.join(second, "two")
            services.join(supporter, "one")
        key = party.change(first, "create", "Retained team")
        party.change(supporter, "join", key)
        services.declare(supporter, [first], action="assist", rng=ROLL)
        services.control(supporter, "posed")
        services.storyteller(first, "spirit", target=first, value=1000)
        services.control(first, "accept")
        token = f"{services.declare(first, [second], rng=ROLL)}:1"
        state = services.state_for(first)
        fight = services.open_fight(room)
        path.write_text(
            json.dumps(
                {
                    "fight": fight.pk,
                    "first": first.pk,
                    "second": second.pk,
                    "supporter": supporter.pk,
                    "token": token,
                    "party": rules.data(state),
                    "builds": list(fight.builds.values_list("digest", flat=True)),
                }
            ),
            encoding="utf-8",
        )
    else:
        saved = json.loads(path.read_text(encoding="utf-8"))
        first, second = (
            ObjectDB.objects.get(pk=saved["first"]),
            ObjectDB.objects.get(pk=saved["second"]),
        )
        fight = Fight.objects.get(pk=saved["fight"])
        state = services.load(fight)
        assert state["partners"]["party"]["data"] == saved["party"]
        assert list(fight.builds.values_list("digest", flat=True)) == saved["builds"]
        if phase == "absent":
            assert find_spec("evennia_rp_party") is None
            assert "unavailable" in services.render(first)
            candidate = deepcopy(state)
            engine.reaction(candidate, second.pk, saved["token"], "resist")
            services.react(second, saved["token"], "resist")
            resumed = services.state_for(first)
            exchange = resumed["exchanges"][saved["token"].split(":")[0]]
            assert exchange["outcomes"] == candidate["exchanges"][exchange["id"]]["outcomes"]
            assert partners.modifiers(exchange, second.pk).damage_boost == "0"
            services.control(first, "posed")
            supporter = ObjectDB.objects.get(pk=saved["supporter"])
            support_token = f"{services.declare(supporter, [second], rng=ROLL)}:1"
            services.react(second, support_token, "resist")
            saved["absent_token"] = f"{services.declare(first, [second], rng=ROLL)}:1"
            path.write_text(json.dumps(saved), encoding="utf-8")
        else:
            assert "party" in partners.registered()
            old = state["exchanges"][saved["token"].split(":")[0]]
            assert partners.modifiers(old, second.pk).damage_boost == "10"
            absent = engine.get_exchange(state, saved["absent_token"])
            assert partners.modifiers(absent, second.pk).damage_boost == "0"
            services.control(second, "cancel", argument=saved["absent_token"])
            token = f"{services.declare(first, [second], rng=ROLL)}:1"
            current = services.state_for(first)
            # The fixed rolls leave Spirit 12 and 2. The boost is their average
            # alone: the rally expired with Party absent, or it would be 12.
            assert (
                partners.modifiers(engine.get_exchange(current, token), second.pk).damage_boost
                == "7"
            )
            services.control(second, "cancel", argument=token)
            retained = deepcopy(current["partners"]["party"])
            services.shelve(first, "package restore fixture completed")
            fight.refresh_from_db()
            assert fight.state["partners"]["party"] == retained
    print(f"Party populated fixture {phase}: passed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_dir", type=Path)
    parser.add_argument("--absent", action="append", choices=OPTIONAL, default=[])
    parser.add_argument(
        "--phase", choices=("suite", "create", "absent", "restored"), default="suite"
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    game = args.game_dir.resolve()
    if args.worker:
        fixture(game, args.phase)
        return 0
    for module in args.absent:
        if find_spec(module) is not None:
            parser.error(f"{module} is importable; use a fresh environment excluding it")
    conf = game / "server/conf"
    if not (conf / "settings.py").is_file():
        parser.error("Supply an initialized disposable game")
    absent = find_spec("evennia_rp_party") is None
    (conf / "party_test_settings.py").write_text(
        "from server.conf.settings import *\n"
        "PASSWORD_HASHERS = ('django.contrib.auth.hashers.MD5PasswordHasher',)\n"
        "RP_COMBAT_REVEALED = True\nRP_PARTY_REVEALED = True\n"
        "RP_COMBAT_PARTNERS = {'party': {'app': 'evennia_rp_party', 'provider': 'evennia_rp_party.providers.PROVIDER'}}\n"
        + (
            "INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'evennia_rp_party']\n"
            if absent
            else ""
        ),
        encoding="utf-8",
    )
    if args.phase != "suite":
        return subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                str(game),
                "--worker",
                "--phase",
                args.phase,
            ],
            stdin=subprocess.DEVNULL,
        ).returncode
    launcher = shutil.which("evennia")
    if launcher is None:
        parser.error("evennia is not on PATH")
    labels = ["evennia_rp_combat"] + ([] if absent else ["evennia_rp_party"])
    result = subprocess.run(
        [launcher, "test", "--settings=party_test_settings.py", *labels],
        cwd=game,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return test_exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
