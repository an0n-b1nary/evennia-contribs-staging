"""Initial setup runs inside the server, after Evennia creates Limbo."""

import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management import call_command

from .runtime import guard, install

SEEDED_THIS_PROCESS = False


def at_initial_setup():
    global SEEDED_THIS_PROCESS
    SEEDED_THIS_PROCESS = True
    guard()
    from evennia import create_account, create_object
    from evennia_rp_chargen import abilities, services
    from server.conf.at_initial_setup import at_initial_setup as original

    original()
    call_command("seed_sandbox", verbosity=0)
    credentials = json.loads(Path(settings.PLAYTEST_CREDENTIALS_FILE).read_text(encoding="utf-8"))
    rooms = {}
    for name in ("telnet", "browser"):
        room = create_object(settings.BASE_ROOM_TYPECLASS, key=f"Playtest {name} laboratory")
        room.room_type = "ic"
        room.db.desc = "[Placeholder] An isolated room for live command verification."
        room.tags.add("market", category="rp_economy")
        room.db.rp_economy_stall_slots = 8
        rooms[name] = room
    gallery = create_object(settings.BASE_ROOM_TYPECLASS, key="Playtest ambient gallery")
    gallery.room_type = "ic"
    for key, source, destination in (
        ("gallery", rooms["telnet"], gallery),
        ("laboratory", gallery, rooms["telnet"]),
    ):
        create_object(
            settings.BASE_EXIT_TYPECLASS, key=key, location=source, destination=destination
        )
    identities = {}
    for role, spec in credentials.items():
        account = create_account(
            spec["name"],
            email=f"{role}@example.invalid",
            password=spec["password"],
            typeclass=settings.BASE_ACCOUNT_TYPECLASS,
            permissions=["Builder" if role == "staff" else "Player"],
        )
        account.tags.add(settings.PLAYTEST_RUN_ID, category="playtest")
        account.db.playtest_role = role
        account.cmdset.add("playtest_support.commands.ProbeCmdSet", persistent=True)
        room = rooms["browser" if role.startswith("browser") else "telnet"]
        character, errors = account.create_character(key=spec["name"], location=room, home=room)
        if errors or character is None:
            raise RuntimeError(f"Fixture character creation failed: {errors}")
        character.permissions.clear()
        character.permissions.add("Builder" if role == "staff" else "Player")
        account.db._last_puppet = character
        if role.startswith("browser"):
            from evennia_rp_rules.ruleset import get_ruleset

            for stat in get_ruleset().stats:
                services.set_stat(character, stat, "B")
            services.finalize(character)
            if role == "browser":
                services.set_edge(character, "presence", 2)
                abilities.grant(character, "proficiency", "performance")
        identities[role] = {"account": account.pk, "character": character.pk, "name": character.key}
        if role == "alice":
            alt, errors = account.create_character(
                key="Playtest alternate", location=room, home=room
            )
            if errors or alt is None:
                raise RuntimeError(f"Alternate fixture creation failed: {errors}")
            identities["alternate"] = {"account": account.pk, "character": alt.pk, "name": alt.key}
    Path(settings.GAME_DIR, "fixtures.json").write_text(json.dumps(identities), encoding="utf-8")


def at_server_start():
    guard()
    from server.conf.at_server_startstop import at_server_start as original

    original()
    install()
    # Evennia restarts once after initial setup. Only advertise the replacement
    # server, otherwise early Telnet sessions miss the connection screen.
    if SEEDED_THIS_PROCESS:
        return
    if not Path(settings.GAME_DIR, "fixtures.json").is_file():
        raise RuntimeError("Playtest fixture initialization did not finish.")
    Path(settings.GAME_DIR, "ready.json").write_text(
        json.dumps({"run_id": settings.PLAYTEST_RUN_ID, "server_pid": os.getpid()}),
        encoding="utf-8",
    )


def at_server_stop():
    from server.conf.at_server_startstop import at_server_stop as original

    original()


def at_server_init():
    pass


def at_server_reload_start():
    pass


def at_server_reload_stop():
    pass


def at_server_cold_start():
    pass


def at_server_cold_stop():
    pass
