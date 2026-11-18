# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Account ownership, source checkpoints and standalone delivery boundaries."""

from datetime import timedelta
from unittest.mock import Mock, patch

from django.apps import apps
from django.db import OperationalError, connection, transaction
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest

from evennia_boards.models import (
    Board,
    Post,
    PostReadSuppression,
    StandaloneNoticeClaim,
    Subscription,
)
from evennia_boards.notice_test_helpers import connected_session
from evennia_boards.notices import notify_login, post_committed, prepare_account
from evennia_links.notices import NoticeContext, RouteResult

SOURCE = {"boards": "evennia_boards.integrations.notices.BoardNoticeSource"}


@override_settings(LINKS_NOTICE_SOURCES=SOURCE, NOTICES_ENABLED=True)
class BoardsActivityTests(EvenniaTest):
    """Exercise Boards on the real optional Inbox when installed."""

    def setUp(self):
        super().setUp()
        if not apps.is_installed("evennia_notices"):
            self.skipTest("Inbox is physically optional")
        self.board = Board.objects.create(name="Activity")
        self.subscription = Subscription.objects.create(account=self.account, board=self.board)
        self.context = NoticeContext(self.account)

    def post(self, board=None, *, author=None, live=True):
        """Use the public creator with isolated on-commit dispatch."""
        with self.captureOnCommitCallbacks(execute=live):
            return Post.create_post(board or self.board, author, "Private title", "Private prose")

    def alerts(self):
        """Read live Inbox projection with no selected character."""
        from evennia_notices.services import project

        return project(self.context)

    def test_new_activity_replaces_only_its_board_alert(self):
        from evennia_notices.services import mutate

        other = Board.objects.create(name="Another board")
        Subscription.objects.create(account=self.account, board=other)
        first = self.post()
        second = self.post(other)
        third = self.post(author=self.char2)
        by_post = {row.events[0].payload["post"]: row for row in self.alerts()}
        self.assertEqual(set(by_post), {second.pk, third.pk})
        self.assertNotIn(first.pk, by_post)
        self.assertEqual(by_post[third.pk].text, "New activity on Activity")
        self.subscription.refresh_from_db()
        checkpoint = self.subscription.last_notified_at
        mutate(self.context, by_post[third.pk].notice.public_ref, "clear")
        prepare_account(self.account.pk)
        self.assertEqual([row.events[0].payload["post"] for row in self.alerts()], [second.pk])
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.last_notified_at, checkpoint)
        self.assertFalse(PostReadSuppression.objects.exists())
        self.assertIsNone(self.account.attributes.get("boards_web_read"))

    def test_own_posts_do_not_alert_or_renew_the_board_alert(self):
        self.account.characters.add(self.char1)
        self.post(author=self.char1)
        prepare_account(self.account.pk)
        self.assertEqual(self.alerts(), [])
        other = self.post(author=self.char2)
        self.post(author=self.char1)
        prepare_account(self.account.pk)
        self.assertEqual([row.events[0].payload["post"] for row in self.alerts()], [other.pk])

    def test_resubscribe_requires_fresh_inbox_activity(self):
        self.post()
        self.subscription.delete()
        sub = Subscription.objects.create(account=self.account, board=self.board)
        prepare_account(self.account.pk)
        self.assertEqual(self.alerts(), [])
        self.assertEqual(sub.unread_count(), 1)
        post = self.post()
        self.assertEqual(self.alerts()[0].events[0].payload["post"], post.pk)

    def test_hidden_and_temporarily_invalid_witnesses_do_not_consume_older_activity(self):
        from evennia_boards import notices

        older = self.post(live=False)
        newest = self.post(live=False)
        original = notices.transfer

        def invalidate(account, **kwargs):
            if kwargs["event"].payload["post"] == newest.pk:
                Post.all_objects.filter(pk=newest.pk).update(is_archived=True)
            return original(account, **kwargs)

        with patch.object(notices, "transfer", side_effect=invalidate):
            prepare_account(self.account.pk)
        self.assertEqual(self.alerts()[0].events[0].payload["post"], older.pk)

    def test_off_precedes_provider_failure(self):
        from evennia_notices.models import DeliveryReceipt
        from evennia_notices.services import set_preference

        set_preference(self.context, "boards", "off")
        with patch("evennia_links.ignoring.notice_ignore_status", return_value="defer"):
            post = self.post(author=self.char2)
        self.assertEqual(self.alerts(), [])
        self.assertEqual(DeliveryReceipt.objects.get(source="boards").disposition, "suppressed")
        set_preference(self.context, "boards", "summary")
        prepare_account(self.account.pk)
        self.assertEqual(self.alerts(), [])
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.discovery_post_id, post.pk)

    @override_settings(NOTICES_ROUTINE_LIMIT=1)
    def test_compaction_reevaluates_each_live_witness(self):
        from evennia_notices.models import NoticeEvent

        other = Board.objects.create(name="Other public board")
        Subscription.objects.create(account=self.account, board=other)
        self.post()
        self.post(other, author=self.char2)
        [item] = self.alerts()
        self.assertTrue(item.notice.is_compacted)
        self.assertEqual(len(item.events), 2)
        bad = NoticeEvent.objects.get(payload__board=other.pk)
        bad.actors = []
        bad.save(update_fields=["actors"])
        [item] = self.alerts()
        self.assertEqual(len(item.events), 1)
        self.assertEqual(item.text, "New activity on Activity")

    def test_previously_suppressed_duplicate_does_not_consume_older_valid_post(self):
        from evennia_boards.integrations.notices import POST_FIELDS, event_for
        from evennia_links.notices import notify
        from evennia_notices.services import set_preference

        first = self.post(live=False)
        second = self.post(live=False)
        row = Post.objects.values_list(*POST_FIELDS).get(pk=second.pk)
        set_preference(self.context, "boards", "off")
        result = notify(self.account, source="boards", event=event_for(self.subscription, row))
        self.assertEqual(result.status, "suppressed")
        set_preference(self.context, "boards", "summary")
        prepare_account(self.account.pk)
        self.assertEqual(self.alerts()[0].events[0].payload["post"], first.pk)

    def test_malformed_configured_source_does_not_fall_back(self):
        with (
            override_settings(LINKS_NOTICE_SOURCES={"boards": "broken.adapter.Source"}),
            connected_session(self.account) as session,
        ):
            post = self.post()
            with self.captureOnCommitCallbacks(execute=True):
                notify_login(self.account, session)
            session.msg.assert_not_called()
        self.assertFalse(StandaloneNoticeClaim.objects.exists())
        prepare_account(self.account.pk)
        self.assertEqual(self.alerts()[0].events[0].payload["post"], post.pk)

    def test_real_summary_and_immediate_listeners_use_one_owned_transport(self):
        from evennia.server.signals import SIGNAL_ACCOUNT_POST_LOGIN, SIGNAL_OBJECT_POST_PUPPET

        from evennia_notices.services import set_preference

        self.account.characters.add(self.char1)
        with connected_session(self.account) as session:
            session._notice_summaries = {}
            self.post()
            session.msg.assert_not_called()
            SIGNAL_ACCOUNT_POST_LOGIN.send(sender=self.account, session=session)
            session.get_puppet.return_value = self.char1
            SIGNAL_OBJECT_POST_PUPPET.send(sender=self.char1, session=session)
            self.assertEqual(session.msg.call_count, 1)
            self.assertIn("Notices: 1 unread alerts", session.msg.call_args.args[0])
            set_preference(self.context, "boards", "immediate")
            with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
                Post.create_post(self.board, None, "Private title", "Private prose")
                self.assertEqual(session.msg.call_count, 1)
            self.assertEqual(session.msg.call_count, 2)
            self.assertEqual(
                session.msg.call_args.args[0],
                "New activity on Activity\nUse +notices to read or manage this alert.",
            )
            set_preference(self.context, "boards", "off")
            self.post()
            self.assertEqual(session.msg.call_count, 2)

    def test_guest_disconnect_after_render_retries_without_durable_or_ephemeral_ack(self):
        from evennia.utils.create import create_account

        from evennia_boards.integrations.notices import BoardNoticeSource

        guest = create_account(
            "Disconnecting Boards Guest",
            None,
            "synthetic-password",
            typeclass="evennia.accounts.accounts.DefaultGuest",
        )
        subscription = Subscription.objects.create(account=guest, board=self.board)
        self.post(live=False)
        render = BoardNoticeSource.render
        with connected_session(guest) as session:
            session._boards_notice_positions = (None, {})

            def render_then_disconnect(source, events, context):
                value = render(source, events, context)
                session.get_account.return_value = None
                return value

            with patch.object(
                BoardNoticeSource, "render", autospec=True, side_effect=render_then_disconnect
            ):
                notify_login(guest, session)
            session.msg.assert_not_called()
            self.assertEqual(session._boards_notice_positions, (None, {}))
            session.get_account.return_value = guest
            notify_login(guest, session)
            session.msg.assert_called_once_with("New activity on Activity")
            notify_login(guest, session)
            session.msg.assert_called_once()
        subscription.refresh_from_db()
        self.assertIsNone(subscription.discovery_post_id)
        self.assertFalse(StandaloneNoticeClaim.objects.filter(account=guest).exists())

    def test_connected_guest_receives_strict_fresh_activity_ephemerally(self):
        from evennia.utils.create import create_account

        from evennia_notices.models import DeliveryReceipt

        guest = create_account(
            "Transient Boards Guest",
            None,
            "synthetic-password",
            typeclass="evennia.accounts.accounts.DefaultGuest",
        )
        subscription = Subscription.objects.create(account=guest, board=self.board)
        with connected_session(guest) as session:
            session._boards_notice_positions = (None, {})
            with patch("evennia_boards.notices.notice_ignore_status", return_value="suppress"):
                self.post(author=self.char2)
            session.msg.assert_not_called()
            self.post()
            notify_login(guest, session)
            session.msg.assert_called_once_with("New activity on Activity")
        subscription.refresh_from_db()
        self.assertIsNone(subscription.discovery_post_id)
        self.assertIsNone(subscription.last_notified_at)
        self.assertFalse(DeliveryReceipt.objects.filter(recipient__account=guest).exists())
        self.assertFalse(StandaloneNoticeClaim.objects.filter(account=guest).exists())
        self.assertFalse(PostReadSuppression.objects.filter(account=guest).exists())

    def test_retry_and_ambiguous_legacy_sender(self):
        with patch("evennia_boards.notices.notify", return_value=RouteResult("retry")):
            system = self.post()
        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.discovery_post_id)
        Post.objects.create(board=self.board, post_number=2, title="Old system?", content="secret")
        prepare_account(self.account.pk)
        self.assertEqual(self.alerts()[0].events[0].payload["post"], system.pk)
        system.archive()
        self.assertEqual(self.alerts(), [])

    def test_no_precommit_delivery_and_hard_deleted_display_number_reuse(self):
        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            post = Post.create_post(self.board, None, "Private title", "Private prose")
            self.assertEqual(self.alerts(), [])
        old_number = post.post_number
        old_id = post.pk
        post.delete()
        next_post = self.post()
        self.assertEqual(next_post.post_number, old_number)
        self.assertGreater(next_post.pk, old_id)
        self.assertEqual(self.alerts()[0].events[0].payload["post"], next_post.pk)

    def test_delayed_fresh_callback_does_not_silently_consume_next_post(self):
        from evennia_notices.models import DeliveryReceipt
        from evennia_notices.services import set_preference

        set_preference(self.context, "boards", "immediate")
        first = self.post(live=False)
        second = self.post(live=False)
        post_committed(self.board.pk, first.pk)
        self.assertEqual(self.alerts()[0].events[0].payload["post"], first.pk)
        post_committed(self.board.pk, second.pk)
        post_committed(self.board.pk, first.pk)
        self.assertEqual(self.alerts()[0].events[0].payload["post"], second.pk)
        self.assertFalse(
            DeliveryReceipt.objects.filter(source="boards", transfer_id__isnull=False).exists()
        )

    def test_no_write_standalone_scope_can_move_quietly_into_inbox(self):
        first = self.post(live=False)
        self.subscription.delete()
        self.subscription = Subscription.objects.create(account=self.account, board=self.board)
        newer = self.post(live=False)
        with (
            override_settings(NOTICES_ENABLED=False),
            connected_session(self.account) as session,
            self.captureOnCommitCallbacks(execute=True),
        ):
            notify_login(self.account, session)
            session.get_account.return_value = None
        self.assertEqual(StandaloneNoticeClaim.objects.get().status, "pending")
        prepare_account(self.account.pk)
        self.assertEqual(StandaloneNoticeClaim.objects.get().status, "transferred")
        self.assertEqual(self.alerts()[0].events[0].payload["post"], newer.pk)
        from evennia_notices.models import DeliveryReceipt

        self.assertFalse(DeliveryReceipt.objects.filter(event_id__endswith=f"-{first.pk}").exists())

    def test_pending_standalone_backlog_respects_new_subscription_inbox_start(self):
        self.subscription.delete()
        self.post(live=False)
        Subscription.objects.create(account=self.account, board=self.board)
        with (
            override_settings(NOTICES_ENABLED=False),
            connected_session(self.account) as session,
            self.captureOnCommitCallbacks(execute=True),
        ):
            notify_login(self.account, session)
            session.get_account.return_value = None
        self.assertEqual(StandaloneNoticeClaim.objects.get().status, "pending")
        prepare_account(self.account.pk)
        self.assertEqual(StandaloneNoticeClaim.objects.get().status, "transferred")
        self.assertEqual(self.alerts(), [])

    def test_acknowledged_ranges_survive_disabling_and_reenabling(self):
        self.post()
        with (
            override_settings(NOTICES_ENABLED=False),
            connected_session(self.account) as session,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                notify_login(self.account, session)
            session.msg.assert_not_called()
            standalone = self.post()
            with self.captureOnCommitCallbacks(execute=True):
                notify_login(self.account, session)
            self.assertIn("1 new post", session.msg.call_args.args[0])
        prepare_account(self.account.pk)
        post_ids = [row.events[0].payload["post"] for row in self.alerts()]
        self.assertNotIn(standalone.pk, post_ids)

    def test_legacy_checkpoint_and_inbox_projection_use_metadata_only(self):
        old = self.post(live=False)
        cutoff = timezone.now() - timedelta(hours=1)
        Post.all_objects.filter(pk=old.pk).update(created_at=cutoff)
        Subscription.objects.filter(pk=self.subscription.pk).update(
            last_notified_at=cutoff, inbox_start_post_id=None
        )
        newest = self.post(live=False)
        with CaptureQueriesContext(connection) as captured:
            prepare_account(self.account.pk)
            self.assertEqual(self.alerts()[0].events[0].payload["post"], newest.pk)
        self.assertFalse(
            any('"evennia_boards_post"."content"' in query["sql"] for query in captured)
        )


@override_settings(LINKS_NOTICE_SOURCES=SOURCE, NOTICES_ENABLED=False)
class StandaloneActivityTests(EvenniaTest):
    """Transport tests continue to run with Inbox and Social physically absent."""

    def setUp(self):
        super().setUp()
        self.board = Board.objects.create(name="Activity")
        self.subscription = Subscription.objects.create(account=self.account, board=self.board)
        self.post = Post.create_post(self.board, None, "First", "Prose")

    def test_session_loses_account_before_send_so_no_output_and_later_retry(self):
        with connected_session(self.account) as session:
            with self.captureOnCommitCallbacks(execute=True):
                notify_login(self.account, session)
                session.get_account.return_value = None
            session.msg.assert_not_called()
            self.assertEqual(StandaloneNoticeClaim.objects.get().status, "pending")
            self.subscription.refresh_from_db()
            self.assertIsNone(self.subscription.last_notified_at)
            session.get_account.return_value = self.account
            with self.captureOnCommitCallbacks(execute=True):
                notify_login(self.account, session)
            session.msg.assert_called_once()
            self.assertEqual(StandaloneNoticeClaim.objects.get().status, "delivered")

    def test_session_recheck_error_precedes_socket_attempt(self):
        from evennia_boards import notices

        with connected_session(self.account) as session:
            with (
                patch.object(
                    notices,
                    "_live_session",
                    side_effect=[True] * 4 + [ValueError("session changed")],
                ),
                self.captureOnCommitCallbacks(execute=True),
            ):
                notify_login(self.account, session)
            session.msg.assert_not_called()
            self.assertEqual(StandaloneNoticeClaim.objects.get().status, "pending")

    def test_post_claim_mutations_prevent_stale_standalone_counts(self):
        from evennia_boards import notices

        changes = {
            "archive": self.post.archive,
            "unsubscribe": lambda: Subscription.objects.filter(pk=self.subscription.pk).delete(),
            "receipt": lambda: PostReadSuppression.objects.create(
                account=self.account, post=self.post
            ),
        }
        live = notices._live_session
        for name, mutate in changes.items():
            with self.subTest(change=name), transaction.atomic():
                changed = False

                def revoke_after_reservation(session, account, mutate=mutate):
                    nonlocal changed
                    if (
                        not changed
                        and StandaloneNoticeClaim.objects.filter(status="attempting").exists()
                    ):
                        changed = True
                        mutate()
                    return live(session, account)

                with (
                    patch.object(notices, "_live_session", side_effect=revoke_after_reservation),
                    connected_session(self.account) as session,
                    self.captureOnCommitCallbacks(execute=True),
                ):
                    notify_login(self.account, session)
                self.assertTrue(changed)
                session.msg.assert_not_called()
                self.assertEqual(StandaloneNoticeClaim.objects.get().status, "pending")
                transaction.set_rollback(True)

    def test_prewrite_render_failure_and_locked_reset_recover_without_duplicate(self):
        from evennia_boards import notices

        finish = notices._finish_standalone
        attempts = []

        def finish_after_contention(*args):
            attempts.append(args[-1])
            if len(attempts) == 1:
                raise OperationalError("database is locked")
            finish(*args)

        def broken_render(_activity):
            self.assertEqual(StandaloneNoticeClaim.objects.get().status, "attempting")
            raise ValueError("render unavailable")

        with connected_session(self.account) as session:
            with (
                patch.object(notices, "_legacy_text", side_effect=broken_render),
                patch.object(notices, "_finish_standalone", side_effect=finish_after_contention),
                self.captureOnCommitCallbacks(execute=True),
            ):
                notify_login(self.account, session)
            session.msg.assert_not_called()
            self.assertEqual(attempts, ["pending", "pending"])
            self.assertEqual(StandaloneNoticeClaim.objects.get().status, "pending")
            self.subscription.refresh_from_db()
            self.assertIsNone(self.subscription.last_notified_at)
            for _ in range(2):
                with self.captureOnCommitCallbacks(execute=True):
                    notify_login(self.account, session)
            session.msg.assert_called_once()
        self.assertEqual(StandaloneNoticeClaim.objects.get().status, "delivered")

    def test_socket_failure_leaves_uncertainty_without_replay(self):
        with connected_session(self.account) as session:
            session.msg.side_effect = OSError("connection closed")
            with self.captureOnCommitCallbacks(execute=True):
                notify_login(self.account, session)
            self.assertEqual(StandaloneNoticeClaim.objects.get().status, "uncertain")
            with self.captureOnCommitCallbacks(execute=True):
                notify_login(self.account, session)
            session.msg.assert_called_once()

    def test_failure_on_one_session_does_not_stop_another(self):
        with connected_session(self.account) as first:
            second = Mock()
            second.get_account.return_value = self.account
            first.msg.side_effect = OSError("connection closed")
            with (
                patch(
                    "evennia.server.sessionhandler.SESSIONS.get_sessions",
                    return_value=[first, second],
                ),
                self.captureOnCommitCallbacks(execute=True),
            ):
                notify_login(self.account)
            first.msg.assert_called_once()
            second.msg.assert_called_once()
            self.assertEqual(StandaloneNoticeClaim.objects.get().status, "delivered")

    def test_stale_no_write_claim_does_not_starve_newer_activity(self):
        with connected_session(self.account) as session:
            with self.captureOnCommitCallbacks(execute=True):
                notify_login(self.account, session)
                session.get_account.return_value = None
            self.post.archive()
            Post.create_post(self.board, None, "Second", "Prose")
            session.get_account.return_value = self.account
            with self.captureOnCommitCallbacks(execute=True):
                notify_login(self.account, session)
            session.msg.assert_called_once()
        self.assertEqual(
            list(StandaloneNoticeClaim.objects.order_by("pk").values_list("status", flat=True)),
            ["pending", "delivered"],
        )

    def test_guest_scope_is_per_session_and_has_no_durable_writes(self):
        with (
            patch("evennia_boards.notices.is_guest", return_value=True),
            connected_session(self.account) as session,
        ):
            session._boards_notice_positions = (None, {})
            notify_login(self.account, session)
            notify_login(self.account, session)
            session.msg.assert_called_once()
        self.assertFalse(StandaloneNoticeClaim.objects.exists())
        self.assertFalse(PostReadSuppression.objects.exists())
        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.discovery_post_id)
        self.assertIsNone(self.subscription.last_notified_at)
