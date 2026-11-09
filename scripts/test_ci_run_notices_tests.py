# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Profile harness rejects false absence and preserves positive-count checking."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import ci_run_notices_tests as runner


class NoticeRunnerTests(unittest.TestCase):
    """No optional profile may quietly retain the allegedly absent distribution."""

    def test_importable_absent_package_is_rejected_before_running(self):
        with (
            patch.object(runner, "find_spec", return_value=object()),
            self.assertRaises(SystemExit),
        ):
            runner.main(["unused", "--absent", "evennia_social"])

    def test_installed_distribution_without_import_is_rejected(self):
        with (
            patch.object(runner, "find_spec", return_value=None),
            patch.object(runner.importlib.metadata, "distribution", return_value=object()),
            self.assertRaises(SystemExit),
        ):
            runner.main(["unused", "--absent", "evennia_social"])

    def test_minimal_settings_and_positive_count_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            (game / "server/conf").mkdir(parents=True)
            (game / "server/conf/settings.py").write_text("")
            completed = Mock(returncode=0, stdout="Ran 0 tests\nOK")
            with (
                patch.object(runner, "find_spec", return_value=object()),
                patch.object(runner.shutil, "which", return_value="evennia"),
                patch.object(runner.subprocess, "run", return_value=completed),
            ):
                self.assertNotEqual(runner.main([str(game), "--minimal"]), 0)
            settings = (game / "server/conf/notices_test_settings.py").read_text()
            self.assertIn("evennia_notices", settings)
            self.assertIn("MD5PasswordHasher", settings)
            namespace = {"INSTALLED_APPS": []}
            exec(settings.partition("\n")[2], namespace)
            self.assertEqual(namespace["TEST_RUNNER"], "evennia_links.testing.TestRunner")
