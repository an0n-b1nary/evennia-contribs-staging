# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real editor restoration with nonpersistent state discarded."""

from evennia_links.testing import EditorPersistenceMixin
from evennia_social.commands.finger import CmdFinger
from evennia_social.tests.base import SocialCommandTestCase


class SocialEditorPersistence(EditorPersistenceMixin, SocialCommandTestCase):
    def test_bio_survives_reload(self):
        self.call(CmdFinger(), "/edit")
        editor = self.reload_editor(self.char1)
        self.save_and_quit_editor(self.char1, editor)
        self.char1.attributes.reset_cache()
        self.assertEqual(self.char1.profile_bio, editor._buffer)
