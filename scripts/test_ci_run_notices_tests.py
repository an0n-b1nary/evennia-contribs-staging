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

    def test_minimal_calendar_settings_use_actual_source_and_no_inbox(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            (game / "server/conf").mkdir(parents=True)
            (game / "server/conf/settings.py").write_text("")
            completed = Mock(returncode=0, stdout="Ran 12 tests\nOK")
            with (
                patch.object(
                    runner,
                    "find_spec",
                    side_effect=lambda name: (
                        object() if name in {"evennia_calendar", "evennia_links"} else None
                    ),
                ),
                patch.object(runner.shutil, "which", return_value="evennia"),
                patch.object(runner.subprocess, "run", return_value=completed) as run,
            ):
                self.assertEqual(runner.main([str(game), "--minimal-calendar"]), 0)
            settings = (game / "server/conf/notices_test_settings.py").read_text()
            namespace = {"INSTALLED_APPS": []}
            exec(settings.partition("\n")[2], namespace)
            self.assertIn("evennia_calendar", namespace["INSTALLED_APPS"])
            self.assertNotIn("evennia_notices", namespace["INSTALLED_APPS"])
            self.assertIn("calendar", namespace["LINKS_NOTICE_SOURCES"])
            self.assertIn("evennia_calendar.test_notice_adapter", run.call_args.args[0])
            self.assertIn("evennia_calendar.test_notice_repairs", run.call_args.args[0])

    def test_calendar_suite_runs_when_inbox_is_present(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            (game / "server/conf").mkdir(parents=True)
            (game / "server/conf/settings.py").write_text("")
            completed = Mock(returncode=0, stdout="Ran 12 tests\nOK")
            with (
                patch.object(runner, "find_spec", return_value=object()),
                patch.object(runner.shutil, "which", return_value="evennia"),
                patch.object(runner.subprocess, "run", return_value=completed) as run,
            ):
                self.assertEqual(runner.main([str(game)]), 0)
            self.assertIn("evennia_calendar", run.call_args.args[0])
            self.assertIn("evennia_notices", run.call_args.args[0])
            self.assertIn("evennia_lore", run.call_args.args[0])

    def test_minimal_lore_collects_only_core_without_web_partners(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            (game / "server/conf").mkdir(parents=True)
            (game / "server/conf/settings.py").write_text("")
            completed = Mock(returncode=0, stdout="Ran 12 tests\nOK")
            with (
                patch.object(
                    runner,
                    "find_spec",
                    side_effect=lambda name: (
                        object() if name in {"evennia_lore", "evennia_links"} else None
                    ),
                ),
                patch.object(runner.shutil, "which", return_value="evennia"),
                patch.object(runner.subprocess, "run", return_value=completed) as run,
            ):
                self.assertEqual(runner.main([str(game), "--minimal-lore"]), 0)
            settings = (game / "server/conf/notices_test_settings.py").read_text()
            self.assertIn("evennia_lore.integrations.notices.LoreNoticeSource", settings)
            self.assertIn("evennia_lore.test_notice_adapter", run.call_args.args[0])
            self.assertNotIn("evennia_lore", run.call_args.args[0])

    def test_moderation_suite_runs_with_inbox_and_minimal_independent_settings(self):
        for minimal in (False, True):
            with self.subTest(minimal=minimal), tempfile.TemporaryDirectory() as temporary:
                game = Path(temporary)
                (game / "server/conf").mkdir(parents=True)
                (game / "server/conf/settings.py").write_text("")
                installed = {"evennia_links", "evennia_jobs", "evennia_moderation"}
                if not minimal:
                    installed.add("evennia_notices")
                with (
                    patch.object(
                        runner,
                        "find_spec",
                        side_effect=lambda name, installed=installed: (
                            object() if name in installed else None
                        ),
                    ),
                    patch.object(runner.shutil, "which", return_value="evennia"),
                    patch.object(
                        runner.subprocess,
                        "run",
                        return_value=Mock(returncode=0, stdout="Ran 12 tests\nOK"),
                    ) as run,
                ):
                    self.assertEqual(
                        runner.main([str(game), *(["--minimal-moderation"] if minimal else [])]), 0
                    )
                self.assertIn("evennia_moderation", run.call_args.args[0])
                content = (game / "server/conf/notices_test_settings.py").read_text()
                self.assertIn("ModerationNoticeSource", content)
                if minimal:
                    namespace = {"INSTALLED_APPS": []}
                    exec(content.partition("\n")[2], namespace)
                    self.assertEqual(
                        namespace["INSTALLED_APPS"],
                        ["evennia_links", "evennia_jobs", "evennia_moderation"],
                    )

    def test_minimal_boards_collects_only_standalone_core_without_web_partners(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            (game / "server/conf").mkdir(parents=True)
            (game / "server/conf/settings.py").write_text("")
            with (
                patch.object(
                    runner,
                    "find_spec",
                    side_effect=lambda name: (
                        object() if name in {"evennia_boards", "evennia_links"} else None
                    ),
                ),
                patch.object(runner.shutil, "which", return_value="evennia"),
                patch.object(
                    runner.subprocess,
                    "run",
                    return_value=Mock(returncode=0, stdout="Ran 12 tests\nOK"),
                ) as run,
            ):
                self.assertEqual(runner.main([str(game), "--minimal-boards"]), 0)
            settings = (game / "server/conf/notices_test_settings.py").read_text()
            namespace = {"INSTALLED_APPS": []}
            exec(settings.partition("\n")[2], namespace)
            self.assertEqual(namespace["INSTALLED_APPS"], ["evennia_links", "evennia_boards"])
            self.assertIn("BoardNoticeSource", namespace["LINKS_NOTICE_SOURCES"]["boards"])
            self.assertIn(
                "evennia_boards.test_notice_adapter.StandaloneActivityTests", run.call_args.args[0]
            )

    def test_minimal_social_uses_standalone_tests_without_inbox(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            (game / "server/conf").mkdir(parents=True)
            (game / "server/conf/settings.py").write_text("")
            with (
                patch.object(
                    runner,
                    "find_spec",
                    side_effect=lambda name: (
                        object()
                        if name in {"evennia_links", "evennia_posing", "evennia_social"}
                        else None
                    ),
                ),
                patch.object(runner.shutil, "which", return_value="evennia"),
                patch.object(
                    runner.subprocess,
                    "run",
                    return_value=Mock(returncode=0, stdout="Ran 12 tests\nOK"),
                ) as run,
            ):
                self.assertEqual(runner.main([str(game), "--minimal-social"]), 0)
            namespace = {"INSTALLED_APPS": []}
            settings = (game / "server/conf/notices_test_settings.py").read_text()
            exec(settings.partition("\n")[2], namespace)
            self.assertEqual(
                namespace["INSTALLED_APPS"], ["evennia_links", "evennia_posing", "evennia_social"]
            )
            self.assertIn("social-pages", namespace["LINKS_NOTICE_SOURCES"])
            self.assertIn(
                "evennia_social.tests.test_page_notices.StandalonePageTests", run.call_args.args[0]
            )
            self.assertNotIn(
                "evennia_social.tests.test_page_notice_concurrency", run.call_args.args[0]
            )

    def test_minimal_plots_verifies_package_and_collects_standalone_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            (game / "server/conf").mkdir(parents=True)
            (game / "server/conf/settings.py").write_text("")
            with (
                patch.object(
                    runner,
                    "find_spec",
                    side_effect=lambda name: (
                        object() if name in {"evennia_links", "evennia_plots"} else None
                    ),
                ),
                patch.object(runner, "check_plots_metadata") as package_check,
                patch.object(runner.shutil, "which", return_value="evennia"),
                patch.object(
                    runner.subprocess,
                    "run",
                    return_value=Mock(returncode=0, stdout="Ran 7 tests\nOK"),
                ) as run,
            ):
                self.assertEqual(runner.main([str(game), "--minimal-plots"]), 0)
            package_check.assert_called_once_with()
            namespace = {"INSTALLED_APPS": []}
            settings = (game / "server/conf/notices_test_settings.py").read_text()
            exec(settings.partition("\n")[2], namespace)
            self.assertEqual(namespace["INSTALLED_APPS"], ["evennia_links", "evennia_plots"])
            self.assertIn("PlotNoticeSource", namespace["LINKS_NOTICE_SOURCES"]["plots"])
            self.assertIn(
                "evennia_plots.test_notice_adapter.StandalonePlotNoticeTests", run.call_args.args[0]
            )
            self.assertNotIn("evennia_plots.test_notice_concurrency", run.call_args.args[0])
