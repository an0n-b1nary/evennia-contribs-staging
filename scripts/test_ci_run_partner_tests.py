# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Ensure partner-test invocation never accepts a zero-test launcher exit."""

import contextlib
import io
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ci_run_partner_tests as runner


class TestPartnerRunner(unittest.TestCase):
    """Validate the real launcher's error and silently-green failure contracts."""

    def result_code(self, code, output):
        """Apply the runner check while keeping the unittest output concise."""
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return runner.test_exit_code(subprocess.CompletedProcess([], code, stdout=output))

    def test_zero_tests_or_import_failure_cannot_pass(self):
        """A successful process status requires an actual test-run summary."""
        for output in (
            "Ran 0 tests\nOK\n",
            "Settings import failed\n",
            "Found 0 test(s).\n",
            "Import failure: expected Ran 8 tests\n",
        ):
            with self.subTest(output=output):
                self.assertEqual(self.result_code(0, output), 1)

    def test_failed_test_exit_is_propagated(self):
        """Preserve the launcher failure status when tests fail."""
        self.assertEqual(self.result_code(2, "Ran 8 tests\nFAILED\n"), 2)

    def test_a_positive_count_passes_for_singular_and_plural(self):
        """Accept real unittest summaries for one or multiple tests."""
        for output in ("Ran 1 test in 0.2s\nOK\n", "Ran 278 tests in 30s\nOK\n"):
            with self.subTest(output=output):
                self.assertEqual(self.result_code(0, output), 0)

    def test_launch_uses_the_disposable_game_and_preserves_its_original_settings(self):
        """Keep generated settings intact and close stdin on the child test process."""
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory)
            conf = game / "server" / "conf"
            conf.mkdir(parents=True)
            original = "# Original generated game settings\n"
            (conf / "settings.py").write_text(original, encoding="utf-8")
            with (
                patch.object(runner.shutil, "which", return_value="evennia"),
                patch.object(
                    runner.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0, stdout="Ran 8 tests\nOK\n"),
                ) as launch,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(runner.main([str(game), "--calendar", "absent"]), 0)
            self.assertEqual((conf / "settings.py").read_text(encoding="utf-8"), original)
            self.assertIn(
                "PARTNER_TEST_CALENDAR = False",
                (conf / "partner_test_settings.py").read_text(encoding="utf-8"),
            )
            self.assertIn("--settings=partner_test_settings.py", launch.call_args.args[0])
            self.assertEqual(launch.call_args.kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(launch.call_args.kwargs["cwd"], game.resolve())
            self.assertEqual(
                (game / "web/templates/rest_framework/api.html").read_bytes(),
                (
                    runner.REPO_ROOT / "example_game/web/templates/rest_framework/api.html"
                ).read_bytes(),
            )

    def test_building_rejects_an_allegedly_absent_importable_partner(self):
        with (
            patch.object(runner, "find_spec", return_value=object()),
            self.assertRaisesRegex(ValueError, "still importable"),
        ):
            runner.building_profile(Path("unused"), ["evennia_maps"], "evennia")

    def test_building_race_gate_cannot_pass_without_running_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory)
            (game / "server/conf").mkdir(parents=True)
            with (
                patch.object(runner, "find_spec", return_value=None),
                patch.object(
                    runner.subprocess,
                    "run",
                    side_effect=[
                        subprocess.CompletedProcess([], 0, stdout="Ran 24 tests\nOK\n"),
                        subprocess.CompletedProcess([], 0, stdout="Settings import failed\n"),
                    ],
                ) as launch,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(runner.building_profile(game, ["evennia_jobs"], "evennia"), 1)
            self.assertEqual(launch.call_count, 2)
            race_command = launch.call_args.args[0]
            self.assertIn("--settings=building_race_settings.py", race_command)
            self.assertNotIn("evennia_jobs.test_concurrency", race_command)
            self.assertEqual(launch.call_args.kwargs["stdin"], subprocess.DEVNULL)
            self.assertIn(
                "building-races.sqlite3",
                (game / "server/conf/building_race_settings.py").read_text(encoding="utf-8"),
            )


class TestRunnerHosts(unittest.TestCase):
    """Every host uses the links test runner, and long suites run in parallel."""

    def launch(self, module, argv, game, init=False):
        """Run a runner's main() with `evennia` mocked; return its test commands.

        `init` lets a mocked `evennia --init` create the game the runner then
        configures; otherwise `game` is pre-initialized (or must not exist).
        """
        commands = []

        def run(command, **kwargs):
            if init and "--init" in command:
                (Path(command[-1]) / "server/conf").mkdir(parents=True)
                (Path(command[-1]) / "server/conf/settings.py").write_text("", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="Ran 8 tests\nOK\n")

        with (
            patch.object(module, "find_spec", return_value=None),
            patch.object(module.shutil, "which", return_value="evennia"),
            patch.object(module.subprocess, "run", side_effect=run),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(module.main(argv), 0)
        return commands

    def settings_text(self, game, command):
        """Read the settings file a test command names, with the host files it imports."""
        name = next(
            part.split("=", 1)[1] if "=" in part else command[command.index(part) + 1]
            for part in command
            if part.startswith("--settings")
        )
        text = (game / "server/conf" / name).read_text(encoding="utf-8")
        parent = re.match(r"from server\.conf\.(\w+) import \*", text)
        if parent and parent.group(1) != "settings":
            text += self.settings_text(game, [f"--settings={parent.group(1)}.py"])
        return text

    def initialized_game(self, directory):
        game = Path(directory) / "game"
        (game / "server/conf").mkdir(parents=True)
        (game / "server/conf/settings.py").write_text("", encoding="utf-8")
        return game

    def test_hosts_without_installer_settings_use_the_links_test_runner(self):
        """Hosts ci_install_contribs.py doesn't configure write the runner themselves."""
        import ci_run_combat_tests
        import ci_run_crafting_core_tests
        import ci_run_lore_item_tests
        import ci_run_moderation_tests
        import ci_run_party_tests

        for module, argv, init in (
            (ci_run_combat_tests, [], False),
            (ci_run_crafting_core_tests, [], False),
            (ci_run_moderation_tests, [], False),
            (ci_run_party_tests, [], False),
            (ci_run_lore_item_tests, ["--absent", "evennia_lore"], True),
        ):
            with self.subTest(runner=module.__name__), tempfile.TemporaryDirectory() as directory:
                game = Path(directory) / "game"
                if not init:
                    game = self.initialized_game(directory)
                commands = self.launch(module, [str(game), *argv], game, init)
                self.assertTrue(commands)
                for command in commands:
                    self.assertIn(runner.LINKS_TEST_RUNNER, self.settings_text(game, command))

    def test_long_suites_run_in_parallel_and_file_backed_races_serially(self):
        import ci_run_crafting_tests
        import ci_run_lore_item_tests
        import ci_run_rp_sandbox_tests

        for module, argv, serial_runs in (
            (ci_run_rp_sandbox_tests, [], 0),
            (ci_run_crafting_tests, [], 1),
            (ci_run_lore_item_tests, [], 0),
        ):
            with self.subTest(runner=module.__name__), tempfile.TemporaryDirectory() as directory:
                game = Path(directory) / "game"
                commands = self.launch(module, [str(game), *argv], game)
                self.assertIn(runner.PARALLEL, commands[0])
                self.assertEqual(len(commands), 1 + serial_runs)
                for command in commands[1:]:
                    self.assertNotIn(runner.PARALLEL, command)
                    self.assertIn("races.sqlite3", self.settings_text(game, command))

        for argv, serial_runs in ((["--building"], 1), (["--calendar", "present"], 0)):
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as directory:
                game = self.initialized_game(directory)
                commands = self.launch(runner, [str(game), *argv], game)
                self.assertIn(runner.PARALLEL, commands[0])
                self.assertEqual(len(commands), 1 + serial_runs)
                for command in commands[1:]:
                    self.assertNotIn(runner.PARALLEL, command)
                    self.assertIn("races.sqlite3", self.settings_text(game, command))


if __name__ == "__main__":
    unittest.main()
