# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real editor restoration with nonpersistent state discarded."""

from unittest.mock import patch

from evennia.utils.test_resources import EvenniaCommandTest

from evennia_links.testing import EditorPersistenceMixin
from evennia_plots.commands import CmdArc, CmdPlot
from evennia_plots.models import PlotArc, PlotThread, PlotUpdate


class PlotsEditorPersistence(EditorPersistenceMixin, EvenniaCommandTest):
    def parents(self):
        plot = PlotThread.create_thread("The harbour", self.char1)
        plot.activate()
        arc = PlotArc.create_arc("The storm", self.char1)
        return [(CmdPlot, plot, plot.plot_number), (CmdArc, arc, arc.arc_number)]

    def test_new_and_existing_plot_and_arc_updates_survive_reload(self):
        for cls, parent, number in self.parents():
            for mode in ("new", "edit"):
                with self.subTest(command=cls.__name__, mode=mode):
                    if mode == "new":
                        args = f"/update #{number}"
                    else:
                        block = parent.updates.get()
                        args = f"/revise #{number}/{block.block_number}"
                    self.call(cls(), args)
                    editor = self.reload_editor(self.char1, f"{cls.__name__} {mode} restored")
                    self.save_and_quit_editor(self.char1, editor, "plots_update_editor")
                    saved = parent.updates.get()
                    self.assertEqual(saved.content, editor._buffer)
                    if mode == "edit":
                        self.assertEqual(saved.pk, block.pk)

    def test_deleted_parent_or_block_refuses_save(self):
        for cls, parent, number in self.parents():
            for mode in ("edit", "new"):
                with self.subTest(command=cls.__name__, mode=mode):
                    block = PlotUpdate.create_update(parent, self.char1, "Old")
                    args = (
                        f"/update #{number}"
                        if mode == "new"
                        else f"/revise #{number}/{block.block_number}"
                    )
                    self.call(cls(), args)
                    editor = self.reload_editor(self.char1)
                    if mode == "new":
                        parent.delete()
                    else:
                        block.delete()
                    with patch.object(self.char1, "msg") as msg:
                        self.assertFalse(editor._savefunc(self.char1, editor._buffer))
                    self.assertIn("no longer exists", msg.call_args[0][0])
                    editor.quit()
