"""Regression tests for the pre-push publication boundary."""

from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import anonymity_push_guard as guard

REMOTE = "https://github.com/fixture-maintainer/public-contribs.git"
SHA = "a" * 40
REF = f"refs/heads/main {SHA} refs/heads/main {guard.ZERO_SHA}\n"


class PushGuardTests(unittest.TestCase):
    def invoke(
        self,
        *,
        args=("origin", REMOTE),
        env=None,
        account="fixture-maintainer",
        patterns=None,
        stdin=REF,
        gh_error=None,
    ):
        if patterns is None:
            patterns = [re.compile("fixture-secret")]
        output = io.StringIO()
        with (
            patch.dict(os.environ, env or {}, clear=True),
            patch.object(guard, "expected_account", return_value=account),
            patch.object(guard, "load_patterns", return_value=patterns) as loader,
            patch.object(guard, "commits_to_check", return_value=[SHA]),
            patch.object(
                guard.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, SHA + "\n", ""),
            ),
            patch.object(guard, "commit_identity", return_value=[("author name", "safe")]),
            patch.object(guard, "check_gh_account", return_value=gh_error) as gh,
            patch.object(guard.PATTERNS_FILE.__class__, "exists", return_value=True),
            patch.object(sys, "stdin", io.StringIO(stdin)),
            contextlib.redirect_stderr(output),
        ):
            code = guard.main(list(args))
        return code, output.getvalue(), loader, gh

    def test_clean_native_push_passes_and_wrong_account_blocks(self):
        for gh_error, expected in ((None, 0), ("wrong active account", 1)):
            with self.subTest(gh_error=gh_error):
                code, _, loader, gh = self.invoke(gh_error=gh_error)
                self.assertEqual(code, expected)
                loader.assert_called_once()
                gh.assert_called_once()

    def test_pattern_read_failures_and_invalid_regex_block(self):
        with (
            patch.object(guard, "load_patterns", side_effect=OSError("unreadable")),
            patch.object(guard, "expected_account", return_value="fixture-maintainer"),
            patch.object(guard, "check_gh_account") as gh,
            patch.object(guard.PATTERNS_FILE.__class__, "exists", return_value=True),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertNotEqual(guard.main(["origin", REMOTE]), 0)
            gh.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            pattern_file = Path(directory) / "patterns"
            pattern_file.write_text("[invalid\n", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                guard.load_patterns(pattern_file)
            self.assertEqual(exc.exception.code, 2)

    def test_unconfigured_clone_and_unprotected_remote_skip_checks(self):
        for options in ({"account": None}, {"args": ("origin", "https://example.test/repo")}):
            with self.subTest(options=options):
                code, _, loader, gh = self.invoke(**options)
                self.assertEqual(code, 0)
                loader.assert_not_called()
                gh.assert_not_called()

    def test_missing_or_empty_patterns_refuse_protected_push(self):
        with (
            patch.object(guard.PATTERNS_FILE.__class__, "exists", return_value=False),
            patch.object(guard, "expected_account", return_value="fixture-maintainer"),
            patch.object(guard, "check_gh_account") as gh,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertNotEqual(guard.main(["origin", REMOTE]), 0)
            gh.assert_not_called()
        code, _, _, gh = self.invoke(patterns=[])
        self.assertNotEqual(code, 0)
        gh.assert_not_called()

    def test_precommit_environment_runs_the_guard_without_arguments(self):
        code, _, loader, gh = self.invoke(
            args=(),
            env={
                "PRE_COMMIT_REMOTE_NAME": "origin",
                "PRE_COMMIT_REMOTE_URL": REMOTE,
                "PRE_COMMIT_LOCAL_BRANCH": "refs/heads/main",
                "PRE_COMMIT_FROM_REF": "b" * 40,
                "PRE_COMMIT_TO_REF": SHA,
            },
            gh_error="wrong active account",
        )
        self.assertNotEqual(code, 0)
        loader.assert_called_once()
        gh.assert_called_once()

    def test_configured_clone_without_remote_context_fails_closed(self):
        code, _, _, _ = self.invoke(args=())
        self.assertNotEqual(code, 0)

    def test_native_push_checks_every_ref_and_identity(self):
        refs = REF + f"refs/heads/other {'b' * 40} refs/heads/other {SHA}\n"
        with (
            patch.object(guard, "commits_to_check", side_effect=[[SHA], ["b" * 40]]),
            patch.object(
                guard,
                "commit_identity",
                side_effect=[
                    [("author name", "safe")],
                    [("committer email", "fixture-secret@example.test")],
                ],
            ),
            patch.object(sys, "stdin", io.StringIO(refs)),
        ):
            failures = guard.check_commits([re.compile("fixture-secret")])
        self.assertEqual(len(failures), 1)
        self.assertIn("committer email", failures[0])

    def test_git_failures_do_not_become_empty_clean_commit_lists(self):
        failed = subprocess.CompletedProcess([], 128, "", "unknown revision")
        with patch.object(guard.subprocess, "run", return_value=failed):
            for operation in (
                lambda: guard.commits_to_check(SHA, "b" * 40),
                lambda: guard.commit_identity(SHA),
            ):
                with self.subTest(operation=operation), self.assertRaises(RuntimeError):
                    operation()

    def test_malformed_ref_input_does_not_pass(self):
        with (
            patch.object(sys, "stdin", io.StringIO("broken ref line\n")),
            self.assertRaises(RuntimeError),
        ):
            guard.check_commits([re.compile("fixture-secret")])

    def test_native_deletion_has_no_commits(self):
        self.assertEqual(guard.commits_to_check(guard.ZERO_SHA, SHA), [])


class PrePushHookIntegrationTests(unittest.TestCase):
    """Exercise the real pre-commit dispatcher in disposable Git repositories."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.env = os.environ.copy()
        for key in tuple(self.env):
            if key.startswith(("GIT_", "PRE_COMMIT_")):
                del self.env[key]
        self.git("init", "-b", "main")
        self.git("config", "user.name", "safe-fixture")
        self.git("config", "user.email", "safe@example.test")
        self.git("config", "anonymity.expected-gh-account", "fixture-maintainer")
        scripts = self.repo / "scripts"
        scripts.mkdir()
        for name in ("anonymity_push_guard.py", "_anonymity_patterns.py"):
            shutil.copyfile(Path(__file__).parent / name, scripts / name)
        (self.repo / ".anonymity-patterns").write_text("fixture-secret\n", encoding="utf-8")
        (self.repo / ".pre-commit-config.yaml").write_text(
            "repos:\n- repo: local\n  hooks:\n  - id: push-guard\n    name: push guard\n"
            f"    entry: '\"{Path(sys.executable).as_posix()}\" scripts/anonymity_push_guard.py'\n"
            "    language: system\n    pass_filenames: false\n    always_run: true\n"
            "    stages: [pre-push]\n",
            encoding="utf-8",
        )
        (self.repo / ".gitignore").write_text(".anonymity-patterns\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "safe base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("update-ref", "refs/remotes/origin/main", self.base)

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=self.env, capture_output=True, text=True, check=True
        )

    def commit(self, name):
        (self.repo / "content.txt").write_text(name, encoding="utf-8")
        self.git("add", "content.txt")
        self.git("-c", f"user.name={name}", "commit", "-m", "fixture change")
        return self.git("rev-parse", "HEAD").stdout.strip()

    def dispatch(self, refs):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pre_commit",
                "hook-impl",
                "--hook-type",
                "pre-push",
                "--hook-dir",
                str(self.repo / ".git" / "hooks"),
                "--",
                "origin",
                REMOTE,
            ],
            input=refs,
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_real_dispatcher_blocks_forbidden_identity(self):
        sha = self.commit("fixture-secret")
        result = self.dispatch(f"refs/heads/main {sha} refs/heads/main {self.base}\n")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("forbidden identity", result.stdout + result.stderr)

    def test_real_dispatcher_blocks_when_patterns_are_missing(self):
        sha = self.commit("safe-fixture")
        (self.repo / ".anonymity-patterns").unlink()
        result = self.dispatch(f"refs/heads/main {sha} refs/heads/main {self.base}\n")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(".anonymity-patterns not found", result.stdout + result.stderr)

    def test_real_dispatcher_allows_an_unconfigured_external_clone(self):
        self.git("config", "--unset", "anonymity.expected-gh-account")
        sha = self.commit("safe-fixture")
        (self.repo / ".anonymity-patterns").unlink()
        result = self.dispatch(f"refs/heads/main {sha} refs/heads/main {self.base}\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_dispatcher_blocks_a_new_repository_root_push(self):
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        sha = self.commit("fixture-secret")
        result = self.dispatch(f"refs/heads/main {sha} refs/heads/main {guard.ZERO_SHA}\n")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("forbidden identity", result.stdout + result.stderr)

    def test_plain_install_creates_both_framework_hooks(self):
        shutil.copyfile(
            Path(__file__).parent.parent / ".pre-commit-config.yaml",
            self.repo / ".pre-commit-config.yaml",
        )
        result = subprocess.run(
            [sys.executable, "-m", "pre_commit", "install"],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for hook in ("pre-commit", "pre-push"):
            hook_path = (
                self.repo / self.git("rev-parse", "--git-path", f"hooks/{hook}").stdout.strip()
            )
            self.assertTrue(hook_path.is_file())
            self.assertIn(f"--hook-type={hook}", hook_path.read_text(encoding="utf-8"))

    def test_real_dispatcher_checks_second_pushed_branch(self):
        clean = self.commit("safe-fixture")
        self.git("checkout", "-b", "other", self.base)
        bad = self.commit("fixture-secret")
        result = self.dispatch(
            f"refs/heads/main {clean} refs/heads/main {self.base}\n"
            f"refs/heads/other {bad} refs/heads/other {guard.ZERO_SHA}\n"
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("forbidden identity", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
