# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Internal worker for downstream_gate.py; always uses runner-created hosts."""

from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from contextlib import closing
from pathlib import Path

from playtesting.host import HIDDEN, Host
from playtesting.session import Session


def write(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def database_snapshot(path):
    """Private logical snapshot, including core identities and cross-system rows."""
    result = {}
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        names = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (name,) in names:
            if name.startswith("sqlite_") or name == "django_migrations":
                continue
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({quote(name)})")]
            rows = [encoded(row) for row in connection.execute(f"SELECT * FROM {quote(name)}")]
            result[name] = {"columns": columns, "rows": rows}
    if not result or not any(table.startswith("evennia_rp_chargen_") for table in result):
        raise AssertionError("Refusing an empty/non-game database snapshot")
    return result


def encoded(row):
    return json.dumps(row, default=lambda value: {"bytes": value.hex()}, sort_keys=True)


def verify_database(path, expected):
    """Preserve every old row and column; additive rows/columns/tables are allowed."""
    counts = {}
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        for name, table in expected.items():
            available = {row[1] for row in connection.execute(f"PRAGMA table_info({quote(name)})")}
            assert set(table["columns"]) <= available, f"Existing columns disappeared from {name}"
            columns = ",".join(quote(column) for column in table["columns"])
            actual = Counter(
                encoded(row) for row in connection.execute(f"SELECT {columns} FROM {quote(name)}")
            )
            old = Counter(table["rows"])
            assert not old - actual, f"Existing data changed or disappeared from {name}"
            counts[name] = len(table["rows"])
    return counts


def provenance(source, revision, artifact):
    """Verify PEP 610 VCS identity and installed production files, not just versions."""
    import tomllib

    packages = {}
    for path in sorted((source / "contribs").glob("*/*/pyproject.toml")):
        project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
        dist = metadata.distribution(project["name"])
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
        assert direct.get("vcs_info", {}).get("commit_id") == revision, direct
        assert direct.get("url") == "https://github.com/an0n-b1nary/evennia-contribs-staging.git"
        assert direct.get("subdirectory") == path.parent.relative_to(source).as_posix()
        assert not direct.get("dir_info", {}).get("editable"), project["name"]
        assert dist.version == project["version"], project["name"]
        package = path.parent.name
        spec = importlib.util.find_spec(package)
        assert spec and Path(spec.origin).resolve().is_relative_to(Path(sys.prefix).resolve())
        checked = 0
        for file in path.parent.rglob("*"):
            if not file.is_file():
                continue
            relative = file.relative_to(path.parent)
            if "tests" in relative.parts or file.name.startswith("test"):
                continue
            if file.suffix != ".py" and not {"static", "templates"}.intersection(relative.parts):
                continue
            installed = Path(dist.locate_file(Path(package) / relative))
            assert installed.is_file(), f"Wheel is missing {package}/{relative}"
            assert installed.read_bytes() == file.read_bytes(), (
                f"Wheel file differs: {package}/{relative}"
            )
            checked += 1
        packages[project["name"]] = {
            "version": dist.version,
            "revision": revision,
            "production_files": checked,
        }
    actual = {
        d.metadata["Name"].lower()
        for d in metadata.distributions()
        if d.metadata["Name"].lower().startswith("evennia-")
    }
    assert actual == set(packages), (
        f"Unexpected/missing installed contribs: {actual ^ set(packages)}"
    )
    assert metadata.version("evennia") == "6.0.0"
    assert sys.prefix != sys.base_prefix
    assert "include-system-site-packages = false" in (Path(sys.prefix) / "pyvenv.cfg").read_text()
    write(
        artifact, {"revision": revision, "packages": packages, "isolated": True, "editable": False}
    )
    with (artifact.parent / "dependency-lock.txt").open("w", encoding="utf-8") as stream:
        subprocess.run(
            [sys.executable, "-m", "pip", "freeze", "--all"],
            stdin=subprocess.DEVNULL,
            stdout=stream,
            check=True,
            **HIDDEN,
        )
    return len(packages)


def consumer_snapshot(directory, mode):
    """A package upgrade retains the populated game's configuration and content."""
    return directory / ("new" if mode == "fresh" else "old") / "snapshot"


def fixture_module(source, name):
    """Load immutable consumer scenarios while retaining shared protocol helpers."""
    spec = importlib.util.spec_from_file_location(
        f"playtesting.snapshot_{name}", source / "scripts/playtesting" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SnapshotHost(Host):
    def __init__(
        self,
        revision,
        *,
        consumer_source,
        consumer_revision,
        fixture_source=None,
        fixture_revision=None,
        **kwargs,
    ):
        self.snapshot_revision = revision
        self.consumer_revision = consumer_revision
        self.fixture_revision = fixture_revision or consumer_revision
        fixture_source = fixture_source or consumer_source
        super().__init__(
            scaffold=consumer_source / "example_game",
            support=fixture_source / "scripts/playtesting/support",
            **kwargs,
        )

    def manifest(self):
        self.evidence.write(
            "manifest.json",
            {
                "run_id": self.run_id,
                "profile": self.profile,
                "snapshot_revision": self.snapshot_revision,
                "consumer_revision": self.consumer_revision,
                "fixture_revision": self.fixture_revision,
                "python": sys.version,
                "ports": self.ports,
                "versions": {
                    name: metadata.version(name)
                    for name in ("evennia", "Twisted", "psutil", "playwright")
                },
                "package_provenance": "Verified independently in provenance.json",
            },
        )

    def write_settings(self):
        super().write_settings()
        # Older scaffold snapshots have the known blank-Text option bug. This
        # test-only game setting preserves the blank value without log errors;
        # installed package code is never patched.
        with (self.game / "server/conf/playtest_settings.py").open("a", encoding="utf-8") as stream:
            stream.write("\nOPTIONS_ACCOUNT_DEFAULT = dict(OPTIONS_ACCOUNT_DEFAULT)\n")
            stream.write(
                "OPTIONS_ACCOUNT_DEFAULT['pose_separator'] = ('Visual separator between poses.', 'BaseOption', '')\n"
            )


def configured_game(game):
    os.chdir(game)
    sys.path.insert(0, str(game))
    os.environ["DJANGO_SETTINGS_MODULE"] = "server.conf.playtest_settings"
    import django

    django.setup()
    import evennia

    evennia._init()


def cross_links(game):
    configured_game(game)
    from evennia.objects.models import ObjectDB
    from evennia_lore.models import LoreAcquisition, LoreEntry, LoreSceneLink
    from evennia_scenes.models import Scene

    character = ObjectDB.objects.get(db_key="pt-alice")
    scene = Scene.objects.filter(creator=character).order_by("pk").first()
    assert scene is not None
    entry = LoreEntry.create_entry(
        title="Upgrade rehearsal record",
        body="[Placeholder] A persistent rehearsal record.",
        author=character,
    )
    link = LoreSceneLink.objects.create(entry=entry, scene_id=scene.pk)
    acquisition = LoreAcquisition.objects.create(
        entry=entry, character=character, character_name=character.key, source="seed"
    )
    return {"entry": entry.pk, "scene": scene.pk, "link": link.pk, "acquisition": acquisition.pk}


def web_and_models(game, artifacts):
    configured_game(game)
    from django.apps import apps
    from django.contrib.staticfiles import finders
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.autodetector import MigrationAutodetector
    from django.db.migrations.loader import MigrationLoader
    from django.db.migrations.state import ProjectState
    from django.test import Client
    from evennia.accounts.models import AccountDB

    call_command("check")
    loader = MigrationLoader(connection)
    labels = {app.label for app in apps.get_app_configs() if app.name.startswith("evennia_")}
    changes = MigrationAutodetector(loader.project_state(), ProjectState.from_apps(apps)).changes(
        graph=loader.graph
    )
    assert not labels.intersection(changes), (
        f"Contrib migration drift: {labels.intersection(changes)}"
    )
    client = Client()
    client.force_login(AccountDB.objects.get(username="pt-alice"))
    routes = (
        "/",
        "/scenes/",
        "/boards/",
        "/lore/",
        "/plots/",
        "/calendar/",
        "/regions/",
        "/map/",
        "/jobs/",
        "/xp/",
        "/api/v1/",
        "/webclient/",
    )
    rendered = {}
    for route in routes:
        response = client.get(route, HTTP_HOST="localhost")
        assert response.status_code == 200, f"{route}: {response.status_code}"
        assert response.content, route
        rendered[route] = {"status": response.status_code, "bytes": len(response.content)}
    assert finders.find("webclient/js/plugins/font.js")
    write(
        artifacts / "web-and-models.json",
        {
            "routes": rendered,
            "contrib_migration_drift": [],
            "upstream_migration_drift": sorted(set(changes) - labels),
        },
    )


def integration(source, directory, artifacts):
    game = directory / "integration-game"
    shutil.copytree(source / "example_game", game)
    launcher = Path(sys.executable).parent / ("evennia.exe" if os.name == "nt" else "evennia")
    log = directory / "integration.log"
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            [
                str(launcher),
                "test",
                "--settings=test_settings.py",
                "typeclasses",
                "commands",
                "world",
            ],
            cwd=game,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=1200,
            **HIDDEN,
        )
    text = log.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"Ran (\d+) tests?", text)
    assert (
        result.returncode == 0
        and matches
        and int(matches[-1]) > 0
        and re.search(r"^OK(?:\s|$)", text, re.M)
    ), "Integration tests failed or ran zero tests; see integration.log"
    write(artifacts / "integration.json", {"test_count": int(matches[-1]), "passed": True})
    return int(matches[-1])


