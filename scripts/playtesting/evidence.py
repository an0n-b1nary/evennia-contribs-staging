"""Sanitized, sequenced evidence shared by scripted and exploratory runs."""

import json
import re
import threading
from datetime import UTC, datetime

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
FRAME = "__PLAYTEST__"
WS_QUERY = re.compile(r"(wss?://[^\s?\"'<>]+)\?[^\s\"'<>]+")


def plain(text):
    return ANSI.sub("", text).replace("\r", "")


class Evidence:
    def __init__(self, directory, secrets=()):
        self.directory = directory
        self.secrets = tuple(value for value in secrets if value)
        self.lock = threading.RLock()
        self.events = []
        self.pending = {}

    def clean(self, text):
        for value in self.secrets:
            text = text.replace(value, "[REDACTED]")
        # The stock webclient puts its browser session identifier in the
        # WebSocket query string. Preserve the endpoint, never that identifier.
        return WS_QUERY.sub(r"\1?[REDACTED]", text)

    def write(self, name, value):
        text = json.dumps(value, indent=2, default=str) + "\n"
        (self.directory / name).write_text(self.clean(text), encoding="utf-8")

    def event(self, actor, direction, text):
        with self.lock:
            if direction == "receive":
                # Retain only a suffix that could be the beginning of a secret.
                # Packet fragmentation must not bypass transcript redaction.
                text = self.pending.pop(actor, "") + text
                text = self.clean(text)
                held = max(
                    (
                        size
                        for secret in self.secrets
                        for size in range(1, len(secret))
                        if text.endswith(secret[:size])
                    ),
                    default=0,
                )
                if held:
                    self.pending[actor] = text[-held:]
                    text = text[:-held]
            event = {
                "seq": len(self.events) + 1,
                "time": datetime.now(UTC).isoformat(),
                "actor": actor,
                "direction": direction,
                "text": self.clean(text),
                "plain": self.clean(plain(text)),
            }
            self.events.append(event)
            with (self.directory / f"{actor}.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event) + "\n")
            return event

    def after(self, seq=0, actor=None):
        with self.lock:
            return [
                event.copy()
                for event in self.events
                if event["seq"] > seq and (actor is None or event["actor"] == actor)
            ]

    @property
    def cursor(self):
        with self.lock:
            return len(self.events)
