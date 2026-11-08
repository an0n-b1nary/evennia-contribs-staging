# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Ignore-aware board projections and unread behavior.

Social is deliberately optional. The projection and serializer tests run with
Links alone; service integration cases skip when evennia-social is absent.
"""

import unittest
from dataclasses import FrozenInstanceError
from datetime import timedelta
from importlib import import_module, util
from unittest.mock import patch

from django.conf import settings
from django.contrib import admin
from django.test import RequestFactory, override_settings
from django.urls import include, path
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from evennia.web.urls import urlpatterns as evennia_default_urlpatterns
from rest_framework.test import APIRequestFactory, force_authenticate

from evennia_boards.api.serializers import BoardSerializer, PostSerializer
from evennia_boards.api.views import PostViewSet
from evennia_boards.models import Board, Post, PostReadSuppression, Subscription
from evennia_boards.presentation import PolicyContext, visible_post_count
from evennia_boards.views import BoardDetailView, BoardListView, PostReplyView

try:
    _HAS_SOCIAL = util.find_spec("evennia_social") is not None
except (ImportError, ModuleNotFoundError):
    _HAS_SOCIAL = False


def requires_social(test):
    """Skip one real-provider test when Social is physically absent."""
    return unittest.skipUnless(_HAS_SOCIAL, "evennia-social is an optional partner")(test)


def _always_web_staff(_request):
    """Dotted-path host predicate used to prove HTTP staff bypass is honored."""
    return True


urlpatterns = [
    path("", include(("evennia_boards.urls", "evennia_boards"))),
    path("admin/", admin.site.urls),
    *evennia_default_urlpatterns,
]


def _board(name="Notices", kind=Board.BoardType.OOC):
    return Board.objects.create(name=name, board_type=kind)


def _post(board, author, title, content, *, parent=None):
    return Post.create_post(
        board=board,
        author=author,
        title=title,
        content=content,
        parent_post=parent,
    )


@override_settings(ROOT_URLCONF=__name__)
class TestBoardIgnoreProjection(EvenniaTest):
    """The safe projection is the common source for every display surface."""

    def setUp(self):
        super().setUp()
        self.board = _board()
        self.reader = self.char1
        self.reader_account = self.account
        self.author = self.char2
        self.reader_account.permissions.clear()
        self.reader_account.is_superuser = False
        self.reader_account.save()
        self.reader.permissions.clear()
        self.factory = RequestFactory()

    def _request(self, path="/boards/", user=None):
        request = self.factory.get(path)
        request.user = user or self.reader_account
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        return request

    def test_placeholder_projection_is_frozen_redacted_and_cached_per_author(self):
        from evennia_boards import presentation

        first = _post(self.board, self.author, "PRIVATE TITLE", "PRIVATE BODY")
        second = _post(self.board, self.author, "OTHER PRIVATE TITLE", "OTHER BODY")
        with patch.object(presentation, "ignore_mode", return_value="placeholder") as mode:
            policy = PolicyContext(self.reader, staff=False)
            values = policy.project_many(
                Post.objects.filter(pk__in=(first.pk, second.pk)).select_related(
                    "board", "author", "parent_post", "parent_post__author"
                )
            )

        projection = values[first.pk]
        self.assertEqual(projection.title, "[A post by an ignored player.]")
        self.assertEqual(projection.content, "")
        self.assertEqual(projection.author_name, "")
        self.assertIsNone(projection.author_id)
        self.assertFalse(hasattr(projection, "raw_post"))
        with self.assertRaises(FrozenInstanceError):
            projection.title = "changed"
        self.assertEqual(mode.call_count, 1)
        self.assertEqual(policy.placeholder_ids, {first.pk, second.pk})
        self.assertFalse(PostReadSuppression.objects.exists())

    def test_hide_projection_writes_only_suppression_receipts_and_counts_zero(self):
        from evennia_boards import presentation

        hidden = _post(self.board, self.author, "PRIVATE", "SECRET")
        _post(self.board, self.reader, "Visible", "Readable")

        def mode(_viewer, sender, _kind):
            return "hide" if sender.pk == self.author.pk else None

        with patch.object(presentation, "ignore_mode", side_effect=mode):
            policy = PolicyContext(self.reader_account, staff=False)
            rows = Post.objects.filter(board=self.board).select_related("author", "board")
            projected = policy.project_many(list(rows))
            self.assertEqual(visible_post_count(self.reader_account, rows, context=policy), 1)
        self.assertIsNone(projected[hidden.pk])
        self.assertEqual(
            set(
                PostReadSuppression.objects.filter(account=self.reader_account).values_list(
                    "post_id", flat=True
                )
            ),
            {hidden.pk},
        )

    def test_provider_errors_and_invalid_values_fail_open_without_unread_side_effects(self):
        from evennia_links.ignoring import ignore_mode_requested

        post = _post(self.board, self.author, "Ordinary title", "Ordinary body")
        sub = Subscription.objects.create(account=self.reader_account, board=self.board)
        self.reader_account.attributes.add("boards_web_read", {str(self.board.pk): 4})
        old_markers = dict(self.reader_account.attributes.get("boards_web_read"))

        def hider(sender, viewer, sender_object, kind, **kwargs):
            return "hide"

        def broken(sender, viewer, sender_object, kind, **kwargs):
            raise RuntimeError("provider unavailable")

        def invalid(sender, viewer, sender_object, kind, **kwargs):
            return "unknown-mode"

        for receiver, uid in ((broken, "broken"), (invalid, "invalid")):
            with self.subTest(receiver=uid):
                ignore_mode_requested.connect(hider, dispatch_uid=f"boards-test-hide-{uid}")
                ignore_mode_requested.connect(receiver, dispatch_uid=f"boards-test-{uid}")
                try:
                    with self.assertLogs("evennia", level="ERROR"):
                        safe = PolicyContext(self.reader_account, staff=False).project(post)
                    self.assertEqual(safe.title, "Ordinary title")
                    self.assertEqual(safe.content, "Ordinary body")
                    self.assertEqual(sub.unread_count(), 1)
                    response = BoardListView.as_view()(self._request())
                    response.render()
                    self.assertIn("Ordinary title", response.content.decode())
                    self.assertFalse(
                        PostReadSuppression.objects.filter(
                            account=self.reader_account, post=post
                        ).exists()
                    )
                    self.reader_account.attributes.reset_cache()
                    self.assertEqual(
                        dict(self.reader_account.attributes.get("boards_web_read")), old_markers
                    )
                    sub.refresh_from_db()
                    self.assertIsNone(sub.last_notified_at)
                finally:
                    ignore_mode_requested.disconnect(dispatch_uid=f"boards-test-hide-{uid}")
                    ignore_mode_requested.disconnect(dispatch_uid=f"boards-test-{uid}")

    def test_old_render_merges_newer_read_marker_and_only_its_displayed_placeholders(self):
        from evennia_boards.presentation import commit_rendered_state
        from evennia_links.ignoring import ignore_mode_requested

        def placeholder(sender, viewer, sender_object, kind, **kwargs):
            return "placeholder"

        first = _post(self.board, self.author, "FIRST SECRET", "first body")
        self.reader_account.attributes.add("boards_web_read", {"999": 7})
        ignore_mode_requested.connect(placeholder, dispatch_uid="boards-test-delayed-render")
        try:
            response = BoardDetailView.as_view()(self._request(), pk=self.board.pk)
            second = _post(self.board, self.author, "SECOND SECRET", "second body")
            self.assertFalse(
                PostReadSuppression.objects.filter(account=self.reader_account, post=first).exists()
            )
            commit_rendered_state(
                self.reader_account,
                board_id=self.board.pk,
                high_water=100,
            )
            response.render()
            markers = dict(self.reader_account.attributes.get("boards_web_read"))
            self.assertEqual(markers, {"999": 7, str(self.board.pk): 100})
            self.assertTrue(
                PostReadSuppression.objects.filter(account=self.reader_account, post=first).exists()
            )
            self.assertFalse(
                PostReadSuppression.objects.filter(
                    account=self.reader_account, post=second
                ).exists()
            )
        finally:
            ignore_mode_requested.disconnect(dispatch_uid="boards-test-delayed-render")

    @requires_social
    def test_no_resurrection_across_remove_clear_preferences_and_unarchive(self):
        from django.utils import timezone

        from evennia_social import ignore

        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        ignore.set_boards_preference(self.reader_account, "hide")
        cutoff = timezone.now() - timedelta(minutes=1)
        visible_a = _post(self.board, self.reader, "A", "visible A")
        hidden_b1 = _post(self.board, self.author, "B1", "offline hidden")
        archived_b2 = _post(self.board, self.author, "B2", "archived offline")
        archived_b2.archive(editor=self.author)
        visible_c = _post(self.board, self.reader, "C", "visible C")
        sub = Subscription.objects.create(
            account=self.reader_account, board=self.board, last_notified_at=cutoff
        )
        self.assertIsNone(self.reader_account.attributes.get("boards_web_read"))

        # Hidden rows exist without any board read. /except snapshots the old
        # hide state, including the archived row, before becoming visible.
        self.assertTrue(ignore.set_entry(self.reader_account, self.author, ignore.POSTS))
        except_new = _post(self.board, self.author, "B3", "created under except")
        self.assertEqual(sub.unread_count(), 3)
        self.assertTrue(ignore.set_entry(self.reader_account, self.author))
        ignore.set_boards_preference(self.reader_account, "show")
        hidden_b4 = _post(self.board, self.author, "B4", "placeholder, not displayed")
        ignore.set_boards_preference(self.reader_account, "hide")
        self.assertTrue(ignore.remove_entry(self.reader_account, self.author))
        after_remove = _post(self.board, self.author, "B5", "created after remove")
        ignore.set_entry(self.reader_account, self.author)
        self.assertTrue(ignore.clear(self.reader_account))

        archived_b2 = Post.all_objects.get(pk=archived_b2.pk)
        archived_b2.unarchive()
        new_b = _post(self.board, self.author, "B6", "new after final clear")
        self.assertEqual(sub.unread_count(), 3)
        self.assertEqual(
            set(
                PostReadSuppression.objects.filter(account=self.reader_account).values_list(
                    "post_id", flat=True
                )
            ),
            {hidden_b1.pk, archived_b2.pk, except_new.pk, hidden_b4.pk, after_remove.pk},
        )
        self.assertEqual(
            {visible_a.pk, visible_c.pk, new_b.pk},
            set(
                Post.objects.filter(board=self.board)
                .exclude(read_suppressions__account=self.reader_account)
                .values_list("pk", flat=True)
            ),
        )
        self.assertIsNone(self.reader_account.attributes.get("boards_web_read"))
        sub.refresh_from_db()
        self.assertEqual(sub.last_notified_at, cutoff)
        from evennia_boards.listeners import _notify_board_subscriptions

        with patch.object(self.reader_account, "msg") as message:
            _notify_board_subscriptions(self.reader_account)
        self.assertIn("3 new posts", message.call_args.args[0])
        sub.refresh_from_db()
        self.assertGreater(sub.last_notified_at, cutoff)

    @requires_social
    def test_http_staff_predicate_bypasses_but_django_is_staff_alone_does_not(self):
        from evennia_social import ignore

        secret = _post(self.board, self.author, "Staff can read", "staff body")
        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        ignore.set_boards_preference(self.reader_account, "hide")
        self.reader_account.is_staff = True
        self.reader_account.save()

        ordinary = BoardDetailView.as_view()(self._request(), pk=self.board.pk)
        ordinary.render()
        self.assertNotIn("Staff can read", ordinary.content.decode())
        with override_settings(
            EVENNIA_WEB_STAFF_PREDICATE="evennia_boards.test_ignoring._always_web_staff"
        ):
            staff = BoardDetailView.as_view()(self._request(), pk=self.board.pk)
            staff.render()
            self.assertIn("Staff can read", staff.content.decode())

        from evennia_boards.api.views import PostViewSet

        request = APIRequestFactory().get(f"/api/posts/{secret.pk}/")
        force_authenticate(request, user=self.reader_account)
        hidden = PostViewSet.as_view({"get": "retrieve"})(request, pk=secret.pk)
        self.assertEqual(hidden.status_code, 404)
        with override_settings(
            EVENNIA_WEB_STAFF_PREDICATE="evennia_boards.test_ignoring._always_web_staff"
        ):
            request = APIRequestFactory().get(f"/api/posts/{secret.pk}/")
            force_authenticate(request, user=self.reader_account)
            staff = PostViewSet.as_view({"get": "retrieve"})(request, pk=secret.pk)
            staff.render()
            self.assertEqual(staff.data["content"], "staff body")

    def test_nested_inherited_titles_never_reveal_filtered_ancestor_title(self):
        from evennia_boards import presentation

        root = _post(self.board, self.author, "SECRET DESCENDANT", "root")
        child = _post(self.board, self.reader, "Re: SECRET DESCENDANT", "child", parent=root)
        grandchild = _post(
            self.board,
            self.reader,
            "Re: Re: SECRET DESCENDANT",
            "grandchild",
            parent=child,
        )

        def mode(_viewer, sender, _kind):
            return "placeholder" if sender.pk == self.author.pk else None

        with patch.object(presentation, "ignore_mode", side_effect=mode):
            policy = PolicyContext(self.reader, staff=False)
            projected = policy.project_many(
                Post.objects.filter(board=self.board)
                .select_related("author", "board", "parent_post", "parent_post__author")
                .order_by("post_number")
            )
        self.assertEqual(projected[child.pk].title, "Re: post #1")
        self.assertEqual(projected[grandchild.pk].title, "Re: Re: post #1")
        self.assertEqual(projected[grandchild.pk].parent_post.title, "Re: post #1")
        for safe in projected.values():
            self.assertNotIn("SECRET DESCENDANT", safe.title)

    def test_deep_custom_titles_project_without_recursion(self):
        from evennia_boards import presentation

        # These are unsaved Django Post instances with real model relations.
        parent = None
        for number in range(1100):
            parent = Post(
                pk=1_000_000 + number,
                board=self.board,
                post_number=number + 1,
                title="CUSTOM",
                content="body",
                author=self.reader,
                author_name="Reader",
                parent_post=parent,
            )

        with patch.object(presentation, "ignore_mode", return_value=None):
            projected = PolicyContext(self.reader, staff=False).project(parent)

        self.assertEqual(projected.title, "CUSTOM")
        self.assertEqual(projected.parent_post.title, "CUSTOM")

    def test_safe_title_retains_visited_cycle_guard(self):
        from evennia_boards import presentation

        parent = Post(
            pk=1_100_001,
            board=self.board,
            post_number=1,
            title="PARENT",
            content="body",
            author=self.reader,
            author_name="Reader",
        )
        child = Post(
            pk=1_100_002,
            board=self.board,
            post_number=2,
            title="Re: PARENT",
            content="body",
            author=self.reader,
            author_name="Reader",
            parent_post=parent,
        )
        parent.parent_post = child

        with patch.object(presentation, "ignore_mode", return_value=None):
            policy = PolicyContext(self.reader, staff=False)
            title = policy._safe_title(child, visited={parent.pk})

        self.assertEqual(title, f"Re: post #{parent.post_number}")

    def test_api_serializers_work_without_request_context_and_keep_field_format(self):
        post = _post(self.board, self.author, "Ordinary", "Body")
        serializer = PostSerializer(post)
        self.assertIn("parent_post_label", serializer.fields)
        serializer.fields["created_at"].format = "%Y"
        serializer.fields["updated_at"].format = "%Y"
        data = serializer.data
        self.assertEqual(data["created_at"], post.created_at.strftime("%Y"))
        self.assertEqual(data["updated_at"], post.updated_at.strftime("%Y"))
        self.assertEqual(BoardSerializer(self.board).data["post_count"], 1)

    @requires_social
    def test_social_provider_maps_show_hide_except_for_both_board_types(self):
        from evennia_links.ignoring import ignore_mode
        from evennia_social import ignore

        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        self.assertEqual(ignore_mode(self.reader_account, self.author, "boards"), "placeholder")
        self.assertEqual(
            PolicyContext(self.reader_account, staff=False).mode_for(self.author), "placeholder"
        )
        self.assertTrue(ignore.set_boards_preference(self.reader_account, "hide"))
        self.assertEqual(ignore_mode(self.reader_account, self.author, "boards"), "hide")
        self.assertTrue(ignore.set_entry(self.reader_account, self.author, ignore.POSTS))
        self.assertIsNone(ignore_mode(self.reader_account, self.author, "boards"))

        for kind in (Board.BoardType.IC, Board.BoardType.OOC):
            board = _board(f"{kind}", kind)
            post = _post(board, self.author, "Both modes", "Body")
            self.assertIsNotNone(PolicyContext(self.reader_account).project(post))

        ignore.set_entry(self.reader_account, self.author)
        ignore.set_boards_preference(self.reader_account, "show")
        self.reader_account.characters.remove(self.reader)
        self.assertEqual(ignore_mode(self.reader_account, self.author, "boards"), "placeholder")
        self.account2.permissions.add("Builder")
        self.assertIsNone(ignore_mode(self.reader_account, self.author, "boards"))
        self.account2.permissions.remove("Builder")
        self.reader_account.permissions.add("Builder")
        self.assertIsNone(ignore_mode(self.reader_account, self.author, "boards"))
        self.reader_account.permissions.remove("Builder")

    @requires_social
    def test_prechange_snapshot_covers_archived_rows_and_failure_rolls_back(self):
        from evennia_social import ignore

        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        ignore.set_boards_preference(self.reader_account, "hide")
        active = _post(self.board, self.author, "Active", "Body")
        archived = _post(self.board, self.author, "Archived", "Body")
        archived.archive(editor=self.author)

        # Removing the ignore makes both rows visible, but the old hide state
        # is captured first and remains an unread exclusion.
        self.assertTrue(ignore.set_entry(self.reader_account, self.author, ignore.POSTS))
        self.assertEqual(
            set(
                PostReadSuppression.objects.filter(account=self.reader_account).values_list(
                    "post_id", flat=True
                )
            ),
            {active.pk, archived.pk},
        )

        ignore.set_entry(self.reader_account, self.author)
        ignore.set_boards_preference(self.reader_account, "hide")
        before = ignore.boards_preference(self.reader_account)
        with (
            patch(
                "evennia_boards.presentation.register_policy_snapshot",
                side_effect=RuntimeError("snapshot unavailable"),
            ),
            self.assertRaises(ignore.PolicyChangeError),
        ):
            ignore.set_boards_preference(self.reader_account, "show")
        self.assertEqual(ignore.boards_preference(self.reader_account), before)

    @requires_social
    def test_staff_custom_board_lock_bypasses_ignore_in_unread_and_login_count(self):
        from evennia_boards.listeners import _notify_board_subscriptions
        from evennia_social import ignore

        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        ignore.set_boards_preference(self.reader_account, "hide")
        _post(self.board, self.author, "Ignored", "Body")
        Subscription.objects.create(account=self.reader_account, board=self.board)
        with override_settings(BOARDS_STAFF_LOCK="cmd:true()"):
            self.assertEqual(Subscription.objects.get().unread_count(), 1)
            with patch.object(self.reader_account, "msg") as message:
                _notify_board_subscriptions(self.reader_account)
            self.assertIn("1 new post", message.call_args.args[0])

    @requires_social
    def test_login_with_only_hidden_posts_sends_no_unread_alert(self):
        from evennia_boards.listeners import _notify_board_subscriptions
        from evennia_boards.signals import board_unread_notified
        from evennia_social import ignore

        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        ignore.set_boards_preference(self.reader_account, "hide")
        _post(self.board, self.author, "Hidden only", "Body")
        subscription = Subscription.objects.create(account=self.reader_account, board=self.board)
        notifications = []

        def receive(sender, **kwargs):
            notifications.append(kwargs["unread_count"])

        board_unread_notified.connect(receive, weak=False)
        try:
            with patch.object(self.reader_account, "msg") as message:
                _notify_board_subscriptions(self.reader_account)
            message.assert_not_called()
        finally:
            board_unread_notified.disconnect(receive)
        self.assertEqual(notifications, [])
        subscription.refresh_from_db()
        self.assertIsNotNone(subscription.last_notified_at)

    @requires_social
    def test_web_hides_latest_and_placeholder_receipt_waits_for_render(self):
        from evennia_social import ignore

        _post(self.board, self.reader, "Visible latest", "Visible body")
        secret = _post(self.board, self.author, "SECRET LATEST", "SECRET BODY")
        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        ignore.set_boards_preference(self.reader_account, "hide")

        hidden_response = BoardDetailView.as_view()(self._request(), pk=self.board.pk)
        hidden_response.render()
        hidden_html = hidden_response.content.decode()
        self.assertNotIn("SECRET LATEST", hidden_html)
        self.assertNotIn("SECRET BODY", hidden_html)
        self.assertTrue(
            PostReadSuppression.objects.filter(account=self.reader_account, post=secret).exists()
        )
        list_response = BoardListView.as_view()(self._request())
        list_response.render()
        self.assertIn("Visible latest", list_response.content.decode())

        ignore.set_boards_preference(self.reader_account, "show")
        placeholder = _post(self.board, self.author, "SECRET SECOND", "SECRET SECOND BODY")
        placeholder_response = BoardDetailView.as_view()(self._request(), pk=self.board.pk)
        self.assertFalse(
            PostReadSuppression.objects.filter(
                account=self.reader_account, post=placeholder
            ).exists()
        )
        placeholder_response.render()
        placeholder_html = placeholder_response.content.decode()
        self.assertIn("[A post by an ignored player.]", placeholder_html)
        self.assertNotIn("SECRET LATEST", placeholder_html)
        self.assertNotIn("SECRET BODY", placeholder_html)
        self.assertTrue(
            PostReadSuppression.objects.filter(
                account=self.reader_account, post=placeholder
            ).exists()
        )
        self.assertTrue(
            PostReadSuppression.objects.filter(account=self.reader_account, post=secret).exists()
        )

    @requires_social
    def test_reply_form_shows_placeholder_marker_and_records_only_after_render(self):
        from evennia_social import ignore

        parent = _post(self.board, self.author, "SECRET PARENT", "SECRET EXCERPT")
        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        request = self._request(f"/boards/{self.board.pk}/posts/{parent.pk}/reply/")
        with patch.object(self.reader_account, "get_all_puppets", return_value=[self.reader]):
            response = PostReplyView.as_view()(request, pk=self.board.pk, post_id=parent.pk)
        self.assertFalse(
            PostReadSuppression.objects.filter(account=self.reader_account, post=parent).exists()
        )
        response.render()
        html = response.content.decode()
        self.assertIn("[A post by an ignored player.]", html)
        self.assertNotIn("SECRET PARENT", html)
        self.assertNotIn("SECRET EXCERPT", html)
        self.assertTrue(
            PostReadSuppression.objects.filter(account=self.reader_account, post=parent).exists()
        )

    @requires_social
    def test_hidden_reply_form_uses_generic_parent_label_without_placeholder(self):
        from evennia_social import ignore

        parent = _post(self.board, self.author, "SECRET HIDDEN PARENT", "SECRET EXCERPT")
        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        ignore.set_boards_preference(self.reader_account, "hide")
        request = self._request(f"/boards/{self.board.pk}/posts/{parent.pk}/reply/")
        with patch.object(self.reader_account, "get_all_puppets", return_value=[self.reader]):
            response = PostReplyView.as_view()(request, pk=self.board.pk, post_id=parent.pk)
        response.render()
        html = response.content.decode()
        self.assertIn("[reply to a hidden post]", html)
        self.assertNotIn("[A post by an ignored player.]", html)
        self.assertNotIn("SECRET HIDDEN PARENT", html)
        self.assertNotIn("SECRET EXCERPT", html)

    @requires_social
    def test_show_replies_false_keeps_placeholder_reply_unread_until_appearance(self):
        from django.utils import timezone

        from evennia_social import ignore

        root = _post(self.board, self.reader, "Root", "body")
        reply = _post(self.board, self.author, "SECRET REPLY", "SECRET REPLY BODY", parent=root)
        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        Subscription.objects.create(
            account=self.reader_account,
            board=self.board,
            last_notified_at=timezone.now() - timedelta(minutes=1),
        )

        filtered = BoardDetailView.as_view()(
            self._request("/boards/?show_replies=0"), pk=self.board.pk
        )
        filtered.render()
        self.assertFalse(
            PostReadSuppression.objects.filter(account=self.reader_account, post=reply).exists()
        )
        self.assertIsNone(self.reader_account.attributes.get("boards_web_read"))
        self.assertEqual(Subscription.objects.get().unread_count(), 2)

        full = BoardDetailView.as_view()(self._request(), pk=self.board.pk)
        full.render()
        self.assertTrue(
            PostReadSuppression.objects.filter(account=self.reader_account, post=reply).exists()
        )
        self.assertEqual(Subscription.objects.get().unread_count(), 1)
        list_response = BoardListView.as_view()(self._request())
        list_response.render()
        self.assertIn(">Read</span>", list_response.content.decode())

    @requires_social
    def test_invalid_reply_post_renders_placeholder_then_records_receipt(self):
        from evennia_social import ignore

        parent = _post(self.board, self.author, "SECRET PARENT", "SECRET EXCERPT")
        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        request = self.factory.post("/", data={"title": "", "content": ""})
        request.user = self.reader_account
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        with patch.object(self.reader_account, "get_all_puppets", return_value=[self.reader]):
            response = PostReplyView.as_view()(request, pk=self.board.pk, post_id=parent.pk)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            PostReadSuppression.objects.filter(account=self.reader_account, post=parent).exists()
        )
        response.render()
        self.assertIn("[A post by an ignored player.]", response.content.decode())
        self.assertTrue(
            PostReadSuppression.objects.filter(account=self.reader_account, post=parent).exists()
        )

    @requires_social
    def test_api_filters_hidden_rows_before_cursor_pagination(self):
        from evennia_social import ignore

        for number in range(21):
            _post(self.board, self.author, f"SECRET API {number}", "SECRET API BODY")
        visible = _post(self.board, self.reader, "Later visible", "body")
        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        ignore.set_boards_preference(self.reader_account, "hide")

        request = APIRequestFactory().get(f"/api/posts/?board={self.board.pk}")
        force_authenticate(request, user=self.reader_account)
        response = PostViewSet.as_view({"get": "list"})(request)
        response.render()
        serialized = response.data["results"]
        self.assertEqual(len(serialized), 1)
        self.assertEqual(serialized[0]["id"], visible.pk)
        self.assertIsNone(response.data["next"])
        self.assertEqual(
            PostReadSuppression.objects.filter(account=self.reader_account).count(),
            21,
        )

    @requires_social
    def test_api_placeholder_receipt_waits_for_render_and_redacts_fields(self):
        from evennia_social import ignore

        secret = _post(self.board, self.author, "SECRET API TITLE", "SECRET API BODY")
        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        request = APIRequestFactory().get(f"/api/posts/?board={self.board.pk}")
        force_authenticate(request, user=self.reader_account)
        response = PostViewSet.as_view({"get": "list"})(request)
        self.assertFalse(
            PostReadSuppression.objects.filter(account=self.reader_account, post=secret).exists()
        )
        response.render()
        rows = response.data["results"]
        placeholder = next(row for row in rows if row["id"] == secret.pk)
        self.assertEqual(placeholder["title"], "[A post by an ignored player.]")
        self.assertEqual(placeholder["content"], "")
        self.assertEqual(placeholder["author_name"], "")
        self.assertNotIn("SECRET API", str(placeholder))
        self.assertTrue(
            PostReadSuppression.objects.filter(account=self.reader_account, post=secret).exists()
        )

    @requires_social
    def test_api_hidden_retrieve_board_counts_and_visible_reply_parent_are_safe(self):
        from evennia_boards.api.views import BoardViewSet
        from evennia_social import ignore

        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        ignore.set_boards_preference(self.reader_account, "hide")
        hidden = _post(self.board, self.author, "SECRET PARENT TITLE", "SECRET PARENT BODY")
        visible = _post(
            self.board,
            self.reader,
            "Re: SECRET PARENT TITLE",
            "VISIBLE REPLY BODY",
            parent=hidden,
        )

        request = APIRequestFactory().get(f"/api/posts/?board={self.board.pk}")
        force_authenticate(request, user=self.reader_account)
        posts = PostViewSet.as_view({"get": "list"})(request)
        posts.render()
        rows = posts.data["results"]
        self.assertEqual([row["id"] for row in rows], [visible.pk])
        self.assertEqual(rows[0]["title"], f"Re: post #{hidden.post_number}")
        self.assertIsNone(rows[0]["parent_post"])
        self.assertEqual(rows[0]["parent_post_label"], "[reply to a hidden post]")
        self.assertEqual(rows[0]["content"], "VISIBLE REPLY BODY")
        self.assertNotIn("SECRET PARENT", str(rows[0]))

        request = APIRequestFactory().get(f"/api/posts/{hidden.pk}/")
        force_authenticate(request, user=self.reader_account)
        response = PostViewSet.as_view({"get": "retrieve"})(request, pk=hidden.pk)
        self.assertEqual(response.status_code, 404)

        request = APIRequestFactory().get("/api/boards/")
        force_authenticate(request, user=self.reader_account)
        board_list = BoardViewSet.as_view({"get": "list"})(request)
        board_list.render()
        serialized_board = next(
            row for row in board_list.data["results"] if row["id"] == self.board.pk
        )
        self.assertEqual(serialized_board["post_count"], 1)

        request = APIRequestFactory().get(f"/api/boards/{self.board.pk}/")
        force_authenticate(request, user=self.reader_account)
        board_detail = BoardViewSet.as_view({"get": "retrieve"})(request, pk=self.board.pk)
        board_detail.render()
        self.assertEqual(board_detail.data["post_count"], 1)

    @requires_social
    def test_custom_ic_and_ooc_policy_is_shared_and_except_keeps_posts_visible(self):
        from evennia_social import ignore

        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        ignore.set_boards_preference(self.reader_account, "hide")
        for kind in (Board.BoardType.IC, Board.BoardType.OOC):
            board = _board(f"{kind} posts", kind)
            secret = _post(board, self.author, f"secret {kind}", "body")
            safe = _post(board, self.reader, f"reader {kind}", "safe")
            context = PolicyContext(self.reader_account, staff=False)
            projected = context.project_many(
                Post.objects.filter(board=board).select_related("author", "board")
            )
            self.assertIsNone(projected[secret.pk])
            self.assertIsNotNone(projected[safe.pk])
            self.assertEqual(
                visible_post_count(self.reader_account, [secret, safe], context=context), 1
            )
        self.assertTrue(ignore.set_entry(self.reader_account, self.author, ignore.POSTS))
        self.assertEqual(
            PolicyContext(self.reader_account, staff=False).mode_for(self.author), None
        )

    @requires_social
    def test_api_board_serializer_without_request_uses_ordinary_unfiltered_count(self):
        from evennia_social import ignore

        ignore.clear(self.reader_account)
        ignore.set_entry(self.reader_account, self.author)
        _post(self.board, self.author, "Visible placeholder", "Body")
        self.assertEqual(BoardSerializer(self.board).data["post_count"], 1)


class TestBoardIgnoreCommands(EvenniaCommandTest):
    """Command listings, direct reads and screenreader output share policy."""

    def setUp(self):
        super().setUp()
        self.board = _board()
        self.account.permissions.clear()
        self.account.is_superuser = False
        self.account.save()
        self.char1.permissions.clear()
        self.reader = self.char1
        self.author = self.char2

    def test_board_listing_keeps_the_space_after_each_post_number(self):
        from evennia_boards.commands import CmdBoard

        root = _post(self.board, self.author, "Plain title", "Body")
        _post(self.board, self.reader, "Re: Plain title", "Reply body", parent=root)
        output = self.call(CmdBoard(), "Notices")
        self.assertIn("  1. Plain title — ", output)
        self.assertIn("  2.   Re: Re: Plain title — ", output)

    @requires_social
    def test_hide_counts_and_direct_root_read_keep_other_authors_replies(self):
        from evennia_boards.commands import CmdBoard
        from evennia_social import ignore

        root = _post(self.board, self.author, "SECRET ROOT", "SECRET ROOT BODY")
        _post(self.board, self.reader, "Visible reply title", "VISIBLE REPLY BODY", parent=root)
        ignore.clear(self.reader)
        ignore.set_entry(self.reader, self.author)
        ignore.set_boards_preference(self.reader, "hide")

        listing = self.call(CmdBoard(), "")
        self.assertIn("1 post", listing)
        self.assertNotIn("SECRET ROOT", listing)
        direct = self.call(CmdBoard(), f"Notices/{root.post_number}")
        self.assertIn("[reply to a hidden post]", direct)
        self.assertIn("Visible reply title", direct)
        self.assertNotIn("SECRET ROOT", direct)
        self.assertNotIn("SECRET ROOT BODY", direct)

    @requires_social
    def test_placeholder_and_screenreader_branches_mask_without_losing_visible_reply(self):
        from evennia_boards import commands
        from evennia_boards.commands import CmdBoard
        from evennia_social import ignore

        root = _post(self.board, self.author, "SECRET ROOT", "SECRET ROOT BODY")
        _post(self.board, self.reader, "Visible reply title", "VISIBLE REPLY BODY", parent=root)
        ignore.clear(self.reader)
        ignore.set_entry(self.reader, self.author)

        output = self.call(CmdBoard(), "Notices")
        self.assertIn("[A post by an ignored player.]", output)
        self.assertIn("Visible reply title", output)
        self.assertNotIn("SECRET ROOT", output)
        self.assertNotIn("SECRET ROOT BODY", output)
        self.assertTrue(
            PostReadSuppression.objects.filter(account=self.account, post=root).exists()
        )

        ignore.set_boards_preference(self.reader, "hide")
        with patch.object(commands, "uses_screenreader", return_value=True):
            screenreader = self.call(CmdBoard(), "Notices")
        self.assertIn("Visible reply title", screenreader)
        self.assertNotIn("SECRET ROOT", screenreader)

    @requires_social
    def test_custom_boards_staff_lock_bypasses_ignore_in_command(self):
        from evennia_boards.commands import CmdBoard
        from evennia_social import ignore

        _post(self.board, self.author, "Staff-only view test", "staff body")
        ignore.clear(self.reader)
        ignore.set_entry(self.reader, self.author)
        ignore.set_boards_preference(self.reader, "hide")
        with override_settings(BOARDS_STAFF_LOCK="cmd:true()"):
            output = self.call(CmdBoard(), "Notices/1")
        self.assertIn("Staff-only view test", output)
        self.assertIn("staff body", output)

    @requires_social
    def test_reply_editor_uses_neutral_inherited_title_for_hidden_parent(self):
        from evennia_boards.commands import _bb_save
        from evennia_social import ignore

        parent = _post(self.board, self.author, "SECRET INHERITED TITLE", "parent body")
        ignore.clear(self.reader)
        ignore.set_entry(self.reader, self.author)
        ignore.set_boards_preference(self.reader, "hide")
        self.reader.attributes.add(
            "boards_editor_context",
            {"mode": "reply", "board_pk": self.board.pk, "parent_post_pk": parent.pk},
        )
        self.assertTrue(_bb_save(self.reader, "A reply body"))
        reply = Post.objects.get(parent_post=parent)
        self.assertEqual(reply.title, f"Re: post #{parent.post_number}")
        parent.refresh_from_db()
        self.assertEqual(parent.title, "SECRET INHERITED TITLE")


@unittest.skipIf(_HAS_SOCIAL, "requires an environment without evennia-social")
@override_settings(ROOT_URLCONF=__name__)
class TestBoardsWithoutSocial(EvenniaCommandTest):
    """The optional integration works normally when its partner is absent."""

    def setUp(self):
        super().setUp()
        self.board = _board()
        self.post = _post(self.board, self.char2, "No provider title", "No provider body")
        self.account.permissions.clear()
        self.account.is_superuser = False
        self.account.save()
        self.char1.permissions.clear()
        self.factory = RequestFactory()

    def test_command_html_api_and_count_do_not_attempt_social_imports(self):
        import builtins

        from django.apps import apps

        from evennia_links.ignoring import ignore_mode

        self.assertIsNone(util.find_spec("evennia_social"))
        self.assertFalse(apps.is_installed("evennia_social"))
        self.assertIsNone(ignore_mode(self.account, self.char2, "boards"))
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "evennia_social" or name.startswith("evennia_social."):
                raise AssertionError("Boards attempted to import the absent Social partner")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded_import):
            from evennia_boards.api.serializers import BoardSerializer, PostSerializer
            from evennia_boards.api.views import PostViewSet
            from evennia_boards.commands import CmdBoard

            command = self.call(CmdBoard(), self.board.name)
            self.assertIn("No provider title", command)

            request = self.factory.get("/boards/")
            request.user = self.account
            request.session = import_module(settings.SESSION_ENGINE).SessionStore()
            page = BoardDetailView.as_view()(request, pk=self.board.pk)
            page.render()
            self.assertIn("No provider title", page.content.decode())

            self.assertEqual(BoardSerializer(self.board).data["post_count"], 1)
            self.assertEqual(PostSerializer(self.post).data["title"], "No provider title")
            api_request = APIRequestFactory().get(f"/api/posts/{self.post.pk}/")
            force_authenticate(api_request, user=self.account)
            api = PostViewSet.as_view({"get": "retrieve"})(api_request, pk=self.post.pk)
            api.render()
            self.assertEqual(api.data["content"], "No provider body")
