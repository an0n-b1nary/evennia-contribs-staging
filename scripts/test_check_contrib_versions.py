# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Regressions for exported, packaged, and changelog version parity."""

import tempfile
import unittest
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

import check_contrib_versions as checker


class VersionChecks(unittest.TestCase):
    """Exercise release checks with packages that must never execute on inspection."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.package = self.root / "utils" / "evennia_probe"
        self.package.mkdir(parents=True)
        (self.package / "pyproject.toml").write_text(
            '[project]\nname = "evennia-probe"\nversion = "0.2.0"\n', encoding="utf-8"
        )
        (self.package / "__init__.py").write_text(
            '__version__ = "0.2.0"\nraise RuntimeError("must not import")\n', encoding="utf-8"
        )
        self.changelog("## [0.2.0] - 2026-10-02\n")

    def changelog(self, text):
        """Set the fixture's release headings."""
        (self.package / "CHANGELOG.md").write_text(text, encoding="utf-8")

    def test_checks_without_importing_package(self):
        self.assertEqual(checker.check_contrib(self.package), [])

    def test_export_drift_is_rejected(self):
        (self.package / "__init__.py").write_text('__version__ = "0.1.0"', encoding="utf-8")
        self.assertIn("__version__", checker.check_contrib(self.package)[0])

    def test_missing_and_dynamic_exports_are_rejected(self):
        for text in ("pass", "__version__ = compute_version()", "__version__ = 2"):
            with self.subTest(text=text):
                (self.package / "__init__.py").write_text(text, encoding="utf-8")
                self.assertTrue(checker.check_contrib(self.package))

    def test_changelog_drift_is_rejected(self):
        self.changelog("## 0.1.0 - initial release\n")
        self.assertIn("latest changelog", checker.check_contrib(self.package)[0])

    def test_future_and_first_release_unreleased_sections_are_allowed(self):
        for text in ("## [Unreleased]\n## [0.2.0] - today\n", "## Unreleased\n"):
            with self.subTest(text=text):
                self.changelog(text)
                self.assertEqual(checker.check_contrib(self.package), [])

    def test_buried_or_duplicate_unreleased_is_rejected(self):
        for text in (
            "## [0.2.0] - today\n## [Unreleased]\n",
            "## [Unreleased]\n## Unreleased\n## 0.2.0\n",
        ):
            with self.subTest(text=text):
                self.changelog(text)
                self.assertIn("Unreleased must", checker.check_contrib(self.package)[0])

    def test_missing_changelog_or_headings_is_rejected(self):
        self.changelog("# Changelog\n")
        self.assertTrue(checker.check_contrib(self.package))
        (self.package / "CHANGELOG.md").unlink()
        self.assertTrue(checker.check_contrib(self.package))

    def test_installed_distribution_must_match(self):
        with patch.object(checker, "version", return_value="0.2.0") as metadata:
            self.assertEqual(checker.check_contrib(self.package, installed=True), [])
            metadata.assert_called_once_with("evennia-probe")
        with patch.object(checker, "version", return_value="0.1.0"):
            self.assertIn(
                "installed version", checker.check_contrib(self.package, installed=True)[0]
            )
        with patch.object(checker, "version", side_effect=PackageNotFoundError("evennia-probe")):
            self.assertTrue(checker.check_contrib(self.package, installed=True))

    def test_empty_discovery_fails(self):
        with patch.object(checker, "CONTRIBS_ROOT", self.root / "missing"):
            self.assertEqual(checker.main([]), 1)

    def test_repository_release_metadata(self):
        self.assertEqual(checker.main([]), 0)


if __name__ == "__main__":
    unittest.main()
