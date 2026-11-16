# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Calendar notices under this game's characters and a real puppet."""

from datetime import timedelta
from unittest import mock

from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_calendar.models import RSVP, CalendarEvent, CalendarNotice
from evennia_calendar.scheduler import promote_waitlist


class CalendarNoticeSeams(EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)

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
        self.assertIsNotNone(notice.delivered_at)
        self.assertEqual(notice.route_state, "inbox")

        with mock.patch.object(Character, "msg") as msg:
            self.account.puppet_object(self.session, self.char1)
        told = "\n".join(str(call.args[0]) for call in msg.call_args_list if call.args)
        self.assertNotIn("Lantern Walk", told)
        from evennia_links.notices import NoticeContext
        from evennia_notices.services import project

        projected = project(NoticeContext(self.account, self.char1))
        self.assertIn("Lantern Walk", projected[0].text)
        self.assertIn("you're confirmed", projected[0].text)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.delivered_at)

    def test_real_calendar_opt_in_is_idempotent_scoped_and_rendered(self):
        from importlib import import_module

        from django.conf import settings
        from django.test import RequestFactory, override_settings

        from evennia_links.notices import NoticeContext
        from evennia_notices import views
        from evennia_notices.services import project
        from world.sandbox.notices_seed import emit_calendar_demo_notices

        # Use this host's actual route tree and selected-character session.
        with override_settings(ROOT_URLCONF="web.urls"):
            emit_calendar_demo_notices(self.account, self.char1)
            emit_calendar_demo_notices(self.account, self.char1)
            self.assertEqual(CalendarNotice.objects.count(), 2)
            self.assertEqual(project(NoticeContext(self.account2, self.char2)), [])
            request = RequestFactory().get("/notices/")
            request.user = self.account
            request.session = import_module(settings.SESSION_ENGINE).SessionStore()
            request.session["puppet"] = self.char1.pk
            response = views.inbox(request).render()
            self.assertContains(response, "Example Calendar selection")
            self.assertContains(response, "Example Calendar invitation")
            request.session["puppet"] = self.char2.pk
            response = views.inbox(request).render()
            self.assertNotContains(response, "Example Calendar selection")

    def test_first_summary_prepares_pending_even_before_calendar_puppet_receiver(self):
        from evennia_links.notices import NoticeContext
        from evennia_notices.listeners import session_summary
        from evennia_notices.services import project

        self.account.puppet_object(self.session, self.char1)
        event = CalendarEvent.objects.create(
            title="Pending Calendar fixture", scheduled_time=timezone.now() + timedelta(days=4)
        )
        rsvp = RSVP.objects.create(
            event=event, character=self.char1, status=RSVP.Status.LOTTERY_SELECTED
        )
        row = CalendarNotice.objects.create(
            rsvp=rsvp, character=self.char1, kind="drawn", status=rsvp.status, message="Legacy draw"
        )
        # Invoke Inbox first, independently of registered signal order.
        with (
            mock.patch.object(self.session, "msg") as message,
            self.captureOnCommitCallbacks(execute=True),
        ):
            session_summary(self.char1, session=self.session)
        row.refresh_from_db()
        self.assertEqual(row.route_state, "inbox")
        self.assertEqual(len(project(NoticeContext(self.account, self.char1))), 1)
        self.assertEqual(message.call_count, 1)
        self.assertIn("Notices:", message.call_args.args[0])
        self.assertNotIn("Pending Calendar fixture", message.call_args.args[0])
        self.assertEqual(
            __import__("evennia_calendar.notices", fromlist=["deliver_pending"]).deliver_pending(
                self.char1
            ),
            0,
        )

    def test_connected_new_lottery_selection_has_one_immediate_hint(self):
        from evennia_calendar import notices

        self.account.puppet_object(self.session, self.char1)
        event = CalendarEvent.objects.create(
            title="Connected selection fixture", scheduled_time=timezone.now() + timedelta(days=4)
        )
        rsvp = RSVP.objects.create(
            event=event, character=self.char1, status=RSVP.Status.LOTTERY_SELECTED
        )
        with (
            mock.patch.object(self.session, "msg") as message,
            self.captureOnCommitCallbacks(execute=True),
        ):
            notices.on_lottery_selected(None, event=event, rsvp=rsvp)
            notices.on_lottery_selected(None, event=event, rsvp=rsvp)
        hints = [
            call.args[0]
            for call in message.call_args_list
            if call.args and "Connected selection fixture" in str(call.args[0])
        ]
        self.assertEqual(len(hints), 1)
