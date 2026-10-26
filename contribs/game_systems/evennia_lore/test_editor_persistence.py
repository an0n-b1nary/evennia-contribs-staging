# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real editor restoration with nonpersistent state discarded."""

from unittest.mock import patch

from evennia.utils.test_resources import EvenniaCommandTest

from evennia_links.testing import EditorPersistenceMixin
from evennia_lore.commands import CmdLore
from evennia_lore.models import LoreEntry, LoreVersion


class LoreEditorPersistence(EditorPersistenceMixin, EvenniaCommandTest):
    def test_submission_survives_reload_and_keeps_title(self):
        self.call(CmdLore(), "/submit A coastal legend")
        editor = self.reload_editor(self.char1)
        self.save_and_quit_editor(self.char1, editor, "links_editing_context")
        self.assertEqual(LoreEntry.objects.get(title="A coastal legend").body, editor._buffer)

    def test_body_and_both_note_layers_survive_reload(self):
        entry = LoreEntry.create_entry("A mystery", self.char1, body="Original lore", kind="rumor")
        for switch, field, context_key in (
            ("edit", "body", "links_editing_context"),
            ("ooc", "ooc_notes", "lore_layer_editor"),
            ("seal", "sealed_notes", "lore_layer_editor"),
        ):
            with self.subTest(field=field):
                self.call(CmdLore(), f"/{switch} #{entry.entry_number}")
                editor = self.reload_editor(self.char1, f"Restored {field}")
                self.save_and_quit_editor(self.char1, editor, context_key)
                entry.refresh_from_db()
                self.assertEqual(getattr(entry, field), editor._buffer)
        self.assertEqual(LoreVersion.objects.get(parent=entry).content, "Original lore")

    def test_deleted_entry_refuses_note_save(self):
        entry = LoreEntry.create_entry("A mystery", self.char1, body="Old")
        self.call(CmdLore(), f"/ooc #{entry.entry_number}")
        editor = self.reload_editor(self.char1)
        entry.delete()
        with patch.object(self.char1, "msg") as msg:
            self.assertFalse(editor._savefunc(self.char1, editor._buffer))
        self.assertIn("no longer exists", msg.call_args[0][0])
        editor.quit()

    def test_quitting_submission_discards_title(self):
        self.call(CmdLore(), "/submit Discard me")
        editor = self.reload_editor(self.char1)
        editor.quit()
        self.assertFalse(self.char1.attributes.has("links_editing_context"))
        self.assertFalse(LoreEntry.objects.filter(title="Discard me").exists())
