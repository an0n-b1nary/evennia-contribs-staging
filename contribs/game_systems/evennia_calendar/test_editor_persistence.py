# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real editor restoration with nonpersistent state discarded."""

from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_calendar.commands import CmdCalendar
from evennia_calendar.models import CalendarEvent
from evennia_links.testing import EditorPersistenceMixin


class CalendarEditorPersistence(EditorPersistenceMixin, EvenniaCommandTest):
    def test_creation_survives_reload_including_saved_description(self):
        when = (timezone.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
        self.call(CmdCalendar(), f"/create A gathering={when}")
        editor = self.reload_editor(self.char1)
        # Calendar creates on quit, so its staged description must also persist
        # if the player saves before a second restart.
        editor.save_buffer()
        self.assertFalse(editor._unsaved)
        editor = self.reload_editor(self.char1, editor._buffer)
        self.save_and_quit_editor(self.char1, editor, "calendar_editor_context")
        event = CalendarEvent.objects.get(title="A gathering")
        self.assertEqual(event.description, editor._buffer)
        self.assertEqual(event.creator_id, self.char1.pk)

    def test_existing_event_survives_reload(self):
        event = CalendarEvent.create_event(
            creator=self.char1, title="Original", scheduled_time=timezone.now() + timedelta(days=7)
        )
        self.call(CmdCalendar(), f"/edit {event.pk}")
        editor = self.reload_editor(self.char1)
        self.save_and_quit_editor(self.char1, editor, "calendar_editor_context")
        event.refresh_from_db()
        self.assertEqual(event.description, editor._buffer)

    def test_deleted_event_refuses_save(self):
        event = CalendarEvent.create_event(
            creator=self.char1, title="Original", scheduled_time=timezone.now() + timedelta(days=7)
        )
        self.call(CmdCalendar(), f"/edit {event.pk}")
        editor = self.reload_editor(self.char1)
        event.delete()
        with patch.object(self.char1, "msg") as msg:
            self.assertFalse(editor._savefunc(self.char1, editor._buffer))
        self.assertIn("no longer exists", msg.call_args[0][0])
        editor.quit()
