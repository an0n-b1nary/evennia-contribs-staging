# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Fault checks for data preservation and isolated package requirements."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import downstream_gate as gate
import downstream_runtime as runtime
from downstream_gate import driver_identity, migration_history, requirements
from downstream_runtime import database_snapshot, verify_database


class SnapshotFixtureTests(unittest.TestCase):
    def test_pre_driver_consumer_uses_separately_pinned_public_fixtures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def create_fixtures(destination):
                path = destination / "scripts/playtesting"
                (path / "support").mkdir(parents=True)
                (path / "support/bootstrap.py").write_text("legacy", encoding="utf-8")
                (path / "scenarios.py").write_text("legacy", encoding="utf-8")

            create_fixtures(root / "new/snapshot")
            with patch.object(
                gate, "snapshot", side_effect=lambda repo, rev, dest: create_fixtures(dest)
            ) as export:
                revisions = gate.prepare_fixtures(root / "repository", root, "a" * 40, "b" * 40)
            self.assertEqual(revisions, {"old": gate.LEGACY_FIXTURE_REVISION, "new": "b" * 40})
            export.assert_called_once_with(
                root / "repository", gate.LEGACY_FIXTURE_REVISION, root / "legacy-fixtures"
            )
            fixtures = json.loads((root / "fixtures.json").read_text())
            self.assertEqual(fixtures["old"]["directory"], "legacy-fixtures")

    def test_host_copies_selected_support_into_game(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scaffold, support = root / "scaffold", root / "support"
            (scaffold / "server/conf").mkdir(parents=True)
            support.mkdir()
            (support / "bootstrap.py").write_text("legacy_fixture = True\n", encoding="utf-8")
            host = runtime.Host(scaffold=scaffold, support=support, output_root=root / "hosts")

            def command(name, *args):
                if name == "migrate":
                    with closing(sqlite3.connect(host.game / "server/evennia.db3")) as db:
                        db.execute("CREATE TABLE accounts_accountdb (id INTEGER)")

            with patch.object(host, "command", side_effect=command):
                host.prepare()
            self.assertEqual(
                (host.game / "playtest_support/bootstrap.py").read_bytes(),
                (support / "bootstrap.py").read_bytes(),
            )

    def test_upgrade_retains_old_consumer_but_fresh_uses_target(self):
        root = Path("run")
        self.assertEqual(runtime.consumer_snapshot(root, "fresh"), root / "new/snapshot")
        for mode in ("populate", "upgrade", "restore"):
            self.assertEqual(runtime.consumer_snapshot(root, mode), root / "old/snapshot")

    def test_snapshot_host_uses_matching_bootstrap(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(runtime.Host, "__init__") as init,
        ):
            source = Path(temporary)
            runtime.SnapshotHost("a" * 40, consumer_source=source, consumer_revision="b" * 40)
            self.assertEqual(init.call_args.kwargs["scaffold"], source / "example_game")
            self.assertEqual(
                init.call_args.kwargs["support"], source / "scripts/playtesting/support"
            )

    def test_scenarios_load_from_consumer_snapshot_with_relative_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            fixtures = source / "scripts/playtesting"
            fixtures.mkdir(parents=True)
            (fixtures / "scenarios.py").write_text(
                "from .client import visible\nSTATS = ('legacy-stat',)\n", encoding="utf-8"
            )
            module = runtime.fixture_module(source, "scenarios")
            self.assertEqual(module.STATS, ("legacy-stat",))
            self.assertEqual(module.visible("legacy"), "legacy")

    def test_preservation_commands_use_populated_identifiers(self):
        baseline = {
            "actors": {
                "alice": {
                    "id": 1,
                    "status": "finalized",
                    "allowance": "4",
                    "stats": {"presence": "B ++"},
                    "abilities": [{"ability__key": "proficiency", "tag__key": "performance"}],
                }
            },
            "transactions": [],
            "xp": [],
            "spends": [],
            "checks": [],
            "logs": [],
        }

        class Session:
            checked = False

            def snapshot(self):
                return {**baseline, "checks": [{"id": 1}] if self.checked else []}

            def send(self, actor, command):
                outputs = {
                    "+sheet": "Presence B ++",
                    "+abilities": "Proficiency: Performance",
                    "+xp": "XP 10",
                    "+xp/grant pt-alice=10:Forbidden": "Not permitted",
                }
                if command == "+test presence~Upgrade and restore confirmation":
                    self.checked = True
                    return {"output": "Success"}
                return {"output": outputs.get(command, "Unknown command")}

        runtime.preserved(Session(), baseline)


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.db3"
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE evennia_rp_chargen_fixture (id INTEGER PRIMARY KEY, balance INTEGER, value BLOB)"
            )
            connection.execute("INSERT INTO evennia_rp_chargen_fixture VALUES (1, 42, X'0102')")
        self.baseline = database_snapshot(self.path)

    def mutate(self, sql):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(sql)

    def test_deleted_player_data_fails(self):
        self.mutate("DELETE FROM evennia_rp_chargen_fixture")
        with self.assertRaisesRegex(AssertionError, "changed or disappeared"):
            verify_database(self.path, self.baseline)

    def test_changed_balance_fails(self):
        self.mutate("UPDATE evennia_rp_chargen_fixture SET balance=0")
        with self.assertRaisesRegex(AssertionError, "changed or disappeared"):
            verify_database(self.path, self.baseline)

    def test_additive_rows_and_columns_preserve_existing_data(self):
        self.mutate(
            "ALTER TABLE evennia_rp_chargen_fixture ADD COLUMN new_value TEXT DEFAULT 'new'"
        )
        self.mutate("INSERT INTO evennia_rp_chargen_fixture (id,balance) VALUES (2,100)")
        self.assertEqual(
            verify_database(self.path, self.baseline), {"evennia_rp_chargen_fixture": 1}
        )

    def test_binary_values_survive_manifest_serialization(self):
        restored = json.loads(json.dumps(self.baseline))
        self.assertEqual(verify_database(self.path, restored), {"evennia_rp_chargen_fixture": 1})

    def test_missing_column_fails(self):
        self.mutate("ALTER TABLE evennia_rp_chargen_fixture RENAME COLUMN balance TO lost")
        with self.assertRaisesRegex(AssertionError, "columns disappeared"):
            verify_database(self.path, self.baseline)

    def test_foreign_key_corruption_fails(self):
        self.mutate(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent INTEGER REFERENCES evennia_rp_chargen_fixture(id))"
        )
        self.mutate("INSERT INTO child VALUES (1,999)")
        with self.assertRaises(AssertionError):
            verify_database(self.path, self.baseline)


