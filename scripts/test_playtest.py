"""Protocol, fault handling and ownership tests without a live game database."""

import errno
import io
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import playtest
from playtesting.client import Client, ClientError, Decoder, SocketTransport
from playtesting.evidence import Evidence, plain
from playtesting.host import Host, HostError, allocate_ports, poll_log
from playtesting.scenarios import Suite
from twisted.conch.telnet import DO, IAC, WONT

TEMP_ROOT = Path(__file__).resolve().parents[1] / ".playtest-runs" / "unit-tests"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.evidence = Evidence(Path(self.temp.name), ["secret-password"])

    def connection(self, writer):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()

        def serve():
            sock, _ = listener.accept()
            with sock:
                writer(sock)
            listener.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        client = Client("alice", listener.getsockname()[1], self.evidence, timeout=0.3)
        self.addCleanup(client.close)
        return client

    def test_fragmented_negotiation_utf8_and_ansi(self):
        output = []
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        decoder = Decoder(output.append)
        decoder.makeConnection(SocketTransport(left))
        wire = IAC + DO + b"\x55" + "\x1b[31mcafé\x1b[0m\r\n".encode()
        for byte in wire:
            decoder.dataReceived(bytes([byte]))
        self.assertEqual(plain("".join(output)), "café\n")
        self.assertEqual(right.recv(3), IAC + WONT + b"\x55")

    def test_frame_fragmentation_multiple_frames_and_cursor(self):
        gate = threading.Event()
        self.addCleanup(gate.set)

        def writer(sock):
            sock.sendall(b"OLD success\r\n")
            gate.wait(2)
            wire = b'__PLAYTEST__{"kind":"armed","token":"other"}\n__PLAYTEST__{"kind":"boundary","token":"new"}\n'
            for byte in wire:
                sock.sendall(bytes([byte]))

        client = self.connection(writer)
        client.expect("OLD")
        cursor = self.evidence.cursor
        gate.set()
        self.assertEqual(client.frame("boundary", "new", cursor)["token"], "new")
        with self.assertRaises(ClientError):
            client.expect("OLD", after=cursor)

    def test_disconnect_and_timeout_fail(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = self.connection(lambda sock: gate.wait(2))
        with self.assertRaisesRegex(ClientError, "timeout"):
            client.expect("missing", timeout=0.02)
        gate.set()
        with self.assertRaisesRegex(ClientError, "disconnected"):
            client.expect("missing")

    def test_redacts_outbound_and_inbound_credentials(self):
        self.evidence.event("alice", "send", "connect alice secret-password")
        self.evidence.event("alice", "receive", "secret-password")
        self.evidence.event("alice", "receive", "ws://127.0.0.1:123/?browser-session-token\n")
        self.evidence.write("manifest.json", {"value": "secret-password"})
        for path in Path(self.temp.name).iterdir():
            self.assertNotIn("secret-password", path.read_text())
            self.assertNotIn("browser-session-token", path.read_text())

    def test_secret_split_between_receive_packets_is_redacted(self):
        self.evidence.event("alice", "receive", "before secret-")
        self.evidence.event("alice", "receive", "password after\n")
        text = "".join(event["text"] for event in self.evidence.after())
        self.assertEqual(text, "before [REDACTED] after\n")

    def test_multiline_send_rejected(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = self.connection(lambda sock: gate.wait(2))
        with self.assertRaises(ValueError):
            client.send("look\n+sheet")

    def test_jsonl_multiple_requests_bad_json_and_eof(self):
        session = SimpleNamespace(
            host=SimpleNamespace(run_id="test", credentials={"alice": {}}, evidence=self.evidence)
        )
        output = io.StringIO()
        requests = "\n".join(("{bad", "[]", '{"id":1,"op":"read"}', '{"id":2,"op":"read"}'))
        with patch("sys.stdin", io.StringIO(requests)), patch("sys.stdout", output):
            playtest.interactive(session)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([item["id"] for item in responses if item.get("ok")], [1, 2])
        self.assertEqual(sum(item.get("ok") is False for item in responses), 2)

    def test_deliberate_bad_expectation_is_failed_case(self):
        session = SimpleNamespace(send=lambda *args: {"output": "real output"})
        suite = Suite(session)
        self.assertFalse(
            suite.case("injected failure", lambda: suite.command("alice", "look", "absent"))
        )
        self.assertFalse(suite.results[0]["passed"])


class HostTests(unittest.TestCase):
    def test_host_constructor_failure_has_environment_exit_code(self):
        args = SimpleNamespace(startup_timeout=1, action_timeout=1, shutdown_timeout=1)
        with (
            patch("playtest.Host", side_effect=HostError("missing launcher")),
            patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(playtest.run_host(args, "normal"), 2)

    def test_transient_log_unavailability_does_not_mask_other_io_errors(self):
        path = MagicMock()
        path.read_text.side_effect = [
            OSError(getattr(errno, "ENODATA", 61), "No data available"),
            "ready",
            PermissionError(13, "denied"),
        ]
        self.assertEqual(poll_log(path), "")
        self.assertEqual(poll_log(path), "ready")
        with self.assertRaises(PermissionError):
            poll_log(path)

    def test_control_frames_preserve_comment_markup_through_output_processing(self):
        from playtesting.support.runtime import frame

        session = MagicMock()
        comment = "{actor} $You() |rCOLOR|n <script>literal</script>"
        frame(session, "state", "nonce", comment=comment)
        wire = session.msg.call_args.kwargs["text"]
        self.assertNotIn("|", wire)
        self.assertNotIn("<", wire)
        self.assertNotIn("$", wire)
        self.assertEqual(json.loads(wire.removeprefix("__PLAYTEST__"))["comment"], comment)

    def test_binding_race_retries_with_new_ports_and_archives_old_log(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            host = Host.__new__(Host)
            host.game, host.run_id, host.owned = Path(directory), "test", {123: 1}
            host.startup_timeout = 1
            host.ports = allocate_ports()
            (host.game / "server/logs").mkdir(parents=True)
            host.prepare = MagicMock()
            host.discover = MagicMock()
            host.stop = MagicMock()
            host.write_settings = MagicMock()
            host.manifest = MagicMock()
            attempts = []

            def command(*args):
                attempts.append(args)
                (host.game / "launcher.log").write_text("start")
                log = host.game / "server/logs/portal.log"
                if len(attempts) == 1:
                    log.write_text("Couldn't listen on: address already in use")
                else:
                    log.write_text("started")
                    (host.game / "fixtures.json").write_text("{}")
                    (host.game / "ready.json").write_text(
                        json.dumps({"run_id": "test", "server_pid": 123})
                    )

            host.command = command
            old_ports = host.ports.copy()
            with patch("playtesting.host.socket.create_connection", return_value=MagicMock()):
                host.start()
            self.assertEqual(len(attempts), 2)
            self.assertNotEqual(host.ports, old_ports)
            self.assertTrue((host.game / "server/logs/portal.attempt-0.txt").exists())
            host.stop.assert_called_once()

    def test_cleanup_refuses_changed_process_directory(self):
        host = Host.__new__(Host)
        host.game, host.shutdown_timeout = Path.cwd(), 0
        host.discover = MagicMock()
        host.command = MagicMock()
        process = MagicMock()
        process.pid = 123
        host.owned = {123: 1}
        process.cwd.return_value = str(Path.cwd().parent)
        host.alive = lambda: [process]
        with (
            patch("playtesting.host.process_identity", return_value=1),
            self.assertRaisesRegex(HostError, "changed process ownership"),
        ):
            host.stop()
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_ports_distinct_and_local_bindable(self):
        ports = allocate_ports()
        self.assertEqual(len(set(ports.values())), 5)
        for port in ports.values():
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))

    def test_missing_fixture_marker_refuses_hook(self):
        from playtesting.support import runtime

        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            settings = SimpleNamespace(
                GAME_DIR=directory,
                PLAYTEST_RUN_ID="test",
                TELNET_INTERFACES=["127.0.0.1"],
                WEBSERVER_INTERFACES=["127.0.0.1"],
                WEBSOCKET_CLIENT_INTERFACE="127.0.0.1",
                AMP_INTERFACE="127.0.0.1",
            )
            with (
                patch.object(runtime, "settings", settings),
                self.assertRaisesRegex(RuntimeError, "runner-created"),
            ):
                runtime.guard()
            marker = Path(directory) / ".playtest-host.json"
            marker.write_text(
                json.dumps({"run_id": "test", "game": str(Path(directory).resolve())})
            )
            with patch.object(runtime, "settings", settings):
                runtime.guard()
                settings.TELNET_INTERFACES = ["0.0.0.0"]
                with self.assertRaisesRegex(RuntimeError, "localhost"):
                    runtime.guard()

    def test_cleanup_never_terminates_reused_pid(self):
        host = Host.__new__(Host)
        host.owned = {123: 1.0}
        process = SimpleNamespace(create_time=lambda: 2.0)
        with (
            patch("playtesting.host.psutil.Process", return_value=process),
            patch("playtesting.host.process_identity", return_value=2.0),
        ):
            self.assertEqual(host.alive(), [])

    def test_linux_clock_adjustment_does_not_hide_owned_process(self):
        host = Host.__new__(Host)
        host.owned = {123: 1234}
        process = SimpleNamespace(pid=123, create_time=lambda: 9999999999, status=lambda: "running")
        stat = "123 (test (with spaces)) " + " ".join(["S", *(["0"] * 18), "1234", "0"])
        with (
            patch("playtesting.host.sys.platform", "linux"),
            patch("playtesting.host.Path.read_text", return_value=stat),
            patch("playtesting.host.psutil.Process", return_value=process),
        ):
            self.assertEqual(host.alive(), [process])

    def test_discover_checks_cwd_time_and_command(self):
        host = Host.__new__(Host)
        host.game, host.started, host.owned = Path.cwd(), 100, {}
        host.boot_started = 0
        owned = SimpleNamespace(
            pid=123,
            create_time=lambda: 101,
            cwd=lambda: str(Path.cwd()),
            cmdline=lambda: ["evennia", "server"],
        )
        foreign = SimpleNamespace(
            pid=456,
            create_time=lambda: 101,
            cwd=lambda: str(Path.cwd().parent),
            cmdline=lambda: ["evennia", "server"],
        )
        with (
            patch("playtesting.host.psutil.process_iter", return_value=[owned, foreign]),
            patch("playtesting.host.process_identity", return_value=101),
        ):
            host.discover()
        self.assertEqual(host.owned, {123: 101})

    def test_runner_environment_failure_returns_two_and_cleans(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            evidence = Evidence(Path(directory))
            host = SimpleNamespace(
                directory=directory,
                artifacts=Path(directory),
                evidence=evidence,
                start=lambda: (_ for _ in ()).throw(HostError("injected setup failure")),
            )
            stopped = []
            host.stop = lambda: stopped.append(True)
            args = SimpleNamespace(
                startup_timeout=1,
                action_timeout=1,
                shutdown_timeout=1,
                mode="run",
                browser=False,
                profile="normal",
            )
            with patch("playtest.Host", return_value=host), patch("sys.stderr", io.StringIO()):
                self.assertEqual(playtest.run_host(args, "normal"), 2)
            self.assertEqual(stopped, [True])

    def test_failed_scenario_returns_one_and_empty_suite_returns_two(self):
        for cases, code in (
            ([{"name": "deliberately bad expectation", "passed": False}], 1),
            ([], 2),
        ):
            with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
                host = SimpleNamespace(
                    directory=directory,
                    artifacts=Path(directory),
                    evidence=Evidence(Path(directory)),
                    start=lambda: None,
                    stop=MagicMock(),
                )
                args = SimpleNamespace(
                    startup_timeout=1,
                    action_timeout=1,
                    shutdown_timeout=1,
                    mode="run",
                    browser=False,
                    profile="normal",
                )
                with (
                    patch("playtest.Host", return_value=host),
                    patch("playtesting.scenarios.run_rp", return_value=cases),
                    patch("sys.stderr", io.StringIO()),
                ):
                    self.assertEqual(playtest.run_host(args, "normal"), code)
                host.stop.assert_called_once()

    def test_real_process_cwd_is_inspectable(self):
        import psutil

        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            cwd=Path.cwd(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
        try:
            self.assertEqual(Path(psutil.Process(process.pid).cwd()).resolve(), Path.cwd())
        finally:
            process.terminate()
            process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
