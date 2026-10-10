"""Disposable localhost Evennia hosts with process ownership checked on cleanup."""

import errno
import json
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing, suppress
from datetime import UTC, datetime
from importlib.metadata import distributions, version
from pathlib import Path

import psutil

from .evidence import Evidence

ROOT = Path(__file__).resolve().parents[2]
HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
ROLES = ("alice", "bob", "staff", "browser", "browser-observer")


class HostError(RuntimeError):
    pass


def poll_log(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        # Rotation and WSL/NTFS can briefly make a live log unavailable.
        if exc.errno in (errno.ENOENT, errno.EAGAIN, getattr(errno, "ENODATA", 61)):
            return ""
        raise


def process_identity(process):
    """Stable PID generation, including across Linux/WSL wall-clock updates."""
    if sys.platform.startswith("linux"):
        # /proc stat field 22 is starttime in boot-relative clock ticks. The
        # parenthesized command can contain spaces and closing parentheses.
        fields = Path(f"/proc/{process.pid}/stat").read_text().rsplit(") ", 1)[1].split()
        return int(fields[19])
    return process.create_time()


def allocate_ports():
    """Reserve distinct ephemeral ports together; the launcher binds after release."""
    reservations = []
    try:
        for _ in range(5):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            reservations.append(sock)
        return dict(
            zip(
                ("telnet", "http", "internal", "websocket", "amp"),
                (sock.getsockname()[1] for sock in reservations),
                strict=True,
            )
        )
    finally:
        for sock in reservations:
            sock.close()


class Host:
    def __init__(
        self,
        profile="deterministic",
        startup=180,
        action=15,
        shutdown=30,
        *,
        scaffold=None,
        support=None,
        output_root=None,
        restore=None,
    ):
        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4)
        self.directory = (output_root or ROOT / ".playtest-runs") / self.run_id
        self.scaffold = scaffold or ROOT / "example_game"
        self.support = support or Path(__file__).parent / "support"
        self.restore = restore
        self.game = (self.directory / "game").resolve()
        self.artifacts = self.directory / "evidence"
        self.artifacts.mkdir(parents=True)
        self.profile = profile
        self.startup_timeout, self.action_timeout, self.shutdown_timeout = startup, action, shutdown
        self.credentials = {
            role: {"name": "pt-" + role, "password": secrets.token_urlsafe(24)} for role in ROLES
        }
        if restore is not None:
            # Only the downstream gate supplies this runner-created backup.
            # The destination is always a new host, never an existing game.
            saved = json.loads((restore / "host.json").read_text(encoding="utf-8"))
            self.run_id = saved["run_id"]
            self.credentials = saved["credentials"]
        self.owner_password = secrets.token_urlsafe(32)
        self.evidence = Evidence(
            self.artifacts,
            [self.owner_password] + [spec["password"] for spec in self.credentials.values()],
        )
        self.ports = allocate_ports()
        self.owned = {}
        self.started = time.time()
        self.boot_started = (
            time.clock_gettime(time.CLOCK_BOOTTIME) if sys.platform.startswith("linux") else None
        )
        self.env = {
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "EVENNIA_SUPERUSER_USERNAME": "playtest-owner",
            "EVENNIA_SUPERUSER_EMAIL": "owner@example.invalid",
            "EVENNIA_SUPERUSER_PASSWORD": self.owner_password,
        }
        self.launcher = str(
            Path(sys.executable).parent / ("evennia.exe" if os.name == "nt" else "evennia")
        )
        if not Path(self.launcher).is_file():
            raise HostError("Run with the Python environment containing Evennia.")

    def command(self, *arguments, timeout=None):
        with (self.game / "launcher.log").open("a", encoding="utf-8") as log:
            result = subprocess.run(
                [self.launcher, *arguments, "--settings=playtest_settings.py"],
                cwd=self.game,
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout or self.startup_timeout,
                **HIDDEN,
            )
        if result.returncode:
            raise HostError(f"Evennia {arguments[0]} exited {result.returncode}; see launcher.log")

    def prepare(self):
        shutil.copytree(
            self.scaffold,
            self.game,
            ignore=shutil.ignore_patterns(
                "*.db3*",
                "*.sqlite3*",
                "secret_settings.py",
                "__pycache__",
                "*.pyc",
                "*.log*",
                "*.pid",
                "*.restart",
                ".static",
                ".media",
                "media",
                "staticfiles",
                "logs",
            ),
        )
        shutil.copytree(
            self.support,
            self.game / "playtest_support",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (self.game / "server/logs").mkdir(parents=True, exist_ok=True)
        (self.game / ".playtest-host.json").write_text(
            json.dumps({"run_id": self.run_id, "game": str(self.game)}), encoding="utf-8"
        )
        (self.game / "credentials.json").write_text(json.dumps(self.credentials), encoding="utf-8")
        self.write_settings()
        if self.restore is not None:
            shutil.copy2(self.restore / "database.db3", self.game / "server/evennia.db3")
            shutil.copy2(self.restore / "fixtures.json", self.game / "fixtures.json")
        self.command("migrate", "--noinput")
        database = self.game / "server/evennia.db3"
        if not database.is_file():
            raise HostError("Migration created no database; see launcher.log")
        with closing(sqlite3.connect(database)) as connection:
            if not connection.execute(
                "SELECT name FROM sqlite_master WHERE name='accounts_accountdb'"
            ).fetchone():
                raise HostError("Migration did not create account tables; see launcher.log")
        self.command("collectstatic", "--noinput")

    def reload(self):
        """Reload only this disposable Server; verify the new owned process is ready."""
        marker = self.game / "ready.json"
        previous = json.loads(marker.read_text(encoding="utf-8"))["server_pid"]
        marker.unlink()
        self.command("reload")
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            self.discover()
            if marker.is_file():
                ready = json.loads(marker.read_text(encoding="utf-8"))
                if ready.get("run_id") != self.run_id:
                    raise HostError("Reloaded Server fixture identity mismatch")
                if ready.get("server_pid") != previous and ready.get("server_pid") in self.owned:
                    self.manifest()
                    return
            time.sleep(0.2)
        raise HostError("Reloaded Server did not become ready; see server.log")

    def write_settings(self):
        p = self.ports
        overrides = {
            "MAX_NR_CHARACTERS": 2,  # Ordinary-account alt for exchange policy checks.
            "PLAYTEST_RUN_ID": self.run_id,
            "PLAYTEST_CREDENTIALS_FILE": str(self.game / "credentials.json"),
            "TELNET_PORTS": [p["telnet"]],
            "TELNET_INTERFACES": ["127.0.0.1"],
            "WEBSERVER_PORTS": [(p["http"], p["internal"])],
            "WEBSERVER_INTERFACES": ["127.0.0.1"],
            "WEBSOCKET_CLIENT_PORT": p["websocket"],
            "WEBSOCKET_CLIENT_INTERFACE": "127.0.0.1",
            "WEBSOCKET_CLIENT_URL": f"ws://127.0.0.1:{p['websocket']}",
            "AMP_PORT": p["amp"],
            "AMP_INTERFACE": "127.0.0.1",
            "SSL_ENABLED": False,
            "SSH_ENABLED": False,
            "GRAPEVINE_ENABLED": False,
            "IRC_ENABLED": False,
            "RSS_ENABLED": False,
            "ALLOWED_HOSTS": ["127.0.0.1", "localhost"],
            "CSRF_TRUSTED_ORIGINS": [f"http://127.0.0.1:{p['http']}"],
            "AT_INITIAL_SETUP_HOOK_MODULE": "playtest_support.bootstrap",
            "AT_SERVER_STARTSTOP_MODULE": "playtest_support.bootstrap",
            "RP_RULES_ROLLER": "playtest_support.runtime.scripted_ten"
            if self.profile == "deterministic"
            else None,
        }
        text = "from server.conf.settings import *  # noqa: F403\n"
        text += "\n".join(f"{key} = {value!r}" for key, value in overrides.items()) + "\n"
        (self.game / "server/conf/playtest_settings.py").write_text(text, encoding="utf-8")

    def discover(self):
        """Daemonized children retain this run's cwd; record PID plus creation time."""
        for process in psutil.process_iter():
            try:
                if Path(process.cwd()).resolve() != self.game:
                    continue
                identity = process_identity(process)
                if sys.platform.startswith("linux"):
                    if identity / os.sysconf("SC_CLK_TCK") < self.boot_started - 1:
                        continue
                elif process.create_time() < self.started - 1:
                    continue
                command = process.cmdline()
                if any(
                    Path(argument).name.lower()
                    in ("evennia", "evennia.exe", "twistd", "twistd.exe")
                    for argument in command
                ):
                    self.owned[process.pid] = identity
            except (psutil.Error, OSError):
                continue

    def alive(self):
        result = []
        for pid, created in self.owned.items():
            try:
                process = psutil.Process(pid)
                if (
                    process_identity(process) == created
                    and process.status() != psutil.STATUS_ZOMBIE
                ):
                    result.append(process)
            except (psutil.Error, OSError):
                pass
        return result

    def start(self):
        self.prepare()
        for attempt in range(5):
            launcher_log = self.game / "launcher.log"
            launcher_offset = launcher_log.stat().st_size if launcher_log.exists() else 0
            self.command("start")
            deadline = time.monotonic() + self.startup_timeout
            while time.monotonic() < deadline:
                self.discover()
                marker = self.game / "ready.json"
                if marker.is_file():
                    data = json.loads(marker.read_text(encoding="utf-8"))
                    if (
                        data.get("run_id") != self.run_id
                        or not (self.game / "fixtures.json").is_file()
                    ):
                        raise HostError("Server fixture identity mismatch")
                    if data.get("server_pid") not in self.owned:
                        raise HostError("Cannot verify the ready Server's process ownership")
                    try:
                        with socket.create_connection(
                            ("127.0.0.1", self.ports["telnet"]), timeout=1
                        ):
                            pass
                        self.manifest()
                        return self
                    except OSError:
                        pass
                with launcher_log.open(encoding="utf-8", errors="replace") as stream:
                    stream.seek(launcher_offset)
                    launcher_output = stream.read()
                logs = launcher_output + "\n".join(
                    poll_log(path) for path in self.game.glob("server/logs/*.log")
                )
                if (
                    "Error in initial setup" in logs
                    or "Playtest fixture initialization did not finish" in logs
                ):
                    raise HostError("Fixture setup failed; see server.log")
                if "Portal process error" in logs:
                    raise HostError("Portal process failed; see launcher.log")
                if "Couldn't listen on" in logs or "CannotListenError" in logs:
                    break
                time.sleep(0.2)
            else:
                raise HostError(f"Server did not become ready in {self.startup_timeout}s")
            self.stop()
            if attempt == 4:
                raise HostError("Listener allocation failed five times")
            for path in self.game.glob("server/logs/*.log"):
                path.rename(path.with_suffix(f".attempt-{attempt}.txt"))
            (self.game / "ready.json").unlink(missing_ok=True)
            self.ports = allocate_ports()
            self.write_settings()
        raise HostError("Startup failed")

    def manifest(self):
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, **HIDDEN
        ).stdout.strip()
        self.evidence.write(
            "manifest.json",
            {
                "run_id": self.run_id,
                "profile": self.profile,
                "revision": revision,
                "python": sys.version,
                "ports": self.ports,
                "versions": {
                    name: version(name) for name in ("evennia", "Twisted", "psutil", "playwright")
                },
                "contribs": {
                    dist.metadata["Name"]: dist.version
                    for dist in distributions()
                    if dist.metadata["Name"].startswith("evennia-")
                },
                "working_tree_dirty": bool(
                    subprocess.run(
                        ["git", "status", "--porcelain"],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        **HIDDEN,
                    ).stdout.strip()
                ),
            },
        )

    def stop(self):
        self.discover()
        if self.alive():
            with suppress(HostError, subprocess.TimeoutExpired):
                self.command("stop", timeout=self.shutdown_timeout)
            deadline = time.monotonic() + self.shutdown_timeout
            while self.alive() and time.monotonic() < deadline:
                time.sleep(0.1)
            for process in self.alive():
                # Recheck both identity and cwd immediately before terminating.
                try:
                    if (
                        process_identity(process) != self.owned[process.pid]
                        or Path(process.cwd()).resolve() != self.game
                    ):
                        raise HostError(f"Cleanup refused changed process ownership: {process.pid}")
                    process.terminate()
                except (psutil.NoSuchProcess, FileNotFoundError):
                    pass
            _, remaining = psutil.wait_procs(self.alive(), timeout=3)
            for process in remaining:
                with suppress(psutil.NoSuchProcess, FileNotFoundError):
                    if (
                        process_identity(process) == self.owned[process.pid]
                        and Path(process.cwd()).resolve() == self.game
                    ):
                        process.kill()
            psutil.wait_procs(remaining, timeout=3)
            if self.alive():
                raise HostError("Owned processes remain after cleanup")
        self.collect_logs()
        self.evidence.write(
            "cleanup.json",
            {"verified": True, "owned_pids": sorted(self.owned), "remaining_pids": []},
        )

    def collect_logs(self):
        if not self.game.exists():
            return
        for path in [
            self.game / "launcher.log",
            *self.game.glob("server/logs/*.log"),
            *self.game.glob("server/logs/*.attempt-*.txt"),
        ]:
            if path.is_file():
                (self.artifacts / path.name).write_text(
                    self.evidence.clean(path.read_text(encoding="utf-8", errors="replace")),
                    encoding="utf-8",
                )
