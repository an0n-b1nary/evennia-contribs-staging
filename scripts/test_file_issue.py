"""Publication-boundary regressions for the guarded issue wrapper."""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import unittest
from unittest.mock import patch

import file_issue
from _anonymity_text import PatternsUnavailable


class IssuePublicationTests(unittest.TestCase):
    def invoke(self, options=(), *, metadata=None, lookup_code=0, patterns=None):
        if metadata is None:
            metadata = {"nameWithOwner": "owner/private-game", "isPrivate": True}
        if patterns is None:
            patterns = [re.compile("fixture-secret")]
        lookup = subprocess.CompletedProcess([], lookup_code, json.dumps(metadata), "")
        output = io.StringIO()
        with (
            patch.object(file_issue, "read_body", return_value="fixture-secret details"),
            patch.object(file_issue, "require_patterns", return_value=patterns),
            patch.object(file_issue.subprocess, "run", return_value=lookup) as visibility,
            patch.object(file_issue, "run_gh", return_value=0) as publish,
            contextlib.redirect_stderr(output),
        ):
            code = file_issue.main(["comment", "7", "--body-file", "reply.md", *options])
        return code, output.getvalue(), visibility, publish

    def test_default_blocks_matching_text_without_visibility_lookup(self):
        code, output, visibility, publish = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn("refusing to publish", output)
        visibility.assert_not_called()
        publish.assert_not_called()

    def test_private_target_without_explicit_flag_still_blocks(self):
        code, _, visibility, publish = self.invoke(["--repo", "owner/private-game"])
        self.assertEqual(code, 1)
        visibility.assert_not_called()
        publish.assert_not_called()

    def test_verified_private_target_warns_and_publishes_to_same_repo(self):
        code, output, visibility, publish = self.invoke(
            ["--repo", "owner/private-game", "--private"]
        )
        self.assertEqual(code, 0)
        self.assertIn("fixture-secret details", output)
        self.assertIn("verified private target: owner/private-game", output)
        self.assertNotIn("Nothing was sent", output)
        self.assertNotIn("guard: clean", output)
        self.assertEqual(visibility.call_args.args[0][3], "owner/private-game")
        publish.assert_called_once_with(
            ["issue", "comment", "7", "--body-file", "reply.md", "--repo", "owner/private-game"]
        )

    def test_private_flag_requires_explicit_owner_name(self):
        for options in (["--private"], ["--private", "--repo", "https://example.test/repo"]):
            with self.subTest(options=options):
                code, _, visibility, publish = self.invoke(options)
                self.assertEqual(code, 2)
                visibility.assert_not_called()
                publish.assert_not_called()

    def test_public_unknown_or_mismatched_target_never_publishes(self):
        for metadata in (
            {"nameWithOwner": "owner/private-game", "isPrivate": False},
            {"nameWithOwner": "owner/private-game"},
            {"nameWithOwner": "owner/private-game", "isPrivate": "true"},
            {"nameWithOwner": "owner/private-game", "isPrivate": 1},
            {"nameWithOwner": "owner/other-game", "isPrivate": True},
            {"nameWithOwner": None, "isPrivate": True},
            [],
        ):
            with self.subTest(metadata=metadata):
                code, _, _, publish = self.invoke(
                    ["--private", "--repo", "owner/private-game"], metadata=metadata
                )
                self.assertEqual(code, 2)
                publish.assert_not_called()

    def test_failed_lookup_never_publishes(self):
        code, _, _, publish = self.invoke(
            ["--private", "--repo", "owner/private-game"], lookup_code=1
        )
        self.assertEqual(code, 2)
        publish.assert_not_called()

    def test_malformed_response_and_missing_gh_fail_closed(self):
        for result in (subprocess.CompletedProcess([], 0, "not json", ""), OSError("missing gh")):
            with (
                self.subTest(result=result),
                patch.object(file_issue.subprocess, "run", side_effect=[result]),
                patch.object(file_issue, "run_gh") as publish,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(
                    file_issue.main(
                        [
                            "comment",
                            "7",
                            "--body-file",
                            "reply.md",
                            "--private",
                            "--repo",
                            "owner/private-game",
                        ]
                    ),
                    2,
                )
                publish.assert_not_called()

    def test_missing_patterns_blocks_even_verified_private_target(self):
        with (
            patch.object(file_issue, "verify_private_repo"),
            patch.object(file_issue, "read_body", return_value="details"),
            patch.object(
                file_issue, "require_patterns", side_effect=PatternsUnavailable("missing")
            ),
            patch.object(file_issue, "run_gh") as publish,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(
                file_issue.main(
                    [
                        "comment",
                        "7",
                        "--body-file",
                        "reply.md",
                        "--private",
                        "--repo",
                        "owner/private-game",
                    ]
                ),
                2,
            )
            publish.assert_not_called()

    def test_private_dry_run_checks_visibility_and_reports_hits_without_publishing(self):
        code, output, visibility, publish = self.invoke(
            ["--private", "--repo", "owner/private-game", "--dry-run"]
        )
        self.assertEqual(code, 0)
        visibility.assert_called_once()
        self.assertIn("fixture-secret details", output)
        self.assertIn("dry run", output)
        publish.assert_not_called()

    def test_clean_public_text_publishes_without_lookup(self):
        code, _, visibility, publish = self.invoke(patterns=[re.compile("different-secret")])
        self.assertEqual(code, 0)
        visibility.assert_not_called()
        publish.assert_called_once()

    def test_create_scans_title_on_private_target(self):
        output = io.StringIO()
        with (
            patch.object(file_issue, "verify_private_repo"),
            patch.object(file_issue, "read_body", return_value="clean body"),
            patch.object(
                file_issue, "require_patterns", return_value=[re.compile("fixture-secret")]
            ),
            patch.object(file_issue, "run_gh", return_value=0) as publish,
            contextlib.redirect_stderr(output),
        ):
            code = file_issue.main(
                [
                    "create",
                    "--title",
                    "fixture-secret title",
                    "--body-file",
                    "draft.md",
                    "--private",
                    "--repo",
                    "owner/private-game",
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("title line 1", output.getvalue())
        publish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
