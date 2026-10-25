# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Fault checks for data preservation and isolated package requirements."""

import io
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, closing
from pathlib import Path
from unittest.mock import Mock, patch

import downstream_gate as gate
import downstream_runtime as runtime
from downstream_failures import (
    GateFailure,
    Progress,
    known_test_ids,
    public_failure,
    test_diagnostics,
)
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
            # This fixture-copy test never starts a host or uses network ports.
            with patch(
                "playtesting.host.allocate_ports",
                return_value=dict(
                    zip(
                        ("telnet", "http", "internal", "websocket", "amp"),
                        range(10001, 10006),
                        strict=True,
                    )
                ),
            ):
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
                    "+abilities": "Proficiency/Performance",
                    "+xp": "XP 10",
                    "+xp/grant pt-alice=10 # Forbidden": "Not permitted",
                }
                if command == "+test presence":
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
            for name in (
                "downstream_gate.py",
                "downstream_runtime.py",
                "downstream_failures.py",
                "playtesting/host.py",
            ):
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


class BudgetTests(unittest.TestCase):
    def test_budgets_cover_the_sandbox_suite_and_nest(self):
        # CI's rp-sandbox job ran the same suite in 22 minutes on 2026-10-13;
        # the old 20-minute integration limit cut every fresh phase off.
        self.assertGreaterEqual(runtime.INTEGRATION_TIMEOUT, 40 * 60)
        self.assertGreater(gate.PHASE_TIMEOUT, runtime.INTEGRATION_TIMEOUT)
        workflow = (gate.ROOT / ".github/workflows/downstream.yml").read_text(encoding="utf-8")
        minutes = int(re.search(r"timeout-minutes: (\d+)", workflow).group(1))
        self.assertGreater(minutes * 60, gate.PHASE_TIMEOUT)