def preserved(session, baseline):
    current = session.snapshot()
    for role, actor in baseline["actors"].items():
        # Evennia clears a character's live location on unpuppet and restores
        # its saved location on login. The offline SQL check preserves both;
        # login itself is verified by Session.connect's laboratory assertion.
        for key in ("id", "status", "allowance", "stats", "abilities"):
            assert current["actors"][role][key] == actor[key], (
                f"{role} {key} changed across restart"
            )
    for key in ("transactions", "xp", "spends", "checks", "logs"):
        for row in baseline[key]:
            assert row in current[key], f"{key} lost an existing row"
    alice = baseline["actors"]["alice"]
    stats = [key for key, value in alice["stats"].items() if value is not None]
    assert stats and alice["abilities"], "Preservation requires populated stats and abilities"

    # Keys belong to the consumer, not the current reference game's vocabulary.
    def label_pattern(key):
        return r"[\s_-]+".join(re.escape(part) for part in re.split(r"[\s_-]+", key))

    workflows = [("alice", "+sheet", label_pattern(key)) for key in stats]
    workflows += [
        ("alice", "+abilities", label_pattern(row["ability__key"])) for row in alice["abilities"]
    ]
    workflows.append(("bob", "+xp", "XP"))
    for actor, command, pattern in workflows:
        output = session.send(actor, command)["output"]
        assert re.search(pattern, output, re.I), output
    denied = session.send("alice", "+xp/grant pt-alice=10:Forbidden")
    assert re.search(
        "not permitted|permission|not available|not found|not access|not allowed|staff",
        denied["output"],
        re.I,
    ), denied
    assert session.snapshot()["xp"] == current["xp"], "Ordinary player changed the XP ledger"
    output = session.send("alice", f"+test {stats[0]}~Upgrade and restore confirmation")["output"]
    assert re.search("Success|Failure", output, re.I), output
    assert len(session.snapshot()["checks"]) == len(current["checks"]) + 1


