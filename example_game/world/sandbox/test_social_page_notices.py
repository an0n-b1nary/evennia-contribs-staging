# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real Social page command, puppet signal, and private Inbox projection."""

from importlib import import_module
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings
from evennia.comms.models import Msg
from evennia.utils.create import create_account, create_message, create_object
from evennia.utils.test_resources import EvenniaCommandTest
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_links.notices import NoticeContext, RouteResult
from evennia_notices import views
from evennia_notices.commands import CmdNotices
from evennia_notices.models import DeliveryReceipt
from evennia_notices.services import mutate, project
from evennia_social import notices as social_notices
from evennia_social.commands.messaging import CmdPage
from evennia_social.models import PageDelivery
from world.sandbox.notices_seed import emit_social_demo_notice


@override_settings(ROOT_URLCONF="web.urls")
class SocialPageNoticeSeams(EvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)

    def request(self, account, character=None):
        request = RequestFactory().get("/notices/?source=social-pages")
        request.user = account
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        if character is not None:
            request.session["puppet"] = character.pk
        return request

    def test_web_command_scope_and_page_history(self):
        self.char1.locks.add(f"puppet:pid({self.account.pk})")
        if self.session.get_puppet() is not None:
            self.account.unpuppet_object(self.session)
        with self.captureOnCommitCallbacks(execute=True):
            self.call(CmdPage(), f"{self.char1.key}=Private source conversation", caller=self.char2)
        row = PageDelivery.objects.get(character=self.char1)
        self.assertEqual(row.state, "inbox")
        # A pre-upgrade page is prepared only by the real puppet signal.
        create_message(
            self.char2,
            "Legacy private conversation",
            receivers=[self.char1],
            locks=f"read:id({self.char1.pk})",
            tags=[("page", "comms")],
        )
        self.assertEqual(DeliveryReceipt.objects.filter(source="social-pages").count(), 1)
        self.account.puppet_object(self.session, self.char1)
        self.assertEqual(self.session.get_puppet(), self.char1)
        self.assertEqual(DeliveryReceipt.objects.filter(source="social-pages").count(), 2)

        copy = "You received a page while offline."
        output = self.call(CmdNotices(), "", caller=self.char1)
        self.assertIn(copy, output)
        self.assertNotIn("Private source conversation", output)
        selected = views.inbox(self.request(self.account, self.char1)).render()
        self.assertContains(selected, copy)
        self.assertNotContains(selected, "Private source conversation")
        self.assertContains(views.preferences(self.request(self.account)).render(), "Social pages")

        alt = create_object(Character, key="Other Selected Character")
        self.account.characters.add(alt)
        for account, character in (
            (self.account, None),
            (self.account, alt),
            (self.account2, self.char1),
        ):
            self.assertNotContains(views.inbox(self.request(account, character)).render(), copy)
        self.assertEqual(views.inbox(self.request(AnonymousUser())).status_code, 302)

        context = NoticeContext(self.account, self.char1, self.session)
        for item in project(context, source="social-pages"):
            detail = views.detail(self.request(self.account, self.char1), item.notice.public_ref)
            self.assertContains(detail.render(), "page/last")
            mutate(context, item.notice.public_ref, "read")
            mutate(context, item.notice.public_ref, "clear")
        self.assertEqual(project(context, source="social-pages"), [])
        history = self.call(CmdPage(), "/last", caller=self.char1)
        self.assertIn("Private source conversation", history)
        self.assertIn("Legacy private conversation", history)
        self.assertIsNone(self.char1.last_page_seen)

    def test_guest_live_reminder_has_no_persistent_state(self):
        guest = create_account(
            "SandboxGuestFixture", None, None, typeclass="evennia.accounts.accounts.DefaultGuest"
        )
        self.char1.account = guest
        self.char1.tags.add("character", category="guest")
        guest_session = Mock()
        guest_session.get_account.return_value = guest
        guest_session.get_puppet.return_value = self.char1
        create_message(
            self.char2,
            "Guest source conversation",
            receivers=[self.char1],
            locks=f"read:id({self.char1.pk})",
            tags=[("page", "comms")],
        )
        with (
            patch(
                "evennia.server.sessionhandler.SESSIONS.get_sessions", return_value=[guest_session]
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.char1._notify_unread_pages()
            self.char1._notify_unread_pages()
        guest_session.msg.assert_called_once()
        self.assertIn("You have 1 unread page", guest_session.msg.call_args.args[0])
        self.assertFalse(PageDelivery.objects.exists())
        self.assertFalse(DeliveryReceipt.objects.filter(source="social-pages").exists())
        self.assertIsNone(self.char1.last_page_seen)

    def test_social_notice_example_is_private_and_idempotent(self):
        session = Mock()
        session.get_account.return_value = self.account
        session.get_puppet.return_value = self.char1
        own_page = create_message(
            self.char2,
            "[Sandbox example]",
            receivers=[self.char1],
            locks=f"read:id({self.char1.pk})",
            tags=[("page", "comms")],
        )
        session_list = "evennia.server.sessionhandler.SESSIONS.get_sessions"
        with patch(session_list, return_value=[session]) as sessions:
            with self.assertRaises(ValueError):
                emit_social_demo_notice(self.account, self.char2, session=session)
            with (
                patch.object(social_notices, "transfer", return_value=RouteResult("retry")),
                self.captureOnCommitCallbacks(execute=True),
            ):
                first = emit_social_demo_notice(self.account, self.char1, session=session)
            self.assertFalse(DeliveryReceipt.objects.filter(source="social-pages").exists())
            self.assertEqual(PageDelivery.objects.get(message_id=first).state, "pending")
            with self.captureOnCommitCallbacks(execute=True):
                second = emit_social_demo_notice(self.account, self.char1, session=session)
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(
                    emit_social_demo_notice(self.account, self.char1, session=session), first
                )
            sessions.return_value = []
            with self.assertRaises(ValueError):
                emit_social_demo_notice(self.account, self.char1, session=session)
            sessions.return_value = [session]
            session.get_puppet.return_value = self.char2
            with self.assertRaises(ValueError):
                emit_social_demo_notice(self.account, self.char1, session=session)
        self.assertEqual(first, second)
        self.assertNotEqual(first, own_page.pk)
        self.assertEqual(Msg.objects.count(), 2)
        self.assertEqual(Msg.objects.get(pk=own_page.pk).db_message, "[Sandbox example]")
        self.assertFalse(PageDelivery.objects.filter(message=own_page).exists())
        self.assertEqual(DeliveryReceipt.objects.filter(source="social-pages").count(), 1)
        self.assertFalse(project(NoticeContext(self.account2, self.char2), source="social-pages"))
        session.msg.assert_not_called()
