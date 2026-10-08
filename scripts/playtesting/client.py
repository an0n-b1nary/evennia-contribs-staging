"""Persistent socket clients using Twisted's Telnet negotiation parser."""

import codecs
import json
import re
import socket
import threading
import time
from contextlib import suppress

from twisted.conch.telnet import ECHO, SGA, Telnet

from .evidence import FRAME, plain


class ClientError(RuntimeError):
    pass


class Decoder(Telnet):
    def __init__(self, receive):
        super().__init__()
        self.receive = receive
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def enableRemote(self, option):
        return option in (ECHO, SGA)

    def enableLocal(self, option):
        return False

    def applicationDataReceived(self, data):
        text = self.decoder.decode(data)
        if text:
            self.receive(text)


class SocketTransport:
    def __init__(self, sock):
        self.sock = sock
        self.lock = threading.Lock()

    def write(self, data):
        with self.lock:
            self.sock.sendall(data)

    def loseConnection(self):
        self.sock.close()


class Client:
    def __init__(self, actor, port, evidence, timeout=15):
        self.actor = actor
        self.evidence = evidence
        self.timeout = timeout
        self.condition = threading.Condition()
        self.closed = False
        self.error = None
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self.sock.settimeout(0.25)
        self.transport = SocketTransport(self.sock)
        self.decoder = Decoder(self.receive)
        self.decoder.makeConnection(self.transport)
        self.thread = threading.Thread(target=self.read_loop, daemon=True)
        self.thread.start()

    def receive(self, text):
        with self.condition:
            self.evidence.event(self.actor, "receive", text)
            self.condition.notify_all()

    def read_loop(self):
        try:
            while not self.closed:
                try:
                    data = self.sock.recv(65536)
                except TimeoutError:
                    continue
                if not data:
                    break
                self.decoder.dataReceived(data)
        except (OSError, ValueError) as exc:
            if not self.closed:
                self.error = str(exc)
        finally:
            with self.condition:
                self.closed = True
                self.condition.notify_all()

    def send(self, command):
        if not isinstance(command, str) or "\n" in command or "\r" in command:
            raise ValueError("Send one command line at a time.")
        if self.closed:
            raise ClientError(f"{self.actor}: connection closed ({self.error})")
        cursor = self.evidence.cursor
        self.evidence.event(self.actor, "send", command)
        self.transport.write(command.encode("utf-8").replace(b"\xff", b"\xff\xff") + b"\r\n")
        return cursor

    def text(self, after=0):
        return "".join(
            event["plain"]
            for event in self.evidence.after(after, self.actor)
            if event["direction"] == "receive"
        )

    def expect(self, pattern, after=0, timeout=None):
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        regex = re.compile(pattern, re.DOTALL)
        with self.condition:
            while True:
                text = self.text(after)
                match = regex.search(text)
                if match:
                    return match
                if self.closed:
                    raise ClientError(
                        f"{self.actor}: disconnected waiting for {pattern!r}: {text[-1500:]}"
                    )
                left = deadline - time.monotonic()
                if left <= 0:
                    raise ClientError(
                        f"{self.actor}: timeout waiting for {pattern!r}: {text[-1500:]}"
                    )
                self.condition.wait(min(left, 0.25))

    def frame(self, kind, token, after=0):
        # Several frames can arrive in one packet. Match by identity, not packet.
        deadline = time.monotonic() + self.timeout
        while True:
            for line in self.text(after).splitlines():
                if FRAME not in line:
                    continue
                try:
                    frame = json.loads(line.split(FRAME, 1)[1])
                except json.JSONDecodeError:
                    continue
                if frame.get("kind") == kind and frame.get("token") == token:
                    return frame
            if time.monotonic() >= deadline:
                raise ClientError(
                    f"{self.actor}: missing {kind} frame for {token}: {self.text(after)[-1500:]}"
                )
            if self.closed:
                raise ClientError(f"{self.actor}: closed waiting for {kind}")
            with self.condition:
                self.condition.wait(0.05)

    def close(self):
        self.closed = True
        with suppress(OSError):
            self.sock.shutdown(socket.SHUT_RDWR)
        self.sock.close()
        self.thread.join(timeout=2)


def visible(text):
    """Strip only test-control lines; retain the actual player-visible output."""
    return "\n".join(line for line in plain(text).splitlines() if FRAME not in line)