def main():
    if not __debug__:
        raise RuntimeError("Assertions must be enabled")
    mode, path, revision = sys.argv[1:]
    directory = Path(path).resolve()
    name = "old" if mode in ("populate", "restore") else "new"
    source = directory / name / "snapshot"
    consumer = consumer_snapshot(directory, mode)
    fixture = json.loads((directory / "fixtures.json").read_text(encoding="utf-8"))[
        "new" if mode == "fresh" else "old"
    ]
    fixture_source = directory / fixture["directory"]
    consumer_revision = revision
    if mode != "fresh":
        consumer_revision = re.search(
            r"@([0-9a-f]{40})#", (directory / "old/requirements.txt").read_text(encoding="utf-8")
        ).group(1)
    phase = Path(tempfile.mkdtemp(prefix=mode + "-", dir=directory))
    artifacts = phase / "evidence"
    artifacts.mkdir()
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    result = {
        "passed": False,
        "revision": revision,
        "evidence": str(artifacts),
        "consumer_revision": consumer_revision,
        "fixture_revision": fixture["revision"],
    }
    backup = directory / "backup"
    hosts = []
    try:
        result["package_count"] = provenance(source, revision, artifacts / "provenance.json")
        if mode == "fresh":
            result["integration_tests"] = integration(source, phase, artifacts)
        restore = backup if mode in ("upgrade", "restore") else None
        host = SnapshotHost(
            revision,
            consumer_source=consumer,
            consumer_revision=consumer_revision,
            fixture_source=fixture_source,
            fixture_revision=fixture["revision"],
            output_root=phase / "hosts",
            restore=restore,
        )
        hosts.append(host)
        # The upgrade comparison happens after migrate and before server hooks
        # legitimately update volatile session/runtime state.
        if restore:
            host.prepare()
            expected = json.loads((backup / "logical.json").read_text(encoding="utf-8"))
            counts = verify_database(host.game / "server/evennia.db3", expected)
            population = json.loads((directory / "populate.json").read_text(encoding="utf-8"))
            backup_info = json.loads(
                (Path(population["evidence"]) / "backup.json").read_text(encoding="utf-8")
            )
            with closing(sqlite3.connect(host.game / "server/evennia.db3")) as connection:
                applied = connection.execute(
                    "SELECT app,name FROM django_migrations ORDER BY app,name"
                ).fetchall()
            result["new_migrations"] = sorted(
                set(map(tuple, applied)) - set(map(tuple, backup_info["applied_migrations"]))
            )
            assert (
                hashlib.sha256((backup / "database.db3").read_bytes()).hexdigest()
                == backup_info["database_sha256"]
            ), "Backup changed during rehearsal"
            write(
                artifacts / "preservation.json",
                {
                    "tables": counts,
                    "existing_rows": sum(counts.values()),
                    "integrity": "ok",
                    "foreign_keys": "ok",
                },
            )
            # start() normally prepares once; this instance is already prepared.
            host.prepare = lambda: None
        session = Session(host)
        try:
            host.start()
            if restore:
                baseline = json.loads((backup / "state.json").read_text(encoding="utf-8"))
                preserved(session, baseline)
                result["preserved_tables"] = len(counts)
                result["preserved_rows"] = sum(counts.values())
                result["ordinary_workflows"] = True
            else:
                scenarios = fixture_module(fixture_source, "scenarios")

                allowance_only = (
                    mode == "populate"
                    and not (
                        source
                        / "contribs/rpg/evennia_rp_chargen/migrations/0003_abilitydefinition_budget_cost_overrides.py"
                    ).exists()
                )
                if allowance_only:
                    suite = scenarios.Suite(session)
                    for operation in (
                        suite.prepare,
                        suite.sheets,
                        suite.pips,
                        suite.purchases,
                        suite.locks,
                        suite.scene_check,
                        suite.challenges,
                        suite.management,
                        suite.adversarial,
                        suite.tracker,
                        suite.reconnect,
                    ):
                        if not suite.case(operation.__name__, operation):
                            break
                    cases = suite.results
                    suite.command("staff", "+xp/grant pt-bob=10:Upgrade fixture", "10")
                else:
                    cases = scenarios.run_rp(session)
                if mode == "fresh":
                    cases.extend(fixture_module(fixture_source, "browser").run_browser(session))
                assert cases and all(case["passed"] for case in cases), cases
                write(artifacts / "cases.json", cases)
                result["live_cases"] = len(cases)
                if mode == "populate":
                    backup.mkdir(exist_ok=True)
                    write(backup / "state.json", session.snapshot())
        finally:
            session.close()
            host.stop()
        if mode == "populate":
            links = cross_links(host.game)
            # Exercise the older public spend service independently of the
            # then-allowance-only chargen integration, including a refund.
            from evennia.objects.models import ObjectDB
            from evennia_xp.spending import refund_xp, spend_xp
            from playtest_support.snapshot import snapshot

            bob = ObjectDB.objects.get(db_key="pt-bob")
            spend_xp(bob.pk, 1, ref_key="upgrade-persistent-spend")
            spend_xp(bob.pk, 1, ref_key="upgrade-refunded-spend")
            refund_xp(bob.pk, ref_key="upgrade-refunded-spend")
            write(backup / "state.json", snapshot())
            write(artifacts / "cross-links.json", links)
            with (
                closing(sqlite3.connect(host.game / "server/evennia.db3")) as original,
                closing(sqlite3.connect(backup / "database.db3")) as target,
            ):
                original.backup(target)
            shutil.copy2(host.game / "fixtures.json", backup / "fixtures.json")
            write(backup / "host.json", {"run_id": host.run_id, "credentials": host.credentials})
            logical = database_snapshot(backup / "database.db3")
            write(backup / "logical.json", logical)
            with closing(sqlite3.connect(backup / "database.db3")) as connection:
                applied = connection.execute(
                    "SELECT app,name FROM django_migrations ORDER BY app,name"
                ).fetchall()
            write(
                artifacts / "backup.json",
                {
                    "tables": len(logical),
                    "rows": sum(len(t["rows"]) for t in logical.values()),
                    "database_sha256": hashlib.sha256(
                        (backup / "database.db3").read_bytes()
                    ).hexdigest(),
                    "applied_migrations": applied,
                },
            )
        if mode == "fresh":
            normal = SnapshotHost(
                revision,
                profile="normal",
                consumer_source=consumer,
                consumer_revision=consumer_revision,
                fixture_source=fixture_source,
                fixture_revision=fixture["revision"],
                output_root=phase / "hosts",
            )
            hosts.append(normal)
            session = Session(normal)
            try:
                normal.start()
                cases = scenarios.run_rp(session, smoke=True)
                assert cases and all(case["passed"] for case in cases), cases
                result["normal_cases"] = len(cases)
                write(artifacts / "normal-cases.json", cases)
            finally:
                session.close()
                normal.stop()
            web_and_models(host.game, artifacts)
        if restore:
            configured_game(host.game)
            from evennia_lore.models import LoreSceneLink

            population = json.loads((directory / "populate.json").read_text(encoding="utf-8"))
            link = json.loads(
                (Path(population["evidence"]) / "cross-links.json").read_text(encoding="utf-8")
            )
            assert LoreSceneLink.objects.filter(
                pk=link["link"], entry_id=link["entry"], scene_id=link["scene"]
            ).exists()
            result["cross_links"] = True
        result["passed"] = True
    finally:
        for index, host in enumerate(hosts):
            host.stop()
            logs = (
                (host.artifacts / "server.log").read_text(encoding="utf-8")
                if (host.artifacts / "server.log").exists()
                else ""
            )
            if "Traceback" in logs or "[EE]" in logs:
                result["passed"] = False
                result["server_errors"] = True
            shutil.copytree(host.artifacts, artifacts / f"host-{index}")
        result["scaffold_override"] = "blank pose separator uses BaseOption; no package patches"
        write(directory / (mode + ".json"), result)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
