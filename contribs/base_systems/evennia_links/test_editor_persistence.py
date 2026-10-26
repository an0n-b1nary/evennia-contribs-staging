# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real editor restoration with nonpersistent state discarded."""

from evennia.utils.test_resources import EvenniaTest

from evennia_links.editing import EditingMixin
from evennia_links.testing import EditorPersistenceMixin


def create_content(caller, content):
    caller.db.editor_created_content = content


class LinksEditorPersistence(EditorPersistenceMixin, EvenniaTest):
    def mixin(self):
        command = EditingMixin()
        command.caller = self.char1
        return command

    def test_existing_record_survives_reload(self):
        self.mixin().start_edit(self.char2, "db_key")
        editor = self.reload_editor(self.char1, "A new name")
        self.save_and_quit_editor(self.char1, editor, "links_editing_context")
        self.char2.refresh_from_db()
        self.assertEqual(self.char2.key, "A new name")

    def test_creation_survives_reload_and_quit_discards_context(self):
        self.mixin().start_new_edit(create_content, context={"title": "Draft"})
        editor = self.reload_editor(self.char1)
        self.save_and_quit_editor(self.char1, editor, "links_editing_context")
        self.assertEqual(self.char1.db.editor_created_content, editor._buffer)
        self.mixin().start_new_edit(create_content, context={"title": "Discard"})
        self.char1.ndb._eveditor.quit()
        self.assertFalse(self.char1.attributes.has("links_editing_context"))
