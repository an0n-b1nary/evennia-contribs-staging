# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Fault checks for data preservation and isolated package requirements."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from downstream_gate import migration_history, requirements
from downstream_runtime import database_snapshot, verify_database


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