class RequirementsTests(unittest.TestCase):
    def test_driver_code_changes_invalidate_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "scripts/playtesting").mkdir(parents=True)
            for name in ("downstream_gate.py", "downstream_runtime.py", "playtesting/host.py"):
                (root / "scripts" / name).write_text("original", encoding="utf-8")
            before = driver_identity(root)
            resume = root / "run"
            (resume / "evidence").mkdir(parents=True)
            (resume / "evidence/result.json").write_text(
                json.dumps(
                    {
                        "old_revision": "a" * 40,
                        "new_revision": "b" * 40,
                        "driver_files_sha256": before,
                    }
                ),
                encoding="utf-8",
            )
            (root / "scripts/playtesting/host.py").write_text("changed", encoding="utf-8")
            self.assertNotEqual(before, driver_identity(root))
            with patch.object(gate, "ROOT", root), self.assertRaises(SystemExit) as exited:
                gate.main(
                    [
                        "--old-revision",
                        "a" * 40,
                        "--new-revision",
                        "b" * 40,
                        "--resume",
                        str(resume),
                    ]
                )
            self.assertEqual(exited.exception.code, 2)

    def test_published_migration_rewrite_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for snapshot in ("old", "new"):
                path = root / snapshot / "contribs/utils/example/migrations"
                path.mkdir(parents=True)
                (path / "0001_initial.py").write_text("original", encoding="utf-8")
            self.assertEqual(migration_history(root / "old", root / "new"), 1)
            (root / "new/contribs/utils/example/migrations/0001_initial.py").write_text(
                "rewritten", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "Published migration changed"):
                migration_history(root / "old", root / "new")

    def test_deleted_migration_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "old/contribs/utils/example/migrations"
            path.mkdir(parents=True)
            (path / "0001_initial.py").write_text("original", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Published migration changed"):
                migration_history(root / "old", root / "new")

    def test_all_siblings_and_web_extras_use_the_same_immutable_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, extras in (
                ("evennia-first", ""),
                ("evennia-second", '[project.optional-dependencies]\nweb=["evennia-first"]\n'),
            ):
                package = root / "contribs" / "utils" / name.replace("-", "_")
                package.mkdir(parents=True)
                (package / "pyproject.toml").write_text(
                    f'[project]\nname="{name}"\nversion="0.1.0"\n' + extras, encoding="utf-8"
                )
            pins, packages = requirements(root, "a" * 40)
            self.assertEqual(len(packages), 2)
            self.assertIn("evennia-second[web] @ git+", pins)
            self.assertEqual(pins.count("@" + "a" * 40 + "#"), 2)
            self.assertNotIn("-e ", pins)

    def test_empty_snapshot_fails_closed(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaisesRegex(ValueError, "no contribs"),
        ):
            requirements(Path(temporary), "a" * 40)


if __name__ == "__main__":
    unittest.main()
