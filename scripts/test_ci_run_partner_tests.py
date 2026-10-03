# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Ensure partner-test invocation never accepts a zero-test launcher exit."""

import contextlib
import io
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


if __name__ == "__main__":
    unittest.main()
