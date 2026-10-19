# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Partner-job selection for pull requests, and its agreement with ci.yml."""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import unittest
from unittest.mock import patch

import ci_scope as scope
from test_ci_install_contribs import ContribTreeMixin

WORKFLOW = scope.REPO_ROOT / ".github/workflows/ci.yml"
ALWAYS_RUN = {"lint", "scope", "test"}


def workflow_jobs() -> dict[str, str]:
    """Split ci.yml into {job name: job block} without needing PyYAML."""
    text = WORKFLOW.read_text(encoding="utf-8")
    body = text[text.index("\njobs:\n") :]
    parts = re.split(r"^  ([\w-]+):\n", body, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


class DependentsTests(ContribTreeMixin, unittest.TestCase):
    def test_hard_and_optional_dependents_are_affected_transitively(self):
        self.add("base", "evennia_core")
        self.add("game", "evennia_middle", ["evennia-core>=0.1"])
        self.add("game", "evennia_top", extras={"middle": ["evennia-middle>=0.1"]})
        self.add("game", "evennia_unrelated", ["evennia>=6.0"])
        graph = scope.partner_graph(self.root)
        self.assertEqual(
            scope.dependents({"evennia_core"}, graph),
            {"evennia_core", "evennia_middle", "evennia_top"},
        )
        self.assertEqual(scope.dependents({"evennia_top"}, graph), {"evennia_top"})

    def test_a_partner_change_selects_jobs_that_install_its_dependents(self):
        # Only the dependent is a subject of the job; the change is two hops away.
        self.add("base", "evennia_links")
        self.add("game", "evennia_maps", ["evennia-links"])
        self.add("game", "evennia_building", extras={"maps": ["evennia-maps"]})
        jobs = {
            "building-partners": ({"evennia_building"}, ()),
            "party-independent": ({"evennia_rp_party"}, ()),
        }
        with patch.dict(scope.JOBS, jobs, clear=True):
            selected, _ = scope.select_jobs(["contribs/base/evennia_links/models.py"], self.root)
        self.assertEqual(selected, ["building-partners"])


class SelectJobsTests(unittest.TestCase):
    def select(self, *paths):
        return scope.select_jobs(list(paths))[0]

    def test_top_level_docs_and_lint_only_files_select_no_partner_jobs(self):
        self.assertEqual(
            self.select(
                "README.md",
                "CONTRIBUTING.md",
                "scripts/file_issue.py",
                "scripts/test_ci_scope.py",
                ".pre-commit-config.yaml",
            ),
            [],
        )

    def test_unclassified_and_shared_ci_files_select_every_job(self):
        for path in (
            ".github/workflows/ci.yml",
            "scripts/ci_install_contribs.py",
            "scripts/ci_run_partner_tests.py",
            "scripts/ci_scope.py",
            "requirements.txt",
            "contribs/README.md",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.select("README.md", path), list(scope.JOBS))

    def test_a_job_runner_selects_only_its_job(self):
        self.assertEqual(self.select("scripts/ci_run_npc_tests.py"), ["npc-partners"])
        self.assertEqual(self.select("scripts/ci_run_combat_tests.py"), ["combat-independent"])

    def test_example_game_selects_the_jobs_that_copy_it(self):
        self.assertEqual(
            set(self.select("example_game/web/templates/website/guides/page.html")),
            {"lore-items-partners", "crafting-partners", "sandbox", "rp-sandbox", "live-playtest"},
        )
        self.assertIn(
            "calendar-partners",
            self.select("example_game/web/templates/rest_framework/api.html"),
        )

    def test_a_leaf_contrib_selects_its_family_and_the_whole_game_jobs(self):
        self.assertEqual(
            self.select("contribs/game_systems/evennia_boards/tests.py"),
            ["sandbox", "live-playtest", "moderation-partners"],
        )

    def test_contrib_docs_count_as_contrib_changes(self):
        # Contrib and sandbox tests read their READMEs.
        self.assertEqual(
            self.select("contribs/game_systems/evennia_boards/README.md"),
            self.select("contribs/game_systems/evennia_boards/tests.py"),
        )

    def test_a_contrib_every_contrib_depends_on_selects_every_job(self):
        self.assertEqual(
            self.select("contribs/base_systems/evennia_links/runtime.py"), list(scope.JOBS)
        )

    def test_no_change_selects_nothing(self):
        self.assertEqual(self.select(), [])


class WorkflowAgreementTests(unittest.TestCase):
    """JOBS must describe the partner jobs ci.yml actually defines."""

    def test_every_partner_job_is_mapped_and_gated_on_its_own_name(self):
        jobs = workflow_jobs()
        self.assertEqual(set(jobs) - ALWAYS_RUN, set(scope.JOBS))
        for name, block in jobs.items():
            if name in ALWAYS_RUN:
                continue
            with self.subTest(job=name):
                self.assertIn(f"contains(fromJSON(needs.scope.outputs.jobs), '{name}')", block)

    def test_contribs_a_job_installs_are_its_subjects(self):
        # A contrib named after --absent in a job that never installs it is
        # only verified as missing; every other mention means it is installed.
        for name, block in workflow_jobs().items():
            if name in ALWAYS_RUN or scope.JOBS[name][0] is scope.EVERY_CONTRIB:
                continue
            installed = re.sub(r"--absent \w+", "", block)
            mentioned = {
                label.replace("-", "_")
                for label in re.findall(r"\bevennia[-_][a-z][a-z_-]*[a-z]", installed)
            } - {"evennia_links"}
            with self.subTest(job=name):
                self.assertLessEqual(mentioned, scope.JOBS[name][0])

    def test_subjects_and_read_paths_exist(self):
        labels = set(scope.partner_graph(scope.REPO_ROOT / "contribs"))
        for name, (contribs, reads) in scope.JOBS.items():
            with self.subTest(job=name):
                self.assertLessEqual(contribs or set(), labels)
                for path in reads:
                    self.assertTrue((scope.REPO_ROOT / path).exists(), path)


class CommandLineTests(unittest.TestCase):
    def output(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(scope.main(argv), 0)
        key, _, value = out.getvalue().strip().partition("=")
        self.assertEqual(key, "jobs")
        return json.loads(value)

    def test_full_runs_select_every_job(self):
        self.assertEqual(self.output(["--all"]), list(scope.JOBS))

    def test_paths_print_a_github_output_line(self):
        self.assertEqual(self.output(["--paths", "scripts/ci_run_npc_tests.py"]), ["npc-partners"])

    def test_diff_lists_both_sides_of_a_rename(self):
        completed = subprocess.CompletedProcess([], 0, stdout="README.md\n")
        with patch.object(scope.subprocess, "run", return_value=completed) as run:
            self.assertEqual(self.output(["--diff", "HEAD^1", "HEAD"]), [])
        self.assertIn("--no-renames", run.call_args.args[0])
        self.assertEqual(run.call_args.args[0][-2:], ["HEAD^1", "HEAD"])


if __name__ == "__main__":
    unittest.main()
