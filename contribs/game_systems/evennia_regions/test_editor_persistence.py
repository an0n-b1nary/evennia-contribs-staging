# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real editor restoration with nonpersistent state discarded."""

from evennia.utils.test_resources import EvenniaCommandTest

from evennia_links.testing import EditorPersistenceMixin
from evennia_regions.commands import CmdRegion
from evennia_regions.models import Region


class RegionsEditorPersistence(EditorPersistenceMixin, EvenniaCommandTest):
    def test_region_description_survives_reload(self):
        region = Region.create_region("The coast", self.char1)
        self.call(CmdRegion(), "/edit The coast")
        editor = self.reload_editor(self.char1)
        self.save_and_quit_editor(self.char1, editor, "links_editing_context")
        region.refresh_from_db()
        self.assertEqual(region.description, editor._buffer)
