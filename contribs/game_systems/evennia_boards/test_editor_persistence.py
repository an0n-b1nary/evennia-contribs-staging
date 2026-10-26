# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real editor restoration with nonpersistent state discarded."""

from unittest.mock import patch

from evennia.utils.test_resources import EvenniaCommandTest

from evennia_boards.commands import CmdBoard
from evennia_boards.models import Board, Post, PostVersion
from evennia_links.testing import EditorPersistenceMixin


class BoardsEditorPersistence(EditorPersistenceMixin, EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.board = Board.objects.create(name="General")
        self.post = Post.create_post(
            board=self.board, author=self.char1, title="Original", content="Old"
        )

    def test_post_reply_and_edit_survive_reload(self):
        for mode, args in (
            ("post", "/post General=New title"),
            ("reply", f"/reply General/{self.post.post_number}"),
            ("edit", f"/edit General/{self.post.post_number}"),
        ):
            with self.subTest(mode=mode):
                self.call(CmdBoard(), args)
                text = f"Restored {mode} text"
                editor = self.reload_editor(self.char1, text)
                self.save_and_quit_editor(self.char1, editor, "boards_editor_context")
                saved = Post.all_objects.get(content=text)
                self.assertEqual(saved.board_id, self.board.pk)
                if mode == "post":
                    self.assertEqual(saved.title, "New title")
                elif mode == "reply":
                    self.assertEqual(saved.parent_post_id, self.post.pk)
                else:
                    self.assertEqual(saved.pk, self.post.pk)
                    self.assertEqual(PostVersion.objects.get(parent=saved).content, "Old")

    def test_deleted_targets_refuse_save(self):
        for mode in ("post", "reply", "edit"):
            with self.subTest(mode=mode):
                board = Board.objects.create(name=f"Board {mode}")
                post = Post.create_post(
                    board=board, author=self.char1, title="Target", content="Old"
                )
                args = (
                    f"/post {board.name}=Draft"
                    if mode == "post"
                    else f"/{mode} {board.name}/{post.post_number}"
                )
                self.call(CmdBoard(), args)
                editor = self.reload_editor(self.char1)
                if mode == "post":
                    board.delete()
                else:
                    post.delete()
                with patch.object(self.char1, "msg") as msg:
                    self.assertFalse(editor._savefunc(self.char1, editor._buffer))
                self.assertIn("no longer exists", msg.call_args[0][0])
                editor.quit()
                self.assertFalse(self.char1.attributes.has("boards_editor_context"))
