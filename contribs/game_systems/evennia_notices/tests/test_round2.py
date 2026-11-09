# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Traverse every advertised page and retain account scope while playing an NPC."""

import re
from importlib import import_module
from unittest.mock import patch

from django.conf import settings
from django.test import RequestFactory, override_settings
from django.urls import include, path
from django.utils import timezone
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTest
from evennia.web.urls import urlpatterns as evennia_patterns

from evennia_links.notices import Evaluation, NoticeContext, NoticeEvent, authorize_context
from evennia_notices import views
from evennia_notices.commands import CmdNotices
from evennia_notices.listeners import session_summary
from evennia_notices.services import project, route

from .test_services import SOURCES, Source

urlpatterns = [path("notices/", include("evennia_notices.urls")), *evennia_patterns]


@override_settings(ROOT_URLCONF=__name__, LINKS_NOTICE_SOURCES=SOURCES)
class RoundTwoTests(EvenniaCommandTest):
    """One stable continuation must reach decisions interleaved with routine alerts."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.context = NoticeContext(self.account, self.char1)
        self.now = timezone.now()

    def emit(self, key, *, decision=False, recipient=None, **payload):
        return route(
            recipient or self.account,
            source="test",
            context=self.context,
            event=NoticeEvent(
                key,
                self.now,
                payload={"text": key, **payload},
                action_kind="waitlist_offer" if decision else None,
            ),
        )

    def build_examples(self):
        self.emit("hidden-candidate")
        self.emit("deferred-candidate")
        for index in range(3):
            self.emit(f"decision-{index}", decision=True)
            self.emit(f"routine-{index}")

    def evaluations(self, events, context):
        return {
            event.event_id: Evaluation(
                "hidden"
                if event.event_id == "hidden-candidate"
                else "defer"
                if event.event_id == "deferred-candidate"
                else "visible",
                outstanding=bool(event.action_kind),
                reason="context" if event.event_id == "deferred-candidate" else None,
            )
            for event in events
        }

    def page(self, *args, **kwargs):
        return project(*args, **kwargs, page_size=2)

    def test_command_traversal_reaches_every_interleaved_decision(self):
        self.build_examples()
        cursor = None
        seen = set()
        with (
            patch.object(Source, "evaluate", side_effect=self.evaluations),
            patch("evennia_notices.commands.project", side_effect=self.page),
        ):
            for _ in range(10):
                output = self.call(CmdNotices(), f"/next {cursor}" if cursor else "")
                seen.update(re.findall(r"(?:decision|routine)-\d+", output))
                self.assertNotIn("hidden-candidate", output)
                self.assertNotIn("deferred-candidate", output)
                following = re.search(r"Next page: \+notices/next ([a-f0-9]{12})", output)
                if following is None:
                    break
                self.assertNotEqual(cursor, following.group(1))
                cursor = following.group(1)
        self.assertEqual(
            seen, {f"{kind}-{index}" for kind in ("decision", "routine") for index in range(3)}
        )

    def test_rendered_web_traversal_reaches_every_interleaved_decision(self):
        self.build_examples()
        cursor = None
        seen = set()
        with (
            patch.object(Source, "evaluate", side_effect=self.evaluations),
            patch("evennia_notices.views.project", side_effect=self.page),
        ):
            for _ in range(10):
                request = RequestFactory().get("/notices/", {"cursor": cursor} if cursor else {})
                request.user = self.account
                request.session = import_module(settings.SESSION_ENGINE).SessionStore()
                response = views.inbox(request).render()
                content = response.content.decode()
                seen.update(re.findall(r"decision-\d+", content))
                self.assertNotIn("hidden-candidate", content)
                self.assertNotIn("deferred-candidate", content)
                following = re.search(r'href="\?cursor=([a-f0-9]{12})"', content)
                if following is None:
                    break
                self.assertNotEqual(cursor, following.group(1))
                cursor = following.group(1)
        self.assertEqual(seen, {f"decision-{index}" for index in range(3)})

    def test_npc_command_and_summary_show_only_eligible_account_activity(self):
        self.emit("account-safe")
        self.emit("character-dependent-secret", requires_character=True)
        self.emit("other-character-secret", recipient=self.char1)
        npc = create_object(type(self.char1), key="Controlled example NPC", location=self.room1)
        npc.account = self.account
        previous = self.session.puppet
        self.session.puppet = npc
        try:
            output = self.call(CmdNotices(), "", caller=npc)
            self.assertIn("account-safe", output)
            self.assertNotIn("character-dependent-secret", output)
            self.assertNotIn("other-character-secret", output)
            account_output = self.call(CmdNotices(), "", caller=self.account, receiver=self.account)
            self.assertIn("account-safe", account_output)
            self.assertNotIn("character-dependent-secret", account_output)
            self.assertNotIn("other-character-secret", account_output)
            from evennia_links.notices import connected_contexts

            current = [
                context
                for context in connected_contexts(self.account)
                if context.session is self.session
            ]
            self.assertEqual(len(current), 1)
            self.assertIsNone(current[0].character)
            self.session._notice_summaries = {}
            with patch.object(self.session, "msg") as messages:
                session_summary(npc, session=self.session)
            messages.assert_called_once()
            self.assertIn("1 unread alerts", messages.call_args.args[0])
            self.assertTrue(authorize_context(NoticeContext(self.account, session=self.session)))
            self.assertFalse(
                authorize_context(NoticeContext(self.account, self.char1, self.session))
            )
            self.assertFalse(authorize_context(NoticeContext(self.account2, session=self.session)))
        finally:
            self.session.puppet = previous
