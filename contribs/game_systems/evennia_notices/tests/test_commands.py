# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Execute commands to verify usable source instructions and strict syntax."""

from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_links.notices import NoticeAction, NoticeContext, NoticeEvent, RenderedNotice
from evennia_notices.commands import CmdNotices
from evennia_notices.models import Notice
from evennia_notices.services import route

from .test_services import SOURCES, Source


@override_settings(LINKS_NOTICE_SOURCES=SOURCES)
class CommandTests(EvenniaCommandTest):
    """Players can discover and use the source command for an outstanding offer."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        route(
            self.account,
            source="test",
            event=NoticeEvent("offer", timezone.now(), action_kind="waitlist_offer"),
            context=NoticeContext(self.account, self.char1),
        )

    def test_read_outputs_safe_action_instructions(self):
        token = Notice.objects.get().public_ref
        with patch.object(
            Source,
            "render",
            return_value=RenderedNotice(
                "Example offer",
                (NoticeAction("Confirm example", command="+sandbox/notice-confirm demo-token"),),
            ),
        ):
            output = self.call(CmdNotices(), f"/read {token}")
        self.assertIn("+sandbox/notice-confirm demo-token", output)

    def test_pending_section_and_unknown_or_stacked_switches(self):
        output = self.call(CmdNotices(), "")
        self.assertIn("Awaiting your decision", output)
        self.assertIn("Routine alerts", output)
        for args in ("/unknown", "/read/clear missing"):
            self.assertIn("usage", self.call(CmdNotices(), args).lower())
