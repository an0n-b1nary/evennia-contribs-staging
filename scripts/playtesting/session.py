"""Shared gameplay operations for suites and the persistent JSONL interface."""

import secrets
import time

from .client import Client, visible


class Session:
    def __init__(self, host):
        self.host = host
        self.clients = {}

    def connect(self, actor):
        if actor not in self.host.credentials:
            raise ValueError(f"Unknown actor: {actor}")
        if actor in self.clients:
            return self.clients[actor]
        client = Client(
            actor, self.host.ports["telnet"], self.host.evidence, self.host.action_timeout
        )
        self.clients[actor] = client
        client.expect(r"[Cc]onnect|\[Placeholder\]")
        spec = self.host.credentials[actor]
        cursor = client.send(f"connect {spec['name']} {spec['password']}")
        client.expect(r"Playtest .* laboratory", after=cursor)
        token = secrets.token_hex(8)
        cursor = client.send(f"+playtest/info {token}")
        info = client.frame("info", token, cursor)
        if info["run_id"] != self.host.run_id or info["role"] != actor or info["superuser"]:
            raise RuntimeError(f"Unexpected live identity: {info}")
        self.host.evidence.write(f"identity-{actor}.json", info)
        # Preserve normal login throttling; never disable it for test accounts.
        time.sleep(0.4)
        return client

    def send(self, actor, command):
        client = self.connect(actor)
        token = secrets.token_hex(8)
        cursor = client.send(f"+playtest/arm {token}")
        client.frame("armed", token, cursor)
        cursor = self.host.evidence.cursor
        client.send(command)
        for receiver in self.clients.values():
            receiver.frame("boundary", token, cursor)
        return {
            "cursor": cursor,
            "through": self.host.evidence.cursor,
            "output": visible(client.text(cursor)),
            "token": token,
        }

    def snapshot(self):
        staff = self.connect("staff")
        token = secrets.token_hex(8)
        cursor = staff.send(f"+playtest/state {token}")
        state = staff.frame("state", token, cursor)["state"]
        self.host.evidence.write(f"snapshot-{token}.json", state)
        return state

    def disconnect(self, actor):
        self.clients.pop(actor).close()

    def close(self):
        for client in self.clients.values():
            client.close()
        self.clients.clear()
