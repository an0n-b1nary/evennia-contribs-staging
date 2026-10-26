# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The fresh-environment wrapper each CI partner profile runs through."""

from __future__ import annotations

import contextlib
import io
import os
import pathlib
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import ci_profile as profile
from test_ci_scope import workflow_jobs


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.calls = []

    def fake_run(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        code = self.setup_code if len(self.calls) < self.runner_call else self.runner_code
        if code and kwargs.get("check"):
            raise subprocess.CalledProcessError(code, command)
        return subprocess.CompletedProcess(command, code)

    def run_main(self, argv, uv="/opt/uv", setup_code=0, runner_code=0):
        self.setup_code, self.runner_code = setup_code, runner_code
        self.runner_call = 5  # venv, Evennia, --init, contribs, then the runner
        which = {"uv": uv}.get
        with (
            patch.object(profile.shutil, "which", side_effect=lambda name, path=None: which(name)),
            patch.object(profile.subprocess, "run", side_effect=self.fake_run),
            patch.dict(os.environ, {"RUNNER_TEMP": self._tmp.name, "GITHUB_ACTIONS": "false"}),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            code = profile.main(argv)
        return code, stderr.getvalue()

    def workdir(self):
        return pathlib.Path(self.calls[0][0][-1]).parent

    def test_runner_sees_a_fresh_venv_and_game_with_the_selection_installed(self):
        code, _ = self.run_main(
            ["--exclude", "evennia-scenes", "--", "python", "runner.py", "{game}/sub", "-x"]
        )
        self.assertEqual(code, 0)
        venv = self.workdir() / "venv"
        game = self.workdir() / "game"
        python = str(venv / "bin" / "python")
        (make_venv, _), (evennia, _), (init, _), (contribs, _), (runner, kwargs) = self.calls
        self.assertEqual(make_venv[:2], ["/opt/uv", "venv"])
        self.assertEqual(
            evennia, ["/opt/uv", "pip", "install", "--python", python, profile.EVENNIA_REQUIREMENT]
        )
        self.assertEqual(init, [str(venv / "bin" / "evennia"), "--init", str(game)])
        self.assertEqual(
            contribs, [python, str(profile.INSTALLER), str(game), "--exclude", "evennia-scenes"]
        )
        self.assertEqual(runner, ["python", "runner.py", f"{game}/sub", "-x"])
        self.assertEqual(kwargs["env"]["VIRTUAL_ENV"], str(venv))
        self.assertTrue(kwargs["env"]["PATH"].startswith(f"{venv / 'bin'}{os.pathsep}"))
        self.assertEqual(kwargs["cwd"], profile.REPO_ROOT)

    def test_each_run_gets_a_new_directory_and_removes_it(self):
        self.run_main(["--", "true"])
        first = self.workdir()
        self.calls.clear()
        self.run_main(["--", "true"])
        self.assertNotEqual(self.workdir(), first)
        self.assertEqual(list(pathlib.Path(self._tmp.name).iterdir()), [])

    def test_packages_install_alone_without_the_registering_installer(self):
        code, _ = self.run_main(
            ["--package", "contribs/a/one", "--package", "contribs/b/two", "--", "true"]
        )
        self.assertEqual(code, 0)
        packages = self.calls[3][0]
        self.assertEqual(packages[-4:], ["-e", "contribs/a/one", "-e", "contribs/b/two"])
        self.assertNotIn(str(profile.INSTALLER), packages)

    def test_without_uv_the_venv_module_and_pip_build_the_environment(self):
        self.run_main(["--", "true"], uv=None)
        make_venv, evennia = self.calls[0][0], self.calls[1][0]
        self.assertEqual(make_venv[1:3], ["-m", "venv"])
        self.assertEqual(evennia[1:4], ["-m", "pip", "install"])

    def test_the_runner_exit_code_is_the_result(self):
        code, _ = self.run_main(["--", "false"], runner_code=3)
        self.assertEqual(code, 3)

    def test_failed_setup_never_runs_the_runner(self):
        code, stderr = self.run_main(["--", "runner"], setup_code=1)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("Setting up the profile failed", stderr)
        self.assertEqual(list(pathlib.Path(self._tmp.name).iterdir()), [])

    def test_a_command_is_required_and_selections_do_not_mix(self):
        for argv in (
            ["--exclude", "evennia-scenes"],
            ["--exclude", "a", "--package", "b", "--", "true"],
        ):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.run_main(argv)


class WorkflowAgreementTests(unittest.TestCase):
    def test_workflow_pins_the_same_evennia(self):
        workflow = (profile.REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        pins = re.findall(r"^\s+EVENNIA_REQUIREMENT: (\S+)$", workflow, flags=re.MULTILINE)
        self.assertEqual(pins, [profile.EVENNIA_REQUIREMENT])

    def test_every_profile_of_a_shared_job_runs_after_another_fails(self):
        merged = 0
        for name, block in workflow_jobs().items():
            steps = [
                s for s in re.split(r"^      - ", block, flags=re.MULTILINE) if "ci_profile.py" in s
            ]
            if len(steps) < 2:
                continue
            merged += 1
            for step in steps:
                with self.subTest(job=name, step=step.splitlines()[0]):
                    self.assertIn("if: ${{ !cancelled() }}", step)
        self.assertTrue(merged, "expected a job that runs several profiles")


if __name__ == "__main__":
    unittest.main()
