# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Run every editor's persistence contract under the fully composed host."""

import ast
from pathlib import Path

from django.test import SimpleTestCase
from evennia_boards import test_editor_persistence as boards
from evennia_calendar import test_editor_persistence as calendar
from evennia_jobs import test_editor_persistence as jobs
from evennia_lore import test_editor_persistence as lore
from evennia_plots import test_editor_persistence as plots
from evennia_scenes import test_editor_persistence as scenes
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_links import test_editor_persistence as links
from evennia_regions import test_editor_persistence as regions
from evennia_social.tests import test_editor_persistence as social


class HostTypeclasses:
    character_typeclass = Character
    room_typeclass = Room


class LinksEditors(HostTypeclasses, links.LinksEditorPersistence):
    pass


class BoardsEditors(HostTypeclasses, boards.BoardsEditorPersistence):
    pass


class CalendarEditors(HostTypeclasses, calendar.CalendarEditorPersistence):
    pass


class JobsEditors(HostTypeclasses, jobs.JobsEditorPersistence):
    pass


class LoreEditors(HostTypeclasses, lore.LoreEditorPersistence):
    pass


class PlotsEditors(HostTypeclasses, plots.PlotsEditorPersistence):
    pass


class RegionsEditors(HostTypeclasses, regions.RegionsEditorPersistence):
    pass


class ScenesEditors(HostTypeclasses, scenes.ScenesEditorPersistence):
    pass


class SocialEditors(HostTypeclasses, social.SocialEditorPersistence):
    pass


class EditorInventory(SimpleTestCase):
    def test_every_editor_site_has_a_reload_and_pickle_contract(self):
        # Keep this inventory paired with the command-opening contracts above.
        # A newly added editor needs a real reload case, even if it already
        # passes persistent=True and its callbacks look importable.
        expected = {
            ("evennia_links/editing.py", "EditingMixin.start_edit"),
            ("evennia_links/editing.py", "EditingMixin.start_new_edit"),
            ("evennia_boards/commands.py", "CmdBoard._post"),
            ("evennia_boards/commands.py", "CmdBoard._reply"),
            ("evennia_boards/commands.py", "CmdBoard._edit"),
            ("evennia_calendar/commands.py", "CmdCalendar._create"),
            ("evennia_calendar/commands.py", "CmdCalendar._edit"),
            ("evennia_jobs/commands.py", "_open_editor"),
            ("evennia_jobs/request_commands.py", "handle_request"),
            ("evennia_lore/commands.py", "CmdLore._do_layer_text"),
            ("evennia_plots/commands.py", "CmdPlot._do_update"),
            ("evennia_plots/commands.py", "CmdPlot._do_update_edit"),
            ("evennia_plots/commands.py", "CmdArc._do_update"),
            ("evennia_plots/commands.py", "CmdArc._do_update_edit"),
            ("evennia_scenes/commands.py", "CmdScene._desc"),
            ("evennia_social/commands/finger.py", "CmdFinger._do_edit"),
        }
        found = set()
        contribs_root = Path(links.__file__).resolve().parents[2]
        for path in contribs_root.rglob("*.py"):
            tree = ast.parse(path.read_text())
            parents = {
                child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
            }
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "EvEditor"
                ):
                    continue
                scope = []
                parent = node
                while parent in parents:
                    parent = parents[parent]
                    if isinstance(parent, (ast.ClassDef, ast.FunctionDef)):
                        scope.append(parent.name)
                relative = "/".join(path.relative_to(contribs_root).parts[1:])
                site = (relative, ".".join(reversed(scope)))
                found.add(site)
                options = {keyword.arg: keyword.value for keyword in node.keywords}
                with self.subTest(site=site):
                    self.assertIsInstance(options.get("persistent"), ast.Constant)
                    self.assertIs(options["persistent"].value, True)
                    for callback in ("loadfunc", "savefunc", "quitfunc"):
                        self.assertIsInstance(options.get(callback), ast.Name)
        self.assertEqual(found, expected)
