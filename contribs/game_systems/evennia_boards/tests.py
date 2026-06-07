# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_boards contrib.

Uses EvenniaTest which provides:
    self.char1 (key="Char"), self.char2 (key="Char2") — both in self.room1
    self.account, self.account2

Run with:
    evennia test evennia_boards --settings test_boards_settings
"""

import unittest
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest

from evennia_boards.models import Board, Post, PostCalendarLink, PostVersion, Subscription

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

try:
    import evennia_xp

    _HAS_XP = True
except ImportError:
    _HAS_XP = False

_XP_GATING = "evennia_xp.gating.resolve_xp_multiplier"


def _make_board(name="General", board_type=Board.BoardType.OOC, order=0):
    return Board.objects.create(name=name, board_type=board_type, order=order)


def _make_ic_board(name="IC Cutscenes", order=99):
    board, _ = Board.objects.get_or_create(
        name=name,
        defaults={"board_type": Board.BoardType.IC, "order": order},
    )
    return board


def _make_ic_post(author, board, *, title="Cutscene", offset_hours=1, window_end=None):
    """Create an IC-board Post offset_hours before window_end."""
    if window_end is None:
        window_end = timezone.now()
    post = Post.all_objects.create(
        board=board,
        post_number=Post.all_objects.filter(board=board).count() + 1,
        title=title,
        content="IC content.",
        author=author,
        author_name=author.key,
    )
    Post.all_objects.filter(pk=post.pk).update(
        created_at=window_end - timedelta(hours=offset_hours)
    )
    post.refresh_from_db()
    return post


# ---------------------------------------------------------------------------
# Board model
# ---------------------------------------------------------------------------


class TestBoardModel(EvenniaTest):
    def test_create_board_defaults(self):
        board = _make_board()
        self.assertEqual(board.name, "General")
        self.assertEqual(board.board_type, Board.BoardType.OOC)
        self.assertFalse(board.is_read_only)
        self.assertIsNotNone(board.created_at)

    def test_board_ordering(self):
        b2 = _make_board("Announcements", order=2)
        b1 = _make_board("Cutscenes", order=1)
        boards = list(Board.objects.all())
        self.assertEqual(boards[0], b1)
        self.assertEqual(boards[1], b2)

    def test_board_str(self):
        board = _make_board()
        self.assertIn("General", str(board))
        self.assertIn("OOC", str(board))

    def test_board_ic_type(self):
        board = _make_board("Cutscenes", board_type=Board.BoardType.IC)
        self.assertEqual(board.board_type, Board.BoardType.IC)

    def test_read_only_flag(self):
        board = Board.objects.create(name="Staff", is_read_only=True, order=5)
        self.assertTrue(board.is_read_only)


# ---------------------------------------------------------------------------
# Post model
# ---------------------------------------------------------------------------


class TestPostModel(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.board = _make_board()

    def test_create_post_starts_at_one(self):
        post = Post.create_post(board=self.board, author=self.char1, title="Hello", content="World")
        self.assertEqual(post.post_number, 1)
        self.assertEqual(post.author, self.char1)
        self.assertEqual(post.author_name, self.char1.key)
        self.assertIsNone(post.parent_post)

    def test_post_number_increments(self):
        p1 = Post.create_post(board=self.board, author=self.char1, title="First", content="A")
        p2 = Post.create_post(board=self.board, author=self.char1, title="Second", content="B")
        self.assertEqual(p1.post_number, 1)
        self.assertEqual(p2.post_number, 2)

    def test_post_numbers_per_board_are_independent(self):
        board2 = _make_board("Announcements")
        Post.create_post(board=self.board, author=self.char1, title="A", content="x")
        Post.create_post(board=self.board, author=self.char1, title="B", content="x")
        p = Post.create_post(board=board2, author=self.char1, title="C", content="x")
        self.assertEqual(p.post_number, 1)

    def test_archived_post_does_not_reset_numbering(self):
        p1 = Post.create_post(board=self.board, author=self.char1, title="A", content="x")
        p1.archive(editor=self.char1)
        p2 = Post.create_post(board=self.board, author=self.char1, title="B", content="x")
        self.assertEqual(p2.post_number, 2)

    def test_default_manager_excludes_archived(self):
        p = Post.create_post(board=self.board, author=self.char1, title="A", content="x")
        p.archive(editor=self.char1)
        self.assertEqual(Post.objects.filter(board=self.board).count(), 0)

    def test_all_objects_includes_archived(self):
        p = Post.create_post(board=self.board, author=self.char1, title="A", content="x")
        p.archive(editor=self.char1)
        self.assertEqual(Post.all_objects.filter(board=self.board).count(), 1)

    def test_create_reply_sets_parent(self):
        parent = Post.create_post(board=self.board, author=self.char1, title="Parent", content="x")
        reply = Post.create_post(
            board=self.board,
            author=self.char2,
            title="Re: Parent",
            content="y",
            parent_post=parent,
        )
        self.assertEqual(reply.parent_post, parent)
        self.assertEqual(reply.post_number, 2)

    def test_post_created_signal_fires(self):
        from evennia_boards.signals import post_created

        received = []

        def handler(sender, post, board, **kwargs):
            received.append((post, board))

        post_created.connect(handler)
        try:
            Post.create_post(board=self.board, author=self.char1, title="X", content="y")
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0][1], self.board)
        finally:
            post_created.disconnect(handler)

    def test_post_str(self):
        p = Post.create_post(board=self.board, author=self.char1, title="Hello", content="x")
        s = str(p)
        self.assertIn("General", s)
        self.assertIn("Hello", s)

    def test_system_post_no_author(self):
        p = Post.create_post(board=self.board, author=None, title="System", content="x")
        self.assertIsNone(p.author)
        self.assertEqual(p.author_name, "System")

    def test_xp_flagged_defaults_false(self):
        p = Post.create_post(board=self.board, author=self.char1, title="A", content="x")
        self.assertFalse(p.xp_flagged)
        self.assertEqual(p.xp_flag_reason, "")


# ---------------------------------------------------------------------------
# Subscription model
# ---------------------------------------------------------------------------


class TestSubscriptionModel(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.board = _make_board()

    def test_create_subscription(self):
        sub = Subscription.objects.create(account=self.account, board=self.board)
        self.assertEqual(sub.account, self.account)
        self.assertEqual(sub.board, self.board)
        self.assertIsNone(sub.last_notified_at)

    def test_unique_together(self):
        from django.db import IntegrityError, transaction

        Subscription.objects.create(account=self.account, board=self.board)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Subscription.objects.create(account=self.account, board=self.board)

    def test_unread_count_no_cutoff_returns_all(self):
        Post.create_post(board=self.board, author=self.char1, title="A", content="x")
        Post.create_post(board=self.board, author=self.char1, title="B", content="x")
        sub = Subscription.objects.create(account=self.account, board=self.board)
        self.assertEqual(sub.unread_count(), 2)

    def test_unread_count_with_cutoff(self):
        Post.create_post(board=self.board, author=self.char1, title="Old", content="x")
        sub = Subscription.objects.create(
            account=self.account, board=self.board, last_notified_at=timezone.now()
        )
        Post.create_post(board=self.board, author=self.char1, title="New", content="x")
        self.assertEqual(sub.unread_count(), 1)

    def test_unread_count_excludes_archived(self):
        p = Post.create_post(board=self.board, author=self.char1, title="A", content="x")
        p.archive(editor=self.char1)
        sub = Subscription.objects.create(account=self.account, board=self.board)
        self.assertEqual(sub.unread_count(), 0)

    def test_related_name_on_account(self):
        Subscription.objects.create(account=self.account, board=self.board)
        self.assertEqual(self.account.evennia_board_subscriptions.count(), 1)

    def test_str(self):
        sub = Subscription.objects.create(account=self.account, board=self.board)
        self.assertIn("General", str(sub))


# ---------------------------------------------------------------------------
# PostVersion model
# ---------------------------------------------------------------------------


class TestPostVersionModel(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.board = _make_board()
        self.post = Post.create_post(
            board=self.board, author=self.char1, title="Draft", content="Original text"
        )

    def test_create_version_increments(self):
        v1 = PostVersion.create_version(
            parent=self.post, content="Original text", editor=self.char1
        )
        v2 = PostVersion.create_version(
            parent=self.post, content="After first edit", editor=self.char1
        )
        self.assertEqual(v1.version_number, 1)
        self.assertEqual(v2.version_number, 2)

    def test_rollback_creates_new_version(self):
        PostVersion.create_version(parent=self.post, content="Original text", editor=self.char1)
        self.post.content = "Edited text"
        self.post.save()
        rollback_v = PostVersion.rollback_to(parent=self.post, version_number=1, editor=self.char2)
        self.assertTrue(rollback_v.is_rollback)
        self.assertEqual(rollback_v.rolled_back_from, 1)
        self.assertEqual(rollback_v.content, "Original text")


# ---------------------------------------------------------------------------
# PostCalendarLink soft-ref
# ---------------------------------------------------------------------------


class TestPostCalendarLink(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.board = _make_board("Events", order=10)
        self.post = Post.create_post(
            board=self.board, author=self.char1, title="Event post", content="come join"
        )

    def test_create_link(self):
        link = PostCalendarLink.objects.create(
            post=self.post,
            event_id=42,
            created_by=self.char1,
            created_by_name=self.char1.key,
        )
        self.assertEqual(link.event_id, 42)
        self.assertEqual(link.post, self.post)

    def test_unique_together(self):
        from django.db import IntegrityError, transaction

        PostCalendarLink.objects.create(
            post=self.post,
            event_id=1,
            created_by=self.char1,
            created_by_name=self.char1.key,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PostCalendarLink.objects.create(
                post=self.post,
                event_id=1,
                created_by=self.char1,
                created_by_name=self.char1.key,
            )

    def test_same_post_different_events(self):
        PostCalendarLink.objects.create(
            post=self.post,
            event_id=1,
            created_by=self.char1,
            created_by_name=self.char1.key,
        )
        PostCalendarLink.objects.create(
            post=self.post,
            event_id=2,
            created_by=self.char1,
            created_by_name=self.char1.key,
        )
        self.assertEqual(self.post.calendar_links.count(), 2)

    def test_str(self):
        link = PostCalendarLink.objects.create(
            post=self.post,
            event_id=99,
            created_by=self.char1,
            created_by_name=self.char1.key,
        )
        s = str(link)
        self.assertIn("99", s)


# ---------------------------------------------------------------------------
# Login notification listener
# ---------------------------------------------------------------------------


class TestLoginNotification(EvenniaTest):
    """Login notification fires from the signal listener."""

    def setUp(self):
        super().setUp()
        self.board = _make_board("News", board_type=Board.BoardType.OOC, order=1)

    def _fire_login_signal(self, account, session=None):
        from evennia.server.signals import SIGNAL_ACCOUNT_POST_LOGIN

        SIGNAL_ACCOUNT_POST_LOGIN.send(sender=account, session=session)

    def test_unread_notification_sent(self):
        Subscription.objects.create(account=self.account, board=self.board)
        Post.all_objects.create(
            board=self.board,
            post_number=1,
            title="Hello",
            content="World.",
            author=self.char1,
            author_name=self.char1.key,
        )
        with patch.object(self.account, "msg") as mock_msg:
            self._fire_login_signal(self.account)
        mock_msg.assert_called_once()
        call_args = mock_msg.call_args[0][0]
        self.assertIn("New board posts", call_args)
        self.assertIn("News", call_args)

    def test_no_notification_when_no_unread(self):
        Subscription.objects.create(
            account=self.account,
            board=self.board,
            last_notified_at=timezone.now(),
        )
        with patch.object(self.account, "msg") as mock_msg:
            self._fire_login_signal(self.account)
        mock_msg.assert_not_called()

    def test_no_notification_when_no_subscriptions(self):
        with patch.object(self.account, "msg") as mock_msg:
            self._fire_login_signal(self.account)
        mock_msg.assert_not_called()

    def test_last_notified_at_updated_after_login(self):
        sub = Subscription.objects.create(account=self.account, board=self.board)
        self.assertIsNone(sub.last_notified_at)
        with patch.object(self.account, "msg"):
            self._fire_login_signal(self.account)
        sub.refresh_from_db()
        self.assertIsNotNone(sub.last_notified_at)

    def test_last_notified_at_updated_even_without_unread(self):
        """last_notified_at is always stamped, whether or not a message is sent."""
        sub = Subscription.objects.create(
            account=self.account,
            board=self.board,
            last_notified_at=timezone.now() - timedelta(hours=1),
        )
        before = sub.last_notified_at
        with patch.object(self.account, "msg"):
            self._fire_login_signal(self.account)
        sub.refresh_from_db()
        self.assertGreater(sub.last_notified_at, before)

    def test_multi_board_unread_counts(self):
        board2 = _make_board("Staff", board_type=Board.BoardType.OOC, order=2)
        Subscription.objects.create(account=self.account, board=self.board)
        Subscription.objects.create(account=self.account, board=board2)
        for board, title in [(self.board, "Post A"), (board2, "Post B")]:
            Post.all_objects.create(
                board=board,
                post_number=1,
                title=title,
                content="content",
                author=self.char1,
                author_name=self.char1.key,
            )
        with patch.object(self.account, "msg") as mock_msg:
            self._fire_login_signal(self.account)
        mock_msg.assert_called_once()
        call_args = mock_msg.call_args[0][0]
        self.assertIn("News", call_args)
        self.assertIn("Staff", call_args)


# ---------------------------------------------------------------------------
# XP integration — sweep (no evennia_xp required)
# ---------------------------------------------------------------------------


class TestSweepCutsceneSpam(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.window_end = self.now + timedelta(days=1)
        self.ic_board = _make_ic_board("IC Spam Test", order=90)
        self.ooc_board, _ = Board.objects.get_or_create(
            name="OOC Spam Test",
            defaults={"board_type": Board.BoardType.OOC, "order": 91},
        )

    def test_fires_at_three_ic_posts_in_24h(self):
        from evennia_boards.integrations.xp import sweep_cutscene_spam

        posts = [
            _make_ic_post(
                self.char1,
                self.ic_board,
                offset_hours=i + 1,
                window_end=self.window_end,
            )
            for i in range(3)
        ]
        sweep_cutscene_spam(self.window_end)
        for p in posts:
            p.refresh_from_db()
            self.assertTrue(p.xp_flagged)
            self.assertIn("cutscene spam", p.xp_flag_reason)

    def test_reporter_called_on_flag(self):
        from evennia_boards.integrations.xp import sweep_cutscene_spam

        for i in range(3):
            _make_ic_post(
                self.char1,
                self.ic_board,
                offset_hours=i + 1,
                window_end=self.window_end,
            )
        with patch("evennia_boards.integrations.xp._call_reporter") as mock_reporter:
            sweep_cutscene_spam(self.window_end)
        mock_reporter.assert_called_once()

    def test_ooc_posts_not_flagged(self):
        from evennia_boards.integrations.xp import sweep_cutscene_spam

        posts = [
            _make_ic_post(
                self.char1,
                self.ooc_board,
                offset_hours=i + 1,
                window_end=self.window_end,
            )
            for i in range(3)
        ]
        sweep_cutscene_spam(self.window_end)
        for p in posts:
            p.refresh_from_db()
            self.assertFalse(p.xp_flagged)

    def test_two_ic_posts_not_flagged(self):
        from evennia_boards.integrations.xp import sweep_cutscene_spam

        posts = [
            _make_ic_post(
                self.char1,
                self.ic_board,
                offset_hours=i + 1,
                window_end=self.window_end,
            )
            for i in range(2)
        ]
        sweep_cutscene_spam(self.window_end)
        for p in posts:
            p.refresh_from_db()
            self.assertFalse(p.xp_flagged)

    def test_single_post_not_flagged(self):
        from evennia_boards.integrations.xp import sweep_cutscene_spam

        post = _make_ic_post(self.char1, self.ic_board, window_end=self.window_end)
        sweep_cutscene_spam(self.window_end)
        post.refresh_from_db()
        self.assertFalse(post.xp_flagged)

    def test_idempotent_already_flagged(self):
        from evennia_boards.integrations.xp import sweep_cutscene_spam

        posts = [
            _make_ic_post(
                self.char1,
                self.ic_board,
                offset_hours=i + 1,
                window_end=self.window_end,
            )
            for i in range(3)
        ]
        Post.all_objects.filter(pk__in=[p.pk for p in posts]).update(
            xp_flagged=True, xp_flag_reason="pre-existing"
        )
        with patch("evennia_boards.integrations.xp._call_reporter") as mock_reporter:
            sweep_cutscene_spam(self.window_end)
        mock_reporter.assert_not_called()

    def test_different_authors_independent(self):
        from evennia_boards.integrations.xp import sweep_cutscene_spam

        char1_post = _make_ic_post(self.char1, self.ic_board, window_end=self.window_end)
        for i in range(3):
            _make_ic_post(
                self.char2,
                self.ic_board,
                offset_hours=i + 1,
                window_end=self.window_end,
            )
        sweep_cutscene_spam(self.window_end)
        char1_post.refresh_from_db()
        self.assertFalse(char1_post.xp_flagged)


# ---------------------------------------------------------------------------
# XP integration — collector (requires evennia_xp)
# ---------------------------------------------------------------------------


@unittest.skipUnless(_HAS_XP, "evennia_xp not installed")
class TestCollectCutscenePosts(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.ic_board = _make_ic_board()

    def test_ic_post_yields_award(self):
        from evennia_xp.models import XPLog

        from evennia_boards.integrations.xp import collect_cutscene_posts

        _make_ic_post(self.char1, self.ic_board, window_end=self.now)
        with patch(_XP_GATING, return_value=Decimal("1.0")):
            awards = list(collect_cutscene_posts(self.now))
        self.assertEqual(len(awards), 1)
        a = awards[0]
        self.assertEqual(a.character_id, self.char1.pk)
        self.assertEqual(a.amount, Decimal("1.0"))
        self.assertEqual(a.source_type, XPLog.SourceType.CUTSCENE)

    def test_ooc_post_skipped(self):
        from evennia_boards.integrations.xp import collect_cutscene_posts

        ooc_board, _ = Board.objects.get_or_create(
            name="OOC General",
            defaults={"board_type": Board.BoardType.OOC, "order": 50},
        )
        Post.all_objects.create(
            board=ooc_board,
            post_number=1,
            title="OOC Post",
            content="ooc content",
            author=self.char1,
            author_name=self.char1.key,
        )
        with patch(_XP_GATING, return_value=Decimal("1.0")):
            awards = list(collect_cutscene_posts(self.now))
        self.assertEqual(len(awards), 0)

    def test_out_of_window_skipped(self):
        from evennia_boards.integrations.xp import collect_cutscene_posts

        _make_ic_post(self.char1, self.ic_board, window_end=self.now - timedelta(days=8))
        with patch(_XP_GATING, return_value=Decimal("1.0")):
            awards = list(collect_cutscene_posts(self.now))
        self.assertEqual(len(awards), 0)

    def test_already_awarded_skipped(self):
        from evennia_xp.models import XPLog

        from evennia_boards.integrations.xp import collect_cutscene_posts

        post = _make_ic_post(self.char1, self.ic_board, window_end=self.now)
        XPLog.objects.create(
            character_id=self.char1.pk,
            character_name=self.char1.key,
            amount=Decimal("1.0"),
            source_type=XPLog.SourceType.CUTSCENE,
            source_ref_id=post.pk,
            week="2026-W18",
        )
        with patch(_XP_GATING, return_value=Decimal("1.0")):
            awards = list(collect_cutscene_posts(self.now))
        self.assertEqual(len(awards), 0)

    def test_downtime_multiplier_zero_skipped(self):
        from evennia_boards.integrations.xp import collect_cutscene_posts

        _make_ic_post(self.char1, self.ic_board, window_end=self.now)
        with patch(_XP_GATING, return_value=Decimal("0")):
            awards = list(collect_cutscene_posts(self.now))
        self.assertEqual(len(awards), 0)

    def test_multiplier_override_doubles_amount(self):
        from evennia_boards.integrations.xp import collect_cutscene_posts

        _make_ic_post(self.char1, self.ic_board, window_end=self.now)
        with patch(_XP_GATING, return_value=Decimal("2.0")):
            awards = list(collect_cutscene_posts(self.now))
        self.assertEqual(len(awards), 1)
        self.assertEqual(awards[0].amount, Decimal("2.0"))

    def test_xp_flagged_post_skipped(self):
        from evennia_boards.integrations.xp import collect_cutscene_posts

        post = _make_ic_post(self.char1, self.ic_board, window_end=self.now)
        Post.all_objects.filter(pk=post.pk).update(
            xp_flagged=True, xp_flag_reason="auto-flag: test"
        )
        with patch(_XP_GATING, return_value=Decimal("1.0")):
            awards = list(collect_cutscene_posts(self.now))
        self.assertEqual(len(awards), 0)


# ---------------------------------------------------------------------------
# Anti-gaming reporter seam
# ---------------------------------------------------------------------------


class TestCallReporter(EvenniaTest):
    def test_no_reporter_logs_warning(self):
        from evennia_boards.integrations.xp import _call_reporter

        with (
            self.settings(BOARDS_ANTIGAMING_REPORTER=None),
            self.assertLogs("evennia", level="WARNING") as cm,
        ):
            _call_reporter("Test flag", "details")
        self.assertTrue(any("flag logged only" in line for line in cm.output))

    def test_configured_reporter_is_called(self):
        import sys
        import types

        from evennia_boards.integrations.xp import _call_reporter

        called_with = []

        def mock_reporter(title, description):
            called_with.append((title, description))

        module_name = "evennia_boards._test_reporter_stub"
        mod = types.ModuleType(module_name)
        mod.report = mock_reporter
        sys.modules[module_name] = mod
        try:
            with self.settings(BOARDS_ANTIGAMING_REPORTER=f"{module_name}.report"):
                _call_reporter("Title", "Body")
        finally:
            sys.modules.pop(module_name, None)

        self.assertEqual(len(called_with), 1)
        self.assertEqual(called_with[0][0], "Title")


# ---------------------------------------------------------------------------
# is_staff helper
# ---------------------------------------------------------------------------


class TestIsStaff(EvenniaTest):
    def test_superuser_is_staff(self):
        from evennia_boards.commands import is_staff

        self.char1.account.is_superuser = True
        self.assertTrue(is_staff(self.char1))

    def test_regular_character_is_not_staff(self):
        from evennia_boards.commands import is_staff

        self.char1.account.is_superuser = False
        result = is_staff(self.char1)
        self.assertIsInstance(result, bool)
