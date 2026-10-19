# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Calendar notices under this game's characters and a real puppet."""

from datetime import timedelta
from unittest import mock

from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest
from evennia_calendar.models import RSVP, CalendarEvent, CalendarNotice
from evennia_calendar.scheduler import promote_waitlist
from typeclasses.characters import Character
from typeclasses.rooms import Room


class CalendarNoticeSeams(EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def test_an_offline_player_hears_about_their_new_place_when_they_puppet(self):
        """The notice waits while nobody plays the character, then arrives on a real puppet."""
        event = CalendarEvent.create_event(
            creator=self.char2,
            title="Lantern Walk",
            scheduled_time=timezone.now() + timedelta(days=3),
            participant_cap=1,
        )
        RSVP.objects.create(
            event=event,
            character=self.char1,
            character_name=self.char1.key,
            status=RSVP.Status.WAITLISTED,
            waitlist_position=1,
        )
        self.account.unpuppet_object(self.session)
        self.assertFalse(self.char1.sessions.count())
        promote_waitlist(event, count=1)
        notice = CalendarNotice.objects.get(character=self.char1)
        self.assertIsNone(notice.delivered_at)

        with mock.patch.object(Character, "msg") as msg:
            self.account.puppet_object(self.session, self.char1)
        told = "\n".join(str(call.args[0]) for call in msg.call_args_list if call.args)
        self.assertIn("Lantern Walk", told)
        self.assertIn("you're confirmed", told)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.delivered_at)