class FailureEvidenceTests(unittest.TestCase):
    """Inject faults through the worker and parent without installing snapshots."""

    test_id = "world.tests.Sample.test_failure"
    private = "/private/host/password=fixture-secret C:\\private\\game player-record"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.scripts = self.root / "driver/scripts"
        self.scripts.mkdir(parents=True)
        (self.scripts / "downstream_gate.py").write_text("# test driver identity\n")
        self.output = self.root / "runs"
        self.stderr = io.StringIO()

    def snapshot(self, repository, revision, destination):
        game = destination / "example_game"
        (game / "world").mkdir(parents=True)
        (game / "world/tests.py").write_text(
            "class Sample:\n    def test_failure(self): pass\n", encoding="utf-8"
        )

    def fixtures(self, repository, directory, old, new):
        (directory / "fixtures.json").write_text(
            json.dumps(
                {
                    "old": {"directory": "old/snapshot", "revision": old},
                    "new": {"directory": "new/snapshot", "revision": new},
                }
            )
        )
        return {"old": old, "new": new}

    def gate(self, worker, *, budget=60):
        (self.scripts / "downstream_runtime.py").write_text(worker, encoding="utf-8")
        original_run = gate.run

        def run(command, **kwargs):
            if kwargs.get("phase") in ("fresh", "populate", "upgrade", "restore") or (
                len(command) > 1 and Path(command[1]).name == "downstream_runtime.py"
            ):
                return original_run(command, **kwargs)
            return None  # No clone, pip or browser downloads in fault-injection tests.

        with ExitStack() as stack:
            for name, replacement in (
                ("ROOT", self.scripts.parent),
                ("PHASE_TIMEOUT", budget),
                ("snapshot", self.snapshot),
                ("prepare_fixtures", self.fixtures),
                ("migration_history", lambda *args: 1),
                ("environment", lambda *args: sys.executable),
                ("run", run),
            ):
                stack.enter_context(patch.object(gate, name, replacement))
            stack.enter_context(patch("sys.stderr", self.stderr))
            stack.enter_context(patch("sys.stdout", io.StringIO()))
            status = gate.main(
                [
                    "--old-revision",
                    "a" * 40,
                    "--new-revision",
                    "b" * 40,
                    "--output-root",
                    str(self.output),
                ]
            )
        directory = next(self.output.iterdir())
        evidence = directory / "evidence"
        result = json.loads((evidence / "result.json").read_text())
        report = (evidence / "results.md").read_text()
        for path in evidence.rglob("*"):
            if path.is_file():
                for forbidden in (
                    str(self.root),
                    "/private/host",
                    "C:\\private",
                    "fixture-secret",
                    "player-record",
                ):
                    self.assertNotIn(forbidden, path.read_text(), str(path))
        for forbidden in ("fixture-secret", "/private/host", "C:\\private", "player-record"):
            self.assertNotIn(forbidden, self.stderr.getvalue())
        return status, result, report, directory

    def runtime_worker(self, operation):
        # Run the actual runtime main/finally path in an independent interpreter.
        return (
            "import sys\n"
            f"sys.path.insert(0, {str(gate.ROOT / 'scripts')!r})\n"
            "import downstream_runtime as runtime\n"
            "from types import SimpleNamespace\n"
            "runtime.provenance = lambda *args: 1\n" + operation + "\nsys.exit(runtime.main())\n"
        )

    def test_integration_failure_survives_worker_and_publication(self):
        log = (
            f"FAIL: test_failure ({self.test_id}) (record={self.private!r})\n"
            f"ERROR: test_secret (world.tests.Sample.test_secret)\n{self.private}\n"
            "Ran 12 tests in 0.123s\nFAILED (failures=1, errors=1)\n"
        )
        worker = self.runtime_worker(
            "def injected(command, **kwargs):\n"
            f"    kwargs['stdout'].write({log!r})\n"
            "    return SimpleNamespace(returncode=1)\n"
            "runtime.subprocess.run = injected"
        )
        status, result, report, directory = self.gate(worker)
        self.assertEqual(status, 1)
        summary = result["failure"]
        self.assertEqual(
            (summary["phase"], summary["step"], summary["kind"]),
            ("fresh", "integration", "nonzero_exit"),
        )
        self.assertEqual(summary["test_summary"], "Ran 12 tests")
        self.assertEqual(summary["failing_test_ids"], [self.test_id])
        self.assertIn(self.test_id, report)
        self.assertIn(self.test_id, self.stderr.getvalue())
        self.assertIn("fresh: FAIL", report)
        integration = json.loads((directory / "evidence/fresh/integration.json").read_text())
        self.assertFalse(integration["passed"])
        self.assertEqual(integration["failure"]["failing_test_ids"], [self.test_id])

    def test_integration_timeout_keeps_inner_budget(self):
        worker = self.runtime_worker(
            "def injected(command, **kwargs):\n"
            f"    raise runtime.subprocess.TimeoutExpired({[self.private]!r}, kwargs['timeout'])\n"
            "runtime.subprocess.run = injected\n"
            "runtime.INTEGRATION_TIMEOUT = 0.25"
        )
        status, result, report, _ = self.gate(worker)
        summary = result["failure"]
        self.assertEqual(status, 1)
        self.assertEqual(summary["kind"], "timeout")
        self.assertEqual(summary["step"], "integration")
        self.assertEqual(summary["budget_seconds"], 0.25)
        self.assertEqual(summary["timeout_scope"], "step")
        self.assertGreaterEqual(summary["elapsed_seconds"], 0)
        self.assertIn("timeout", report)
        self.assertIn("budget 0.25s", self.stderr.getvalue())

    def test_real_phase_timeout_uses_checkpoint_without_worker_result(self):
        worker = (
            "import sys, time\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(gate.ROOT / 'scripts')!r})\n"
            "from downstream_failures import Progress\n"
            "Progress(Path(sys.argv[2]), sys.argv[1]).start('integration')\n"
            "time.sleep(30)\n"
        )
        status, result, report, directory = self.gate(worker, budget=2)
        summary = result["failure"]
        self.assertEqual(status, 1)
        self.assertEqual(
            (summary["phase"], summary["step"], summary["kind"]),
            ("fresh", "integration", "timeout"),
        )
        self.assertEqual(summary["budget_seconds"], 2)
        self.assertEqual(summary["timeout_scope"], "phase")
        self.assertGreaterEqual(summary["elapsed_seconds"], 2)
        self.assertFalse((directory / "fresh.json").exists())
        self.assertIn("phase timeout", report)
        self.assertIn("budget 2s", self.stderr.getvalue())

    def test_assertion_has_step_without_private_message(self):
        worker = self.runtime_worker(
            "def injected(*args):\n"
            f"    raise AssertionError({self.private!r})\n"
            "runtime.provenance = injected"
        )
        status, result, report, _ = self.gate(worker)
        self.assertEqual(status, 1)
        self.assertEqual(result["failure"]["kind"], "assertion")
        self.assertEqual(result["failure"]["step"], "provenance")
        self.assertIn("provenance: assertion", report)

    def test_abrupt_worker_exit_uses_step_and_exit_code(self):
        worker = (
            "import sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(gate.ROOT / 'scripts')!r})\n"
            "from downstream_failures import Progress\n"
            "Progress(Path(sys.argv[2]), sys.argv[1]).start('host-start')\n"
            f"print({self.private!r})\n"
            "sys.exit(7)\n"
        )
        status, result, _, _ = self.gate(worker)
        self.assertEqual(status, 1)
        self.assertEqual(result["failure"]["kind"], "nonzero_exit")
        self.assertEqual(result["failure"]["exit_code"], 7)
        self.assertEqual(result["failure"]["step"], "host-start")

    def test_all_successful_phases_keep_pass_evidence(self):
        worker = (
            "import sys, json\nfrom pathlib import Path\n"
            "mode, directory, revision = sys.argv[1:]\n"
            "root = Path(directory)\n"
            "evidence = root / (mode + '-evidence')\nevidence.mkdir()\n"
            "(root / (mode + '.json')).write_text(json.dumps({\n"
            "    'passed': True, 'revision': revision, 'evidence': str(evidence)\n"
            "}))\n"
        )
        status, result, report, _ = self.gate(worker)
        self.assertEqual(status, 0)
        self.assertTrue(result["passed"])
        self.assertNotIn("failure", result)
        for mode in ("fresh", "populate", "upgrade", "restore"):
            self.assertIn(f"{mode}: PASS", report)
            self.assertNotIn("evidence", result[mode])

    def test_setup_error_never_prints_exception_message(self):
        with patch.object(self, "fixtures", side_effect=AssertionError(self.private)):
            status, result, report, _ = self.gate("")
        self.assertEqual(status, 1)
        self.assertEqual(result["failure"]["phase"], "setup")
        self.assertEqual(result["failure"]["step"], "fixtures")
        self.assertIn("assertion", report)


