"""Install-order regressions for the CI contrib installer."""

from __future__ import annotations

import contextlib
import io
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import ci_install_contribs as installer
from ci_install_contribs import (
    ContribGraphError,
    discover_contribs,
    install_order,
    normalize_name,
    requirement_name,
)

REPO_CONTRIBS = pathlib.Path(__file__).resolve().parent.parent / "contribs"


class ContribTreeMixin:
    """Builds throwaway `contribs/<category>/<name>/pyproject.toml` trees."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "contribs"

    def tearDown(self):
        self._tmp.cleanup()
        super().tearDown()

    def add(self, category, label, dependencies=(), *, name=None, extras=None):
        path = self.root / category / label
        path.mkdir(parents=True)
        deps = ", ".join(f'"{dep}"' for dep in dependencies)
        body = f'[project]\nname = "{name or label.replace("_", "-")}"\ndependencies = [{deps}]\n'
        if extras:
            body += "\n[project.optional-dependencies]\n"
            for extra, reqs in extras.items():
                body += f"{extra} = [{', '.join(f'{r!r}' for r in reqs)}]\n"
        (path / "pyproject.toml").write_text(body, encoding="utf-8")
        return path

    def order(self):
        return [contrib.label for contrib in install_order(discover_contribs(self.root))]


class RequirementParsingTests(unittest.TestCase):
    def test_names_normalize_per_pep_503(self):
        self.assertEqual(normalize_name("Evennia_RP.Rules"), "evennia-rp-rules")

    def test_specifiers_extras_and_markers_are_stripped(self):
        cases = {
            "evennia-rp-rules>=0.1,<0.2": "evennia-rp-rules",
            "evennia_links[web] >= 0.5": "evennia-links",
            'evennia-xp>=0.1; python_version >= "3.12"': "evennia-xp",
            "evennia": "evennia",
        }
        for requirement, expected in cases.items():
            with self.subTest(requirement=requirement):
                self.assertEqual(requirement_name(requirement), expected)

    def test_unparseable_requirement_raises(self):
        with self.assertRaises(ContribGraphError):
            requirement_name(">=1.0")


class InstallOrderTests(ContribTreeMixin, unittest.TestCase):
    def test_dependency_installs_before_an_alphabetically_earlier_dependent(self):
        # The case that motivated the sort: rp_contest < rp_rules alphabetically.
        self.add("rpg", "evennia_rp_contest", ["evennia>=6.0", "evennia-rp-rules>=0.1,<0.2"])
        self.add("rpg", "evennia_rp_rules", ["evennia>=6.0"])
        self.assertEqual(self.order(), ["evennia_rp_rules", "evennia_rp_contest"])

    def test_transitive_chain_across_categories(self):
        self.add("rpg", "evennia_rp_contest", ["evennia-rp-rules", "evennia-links"])
        self.add("rpg", "evennia_rp_chargen", ["evennia-rp-rules", "evennia-links"])
        self.add("rpg", "evennia_rp_rules", ["evennia"])
        self.add("base_systems", "evennia_links", ["evennia"])
        order = self.order()
        self.assertLess(order.index("evennia_links"), order.index("evennia_rp_chargen"))
        self.assertLess(order.index("evennia_rp_rules"), order.index("evennia_rp_chargen"))
        self.assertLess(order.index("evennia_rp_rules"), order.index("evennia_rp_contest"))

    def test_independent_contribs_keep_path_order(self):
        self.add("utils", "evennia_accessibility")
        self.add("game_systems", "evennia_xp")
        self.add("game_systems", "evennia_boards")
        self.add("base_systems", "evennia_links")
        self.assertEqual(
            self.order(),
            ["evennia_links", "evennia_boards", "evennia_xp", "evennia_accessibility"],
        )

    def test_non_normalized_dependency_spelling_still_orders(self):
        self.add("game_systems", "evennia_boards", ["Evennia_Links>=0.5"])
        self.add("game_systems", "evennia_links", name="evennia.links")
        self.assertEqual(self.order(), ["evennia_links", "evennia_boards"])

    def test_external_dependencies_are_ignored(self):
        self.add("game_systems", "evennia_boards", ["evennia>=6.0", "djangorestframework>=3.14"])
        self.assertEqual(self.order(), ["evennia_boards"])

    def test_optional_dependencies_are_not_ordering_edges(self):
        # Mutual extras would be a cycle if extras counted; they must not.
        self.add("game_systems", "evennia_boards", extras={"xp": ["evennia-xp>=0.1"]})
        self.add("game_systems", "evennia_xp", extras={"boards": ["evennia-boards>=0.1"]})
        self.assertEqual(self.order(), ["evennia_boards", "evennia_xp"])

    def test_directories_without_pyproject_are_skipped(self):
        (self.root / "rpg").mkdir(parents=True)
        (self.root / "rpg" / ".gitkeep").touch()
        (self.root / "rpg" / "scratch").mkdir()
        self.add("utils", "evennia_accessibility")
        self.assertEqual(self.order(), ["evennia_accessibility"])

    def test_cycle_raises_and_names_its_members(self):
        self.add("rpg", "evennia_rp_a", ["evennia-rp-b"])
        self.add("rpg", "evennia_rp_b", ["evennia-rp-a"])
        self.add("rpg", "evennia_rp_c", ["evennia-rp-a"])
        self.add("rpg", "evennia_rp_free")
        with self.assertRaises(ContribGraphError) as caught:
            self.order()
        message = str(caught.exception)
        for name in ("evennia-rp-a", "evennia-rp-b", "evennia-rp-c"):
            self.assertIn(name, message)
        self.assertNotIn("evennia-rp-free", message)

    def test_duplicate_distribution_name_raises(self):
        self.add("rpg", "evennia_rp_rules")
        self.add("utils", "evennia_rp_rules_copy", name="evennia_rp_rules")
        with self.assertRaises(ContribGraphError):
            self.order()


class MainTests(ContribTreeMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.game = pathlib.Path(self._tmp.name) / "ci_game"
        self.settings = self.game / "server" / "conf" / "settings.py"
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text("INSTALLED_APPS = []\n", encoding="utf-8")

    def run_main(self):
        with (
            patch.object(installer, "CONTRIBS_ROOT", self.root),
            patch.object(installer.subprocess, "run") as pip,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            code = installer.main(self.game)
        return code, pip, stderr.getvalue()

    def test_installs_and_registers_in_dependency_order(self):
        self.add("rpg", "evennia_rp_contest", ["evennia-rp-rules"])
        self.add("rpg", "evennia_rp_rules")
        code, pip, _ = self.run_main()
        self.assertEqual(code, 0)
        installed = [pathlib.Path(call.args[0][-1]).name for call in pip.call_args_list]
        self.assertEqual(installed, ["evennia_rp_rules", "evennia_rp_contest"])
        settings = self.settings.read_text(encoding="utf-8")
        self.assertLess(
            settings.index('"evennia_rp_rules"'), settings.index('"evennia_rp_contest"')
        )
        self.assertIn("MD5PasswordHasher", settings)

    def test_cycle_fails_before_installing_anything(self):
        self.add("rpg", "evennia_rp_a", ["evennia-rp-b"])
        self.add("rpg", "evennia_rp_b", ["evennia-rp-a"])
        code, pip, stderr = self.run_main()
        self.assertEqual(code, 1)
        pip.assert_not_called()
        self.assertIn("cycle", stderr)
        self.assertEqual(self.settings.read_text(encoding="utf-8"), "INSTALLED_APPS = []\n")


class RepositoryTreeTests(unittest.TestCase):
    """The real contribs/ tree orders cleanly and honours every local dependency."""

    def test_every_local_dependency_precedes_its_dependent(self):
        order = install_order(discover_contribs(REPO_CONTRIBS))
        position = {contrib.name: index for index, contrib in enumerate(order)}
        self.assertTrue(order, "expected at least one contrib in the repository")
        for contrib in order:
            for dep in contrib.requires & position.keys():
                with self.subTest(contrib=contrib.name, dependency=dep):
                    self.assertLess(position[dep], position[contrib.name])


if __name__ == "__main__":
    unittest.main()
