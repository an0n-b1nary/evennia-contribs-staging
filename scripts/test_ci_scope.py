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


def job_scripts(block: str) -> set[str]:
    """Repo paths of the scripts a job's steps run with `python`."""
    return set(re.findall(r"\bpython (?:\.\./)?(scripts/[\w/]+\.py)\b", block))


def workflow_steps(block: str) -> list[tuple[str, str]]:
    """A job block's steps as (name, text) pairs, in order, duplicates kept.

    An unnamed step is named by its first line (`uses: ...`). Full-line comments
    are dropped, so the comment above a step isn't part of the previous step.
    """
    steps = []
    for step in re.split(r"(?m)^      - ", block)[1:]:
        text = "\n".join(line for line in step.splitlines() if not line.lstrip().startswith("#"))
        steps.append((text.split("\n", 1)[0].removeprefix("name: "), text))
    return steps


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
            selected, _, _ = scope.select_checks(
                ["contribs/base/evennia_links/models.py"], self.root
            )
        self.assertEqual(selected, ["building-partners"])


class SelectJobsTests(unittest.TestCase):
    def select(self, *paths):
        return scope.select_checks(list(paths))[0]

    def test_top_level_docs_and_lint_only_files_select_no_partner_jobs(self):
        self.assertEqual(
            self.select(
                "README.md",
                "CONTRIBUTING.md",
                "scripts/file_issue.py",
                "scripts/test_ci_scope.py",
                "scripts/check_command_syntax.py",
                "scripts/test_check_command_syntax.py",
                "scripts/command_syntax_allowlist.txt",
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
        self.assertEqual(
            self.select("scripts/ci_run_boards_notices_upgrade.py"), ["notices-sources"]
        )

    def test_plots_upgrade_runner_selects_notices_sources(self):
        self.assertEqual(
            self.select("scripts/ci_run_plots_notices_upgrade.py"), ["notices-sources"]
        )

    def test_xp_upgrade_runner_selects_notices_sources(self):
        self.assertEqual(self.select("scripts/ci_run_xp_notices_upgrade.py"), ["notices-sources"])
        self.assertEqual(
            self.select("scripts/ci_run_resources_notices_upgrade.py"), ["notices-sources"]
        )

    def test_economy_upgrade_runner_selects_economy_partners(self):
        self.assertEqual(
            self.select("scripts/ci_run_economy_notices_upgrade.py"), ["economy-partners"]
        )
        self.assertIn("economy-partners", self.select("example_game/server/conf/settings.py"))

    def test_social_page_upgrade_runner_selects_notices_sources(self):
        self.assertEqual(
            self.select("scripts/ci_run_social_notices_upgrade.py"), ["notices-sources"]
        )

    def test_notice_runners_select_every_job_that_runs_them(self):
        for path in (
            "scripts/ci_run_resources_tests.py",
            "scripts/ci_resources_partner_tests.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.select(path), ["notices-sources", "resources-partners"])
        for path in ("scripts/ci_run_notices_tests.py", "scripts/ci_notices_partner_tests.py"):
            with self.subTest(path=path):
                self.assertEqual(self.select(path), ["notices-partners", "notices-sources"])
        self.assertEqual(
            self.select("scripts/ci_run_notices_upgrade.py"),
            ["notices-sources", "economy-partners"],
        )

    def test_example_game_selects_the_jobs_that_copy_it(self):
        self.assertEqual(
            set(self.select("example_game/web/templates/website/guides/page.html")),
            {
                "lore-items-partners",
                "crafting-partners",
                "sandbox",
                "rp-sandbox",
                "live-playtest",
            },
        )
        self.assertIn(
            "calendar-partners",
            self.select("example_game/web/templates/rest_framework/api.html"),
        )
        # The upgrades run the current settings on the base commit's game.
        settings = self.select("example_game/server/conf/settings.py")
        self.assertIn("notices-sources", settings)
        self.assertIn("economy-partners", settings)
        self.assertNotIn("notices-partners", settings)

    def test_a_leaf_contrib_selects_its_family_and_the_whole_game_jobs(self):
        self.assertEqual(
            self.select("contribs/game_systems/evennia_boards/tests.py"),
            [
                "notices-partners",
                "notices-sources",
                "sandbox",
                "live-playtest",
                "moderation-partners",
                "boards-partners",
            ],
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


class NoticeUpgradeSelectionTests(unittest.TestCase):
    def select(self, *paths):
        jobs, upgrades, _ = scope.select_checks(list(paths))
        if upgrades:
            self.assertIn("notices-sources", jobs)
        return upgrades

    def test_source_change_selects_its_populated_upgrade(self):
        self.assertEqual(self.select("contribs/game_systems/evennia_social/notices.py"), ["social"])

    def test_migration_selects_its_source_and_the_pre_foundation_fixture(self):
        self.assertEqual(
            self.select("contribs/game_systems/evennia_calendar/migrations/0010_notice.py"),
            ["calendar", "pre-foundation"],
        )

    def test_dependency_changes_select_affected_sources(self):
        self.assertEqual(self.select("contribs/game_systems/evennia_posing/signals.py"), ["social"])
        self.assertEqual(
            self.select("contribs/game_systems/evennia_plots/models.py"),
            ["resources", "plots", "lore", "pre-foundation"],
        )

    def test_runner_and_fixture_select_the_profiles_that_read_them(self):
        self.assertEqual(self.select("scripts/ci_run_lore_notices_upgrade.py"), ["lore"])
        self.assertEqual(self.select("scripts/ci_notices_partner_tests.py"), ["pre-foundation"])

    def test_unrelated_contrib_runs_both_inbox_jobs_without_populated_upgrades(self):
        jobs, upgrades, _ = scope.select_checks(["contribs/rpg/evennia_rp_combat/rounds.py"])
        self.assertIn("notices-partners", jobs)
        self.assertIn("notices-sources", jobs)
        self.assertEqual(upgrades, [])

    def test_shared_or_unclassified_changes_run_every_upgrade(self):
        for path in (
            "contribs/base_systems/evennia_links/notices.py",
            "contribs/game_systems/evennia_notices/services.py",
            "contribs/game_systems/evennia_social/integrations/ignoring.py",
            "contribs/game_systems/evennia_unknown/models.py",
            "example_game/server/conf/settings.py",
            "scripts/ci_install_contribs.py",
            "scripts/ci_profile.py",
            "scripts/ci_run_notices_upgrade.py",
            ".github/workflows/ci.yml",
            "requirements.txt",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.select(path), list(scope.NOTICE_UPGRADES))

    def test_every_upgrade_input_selects_the_job_that_runs_upgrades(self):
        paths = [
            *scope.SHARED_NOTICE_UPGRADE_PATHS,
            *(path for _, reads in scope.NOTICE_UPGRADES.values() for path in reads),
        ]
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path):
                jobs, upgrades, _ = scope.select_checks([path])
                self.assertTrue(upgrades)
                self.assertIn("notices-sources", jobs)
                # An input that went unclassified would pass only through the
                # select-everything fallback.
                self.assertNotEqual(jobs, list(scope.JOBS))


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

    def test_partner_jobs_wait_only_for_scope(self):
        # Chaining one partner job after another puts them end to end on the
        # run's critical path (#235).
        for name, block in workflow_jobs().items():
            if name in ALWAYS_RUN:
                continue
            with self.subTest(job=name):
                self.assertRegex(block, r"(?m)^    needs: scope$")

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

    def test_populated_upgrade_steps_are_gated_on_their_profile(self):
        jobs = workflow_jobs()
        labels = set(scope.partner_graph(scope.REPO_ROOT / "contribs"))
        steps = jobs["notices-sources"].split("\n      - name: Populated ")[1:]
        self.assertEqual(len(steps), len(scope.NOTICE_UPGRADES))
        for (name, (sources, (runner, *_))), step in zip(
            scope.NOTICE_UPGRADES.items(), steps, strict=True
        ):
            with self.subTest(name=name):
                self.assertLessEqual(sources, labels)
                self.assertIn(
                    f"contains(fromJSON(needs.scope.outputs.notice_upgrades), '{name}')", step
                )
                self.assertIn(f"python {runner} {{game}}", step)
        self.assertIn("notice_upgrades: ${{ steps.select.outputs.notice_upgrades }}", jobs["scope"])
        self.assertNotIn("notice_upgrades", jobs["notices-partners"])

    def test_only_nightly_uses_the_broad_host_suites(self):
        jobs = workflow_jobs()
        block = jobs["notices-partners"]
        self.assertIn("github.event_name == 'schedule' && 'broad' || 'focused'", block)
        self.assertEqual(block.count('--coverage "$NOTICE_TEST_COVERAGE"'), 3)
        self.assertNotIn("--coverage", jobs["notices-sources"])
        self.assertNotIn("NOTICE_TEST_COVERAGE", jobs["notices-sources"])

    def test_notice_host_profiles_are_matrix_entries(self):
        # An ungated step would run all three profiles in every entry.
        block = workflow_jobs()["notices-partners"]
        self.assertIn("fail-fast: false", block)
        matrix = re.search(r"profile: \[(.*)\]", block)
        self.assertIsNotNone(matrix)
        profiles = [value.strip() for value in matrix.group(1).split(",")]
        self.assertEqual(len(profiles), 3)
        steps = [
            step for step in re.split(r"(?m)^      - ", block) if "scripts/ci_profile.py" in step
        ]
        self.assertEqual(len(steps), len(profiles))
        for profile, step in zip(profiles, steps, strict=True):
            with self.subTest(profile=profile):
                self.assertIn(f"matrix.profile == '{profile}'", step)

    def test_source_steps_run_without_an_upgrade_selection(self):
        jobs = workflow_jobs()
        block = jobs["notices-sources"]
        # A list, not a dict keyed by name: a duplicated name would hide every
        # step with that name but the last (#312).
        steps = [
            (name, step)
            for name, step in workflow_steps(block)
            if "scripts/ci_profile.py" in step and not name.startswith("Populated ")
        ]
        # Adding or removing a source is a deliberate edit here too.
        self.assertEqual(
            [name for name, _ in steps],
            [
                "Minimal independent inbox",
                "Minimal independent Boards source",
                "Minimal independent Calendar source",
                "Minimal independent Lore source",
                "Minimal independent Moderation source",
                "Minimal independent Social source",
                "Minimal independent Plots source",
                "Minimal independent XP source",
                "Resources Inbox with Plots physically absent",
            ],
        )
        for index, (name, step) in enumerate(steps):
            with self.subTest(step=name, index=index):
                conditions = re.findall(r"(?m)^        if: (.*)$", step)
                self.assertEqual(conditions, ["${{ !cancelled() }}"])
                self.assertNotIn("notice_upgrades", step)
        # Only the upgrades archive base commits and need the full history.
        self.assertIn("fetch-depth: 0", block)
        self.assertNotIn("fetch-depth", jobs["notices-partners"])

    def test_grouped_profiles_run_in_exactly_one_group(self):
        # building-partners and economy-partners split their profiles into
        # matrix groups (#249, #313). An ungated profile runs in every group,
        # one gated on two groups runs twice, and one gated on an unknown
        # group never runs.
        jobs = workflow_jobs()
        grouped = {}
        for job, block in jobs.items():
            matrix = re.search(r"(?m)^        group: \[(.*)\]$", block)
            if matrix:
                groups = [value.strip() for value in matrix.group(1).split(",")]
                grouped[job] = (groups, block)
        self.assertLessEqual({"building-partners", "economy-partners"}, set(grouped))
        # A job gated on matrix.group but missed above (a block-style list, or a
        # comment after the list) would go unchecked.
        self.assertEqual(
            {job for job, block in jobs.items() if "matrix.group" in block}, set(grouped)
        )
        for job, (groups, block) in grouped.items():
            profiles = [
                (name, step)
                for name, step in workflow_steps(block)
                if "scripts/ci_profile.py" in step
            ]
            used = []
            for name, step in profiles:
                with self.subTest(job=job, step=name):
                    conditions = re.findall(r"(?m)^        if: (.*)$", step)
                    self.assertEqual(len(conditions), 1)
                    gate = re.fullmatch(
                        r"\$\{\{ !cancelled\(\) && matrix\.group == '(\w+)' \}\}", conditions[0]
                    )
                    self.assertIsNotNone(gate, conditions[0])
                    self.assertIn(gate.group(1), groups)
                    used.append(gate.group(1))
            with self.subTest(job=job):
                self.assertIn("fail-fast: false", block)
                self.assertEqual(len(groups), len(set(groups)))
                self.assertEqual(set(used), set(groups))  # no group is empty

    def test_every_script_a_job_runs_selects_that_job(self):
        # A change to a runner must select the job that runs it (#301).
        jobs = workflow_jobs()
        checked = 0
        for name in scope.JOBS:
            block = jobs[name]
            scripts = job_scripts(block)
            code = "\n".join(
                line for line in block.splitlines() if not line.strip().startswith("#")
            )
            with self.subTest(job=name):
                self.assertTrue(scripts)
                # A script run in a form job_scripts doesn't see would go unchecked.
                self.assertLessEqual(set(re.findall(r"scripts/[\w/.-]+\.py", code)), scripts)
                for path in sorted(scripts):
                    self.assertTrue((scope.REPO_ROOT / path).is_file(), path)
                    self.assertIn(name, scope.select_checks([path])[0], path)
                    checked += 1
        self.assertTrue(scope.JOBS)
        self.assertTrue(checked)

    def test_modules_a_runner_copies_select_its_jobs(self):
        # Runners copy their fixture module into the game with with_name().
        # Only those copies are followed: ci_run_partner_tests.py copies
        # ci_partner_tests.py or ci_building_partner_tests.py depending on its
        # mode, so following its REPO_ROOT copies would wrongly demand that a
        # calendar fixture select building-partners.
        jobs = workflow_jobs()
        pairs = set()
        for name in scope.JOBS:
            for script in job_scripts(jobs[name]):
                source = (scope.REPO_ROOT / script).read_text(encoding="utf-8")
                for module in re.findall(r'with_name\("(\w+\.py)"\)', source):
                    pairs.add((name, f"scripts/{module}"))
        self.assertTrue(pairs)
        for name, path in sorted(pairs):
            with self.subTest(job=name, module=path):
                self.assertIn(name, scope.select_checks([path])[0])


class CommandLineTests(unittest.TestCase):
    def output(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(scope.main(argv), 0)
        outputs = dict(line.split("=", 1) for line in out.getvalue().splitlines())
        return {key: json.loads(value) for key, value in outputs.items()}

    def test_full_runs_select_every_job(self):
        self.assertEqual(
            self.output(["--all"]),
            {"jobs": list(scope.JOBS), "notice_upgrades": list(scope.NOTICE_UPGRADES)},
        )

    def test_paths_print_github_output_lines(self):
        self.assertEqual(
            self.output(["--paths", "scripts/ci_run_boards_notices_upgrade.py"]),
            {"jobs": ["notices-sources"], "notice_upgrades": ["boards"]},
        )

    def test_diff_lists_both_sides_of_a_rename(self):
        completed = subprocess.CompletedProcess([], 0, stdout="README.md\n")
        with patch.object(scope.subprocess, "run", return_value=completed) as run:
            self.assertEqual(
                self.output(["--diff", "HEAD^1", "HEAD"]), {"jobs": [], "notice_upgrades": []}
            )
        self.assertIn("--no-renames", run.call_args.args[0])
        self.assertEqual(run.call_args.args[0][-2:], ["HEAD^1", "HEAD"])


if __name__ == "__main__":
    unittest.main()