class FailureContractTests(unittest.TestCase):
    def test_unknown_fields_and_untrusted_identifiers_are_not_published(self):
        value = {
            "phase": "/private/host",
            "step": "secret",
            "kind": "password",
            "message": "secret",
            "test_summary": "secret",
            "test_count": 3,
            "failing_test_ids": ["secret", "world.tests.Sample.test_ok"],
            "elapsed_seconds": float("nan"),
            "budget_seconds": float("inf"),
        }
        summary = public_failure(value, {"world.tests.Sample.test_ok"})
        self.assertEqual(summary["phase"], "setup")
        self.assertEqual(summary["step"], "unknown")
        self.assertEqual(summary["kind"], "error")
        self.assertEqual(summary["test_summary"], "Ran 3 tests")
        self.assertEqual(summary["failing_test_ids"], ["world.tests.Sample.test_ok"])
        self.assertNotIn("secret", json.dumps(summary))
        self.assertNotIn("elapsed_seconds", summary)
        self.assertNotIn("budget_seconds", summary)
        self.assertEqual(public_failure({"phase": [], "step": {}, "kind": []})["kind"], "error")

    def test_subtest_parameters_are_removed_and_errors_are_named(self):
        known = {"world.tests.Sample.test_ok"}
        text = (
            "ERROR: test_ok (world.tests.Sample.test_ok) (password='secret')\n"
            "FAIL: test_wrong (world.tests.Sample.test_ok)\n"
            "Ran 1 test in 0.02s\nAssertionError: /private/game secret\n"
        )
        self.assertEqual(
            test_diagnostics(text, known),
            {
                "test_count": 1,
                "test_summary": "Ran 1 test",
                "failing_test_ids": ["world.tests.Sample.test_ok"],
            },
        )

    def test_zero_tests_and_nonzero_exit_write_failure_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "source/example_game").mkdir(parents=True)
            for count, code in ((0, 0), (2, 1)):
                phase = root / str(count)
                artifacts = phase / "evidence"
                artifacts.mkdir(parents=True)

                def injected(command, *, count=count, code=code, **kwargs):
                    kwargs["stdout"].write(f"Ran {count} tests in 0.01s\nOK\n")
                    return subprocess.CompletedProcess(command, code)

                with (
                    patch.object(runtime.subprocess, "run", side_effect=injected),
                    self.assertRaises(GateFailure) as raised,
                ):
                    runtime.integration(root / "source", phase, artifacts)
                self.assertEqual(raised.exception.summary["test_count"], count)
                summary = json.loads((artifacts / "integration.json").read_text())
                self.assertFalse(summary["passed"])
                self.assertEqual(
                    summary["failure"]["kind"], "assertion" if code == 0 else "nonzero_exit"
                )

    def test_failed_worker_retry_discards_stale_result_and_step(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "fresh.json").write_text(json.dumps({"failure": {"step": "integration"}}))
            Progress(directory, "fresh").start("integration")
            with (
                patch.object(
                    gate,
                    "run",
                    side_effect=GateFailure(
                        {
                            "phase": "fresh",
                            "step": "worker",
                            "kind": "nonzero_exit",
                            "exit_code": 7,
                        }
                    ),
                ),
                self.assertRaises(GateFailure) as raised,
            ):
                gate.run_phase(sys.executable, "fresh", directory, "a" * 40)
            self.assertEqual(raised.exception.summary["step"], "worker")
            self.assertFalse((directory / "fresh.json").exists())

    def test_cleanup_error_preserves_primary_failure_and_step(self):
        with tempfile.TemporaryDirectory() as temporary:
            progress = Progress(Path(temporary), "upgrade")
            progress.start("workflows")
            session, host = Mock(), Mock()
            session.close.side_effect = RuntimeError("cleanup-secret")
            try:
                raise AssertionError("primary-secret")
            except AssertionError:
                with patch("sys.stderr", io.StringIO()):
                    runtime.close_session(session, host, progress)
                summary = progress.failed(sys.exception())
            self.assertEqual(summary["step"], "workflows")
            self.assertEqual(summary["kind"], "assertion")
            host.stop.assert_called_once()

    def test_failure_helper_changes_invalidate_driver_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "scripts").mkdir()
            helper = root / "scripts/downstream_failures.py"
            helper.write_text("original")
            before = driver_identity(root)
            helper.write_text("changed")
            self.assertNotEqual(before, driver_identity(root))

    def test_source_names_are_read_without_importing_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tests.py").write_text(
                "raise RuntimeError('must not import')\n"
                "class Sample:\n    def test_ok(self): pass\n"
            )
            self.assertEqual(known_test_ids(root), {"tests.Sample.test_ok"})


if __name__ == "__main__":
    unittest.main()
