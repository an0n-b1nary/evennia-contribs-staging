# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Optional source preparation is authorized, ordered and failure isolated."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from evennia.utils.test_resources import EvenniaTest

from evennia_links.notices import NoticeContext
from evennia_notices import listeners


class PreparationTests(EvenniaTest):
    """Preparing one registered source cannot block others or widen scope."""

    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.notice_session = SimpleNamespace(
            get_account=lambda: self.account, get_puppet=lambda: self.char1
        )

    def test_preparation_runs_before_summary_with_old_sources_supported(self):
        calls = []
        source = SimpleNamespace(prepare=lambda context: calls.append(context.character.pk))
        with (
            patch.object(
                listeners, "source_registry", return_value={"old": object(), "new": source}
            ),
            patch(
                "evennia_notices.services.summarize",
                side_effect=lambda context: calls.append("summary"),
            ),
        ):
            listeners.session_summary(None, session=self.notice_session)
        self.assertEqual(calls, [self.char1.pk, "summary"])

    def test_failed_source_does_not_block_other_preparers_or_summary(self):
        failed = SimpleNamespace(prepare=Mock(side_effect=RuntimeError("temporary")))
        succeeding = SimpleNamespace(prepare=Mock())
        with (
            patch.object(
                listeners, "source_registry", return_value={"bad": failed, "good": succeeding}
            ),
            patch("evennia_notices.services.summarize") as summarize,
        ):
            listeners.session_summary(None, session=self.notice_session)
        succeeding.prepare.assert_called_once()
        summarize.assert_called_once()

    def test_invalid_context_never_invokes_source(self):
        source = SimpleNamespace(prepare=Mock())
        with (
            patch.object(listeners, "source_registry", return_value={"source": source}),
            patch.object(
                listeners, "session_context", return_value=NoticeContext(self.account, self.char2)
            ),
            patch("evennia_notices.services.summarize") as summarize,
        ):
            listeners.session_summary(None, session=self.notice_session)
        source.prepare.assert_not_called()
        summarize.assert_not_called()
