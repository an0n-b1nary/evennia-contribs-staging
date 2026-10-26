# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real editor restoration with nonpersistent state discarded."""

from unittest.mock import patch

from evennia.utils.test_resources import EvenniaCommandTest

from evennia_links.testing import EditorPersistenceMixin
from evennia_scenes.commands import CmdLog, CmdScene
from evennia_scenes.models import LogEntry, LogEntryVersion, Scene


class ScenesEditorPersistence(EditorPersistenceMixin, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.scene = Scene.objects.create(title="A meeting", room=self.room1, creator=self.char1)

    def test_description_survives_reload(self):
        self.call(CmdScene(), f"/desc {self.scene.scene_number}")
        editor = self.reload_editor(self.char1)
        self.save_and_quit_editor(self.char1, editor, "scenes_description_editor")
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.description, editor._buffer)

    def test_log_edit_survives_reload_with_version(self):
        entry = LogEntry.create_entry(self.scene, self.char1, "Original pose")
        self.call(CmdLog(), f"/edit {entry.pk}")
        editor = self.reload_editor(self.char1)
        self.save_and_quit_editor(self.char1, editor, "links_editing_context")
        entry.refresh_from_db()
        self.assertEqual(entry.content, editor._buffer)
        self.assertEqual(LogEntryVersion.objects.get(parent=entry).content, "Original pose")

    def test_deleted_scene_refuses_save(self):
        self.call(CmdScene(), f"/desc {self.scene.scene_number}")
        editor = self.reload_editor(self.char1)
        self.scene.delete()
        with patch.object(self.char1, "msg") as msg:
            self.assertFalse(editor._savefunc(self.char1, editor._buffer))
        self.assertIn("no longer exists", msg.call_args[0][0])
        editor.quit()
