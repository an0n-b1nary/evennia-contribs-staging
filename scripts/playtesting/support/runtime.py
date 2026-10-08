"""Guarded control frames and observation of the normal Evennia input path."""

import json
from pathlib import Path

from django.conf import settings

PREFIX = "__PLAYTEST__"


def guard():
    root = Path(settings.GAME_DIR).resolve()
    marker = root / ".playtest-host.json"
    if not getattr(settings, "PLAYTEST_RUN_ID", None) or not marker.is_file():
        raise RuntimeError("Playtest support requires a runner-created host.")
    data = json.loads(marker.read_text(encoding="utf-8"))
    if data != {"run_id": settings.PLAYTEST_RUN_ID, "game": str(root)}:
        raise RuntimeError("Playtest host identity mismatch.")
    if any(
        getattr(settings, key) != expected
        for key, expected in (
            ("TELNET_INTERFACES", ["127.0.0.1"]),
            ("WEBSERVER_INTERFACES", ["127.0.0.1"]),
            ("WEBSOCKET_CLIENT_INTERFACE", "127.0.0.1"),
            ("AMP_INTERFACE", "127.0.0.1"),
        )
    ):
        raise RuntimeError("Playtest support requires localhost listeners.")


def enrolled(session):
    account = session.account
    return bool(account and account.tags.has(settings.PLAYTEST_RUN_ID, category="playtest"))


def frame(session, kind, token, **data):
    payload = json.dumps({"kind": kind, "token": token, **data}, default=str)
    # Evennia processes output markup before it reaches the wire. JSON escapes
    # preserve literal comment data through ANSI/HTML/FuncParser processing.
    for character in "|<>$":
        payload = payload.replace(character, f"\\u{ord(character):04x}")
    session.msg(text=PREFIX + payload + "\n")


def install():
    guard()
    from evennia.server import inputfuncs

    if getattr(inputfuncs.cmdhandler, "_playtest_observer", False):
        return
    original = inputfuncs.cmdhandler

    def observed(*args, **kwargs):
        session = kwargs.get("session")
        token = session.ndb.playtest_token if session and enrolled(session) else None
        if token:
            session.ndb.playtest_token = None
        result = original(*args, **kwargs)
        if token:

            def finished(value):
                from evennia import SESSION_HANDLER

                for receiver in SESSION_HANDLER.get_sessions():
                    if enrolled(receiver):
                        frame(receiver, "boundary", token)
                return value

            result.addBoth(finished)
        return result

    observed._playtest_observer = True
    inputfuncs.cmdhandler = observed


def scripted_ten():
    from evennia_rp_rules.dice import ScriptedRoller

    return ScriptedRoller([10])
