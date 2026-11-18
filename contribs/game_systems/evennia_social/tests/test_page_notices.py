# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Character page provenance and the single Inbox or connected delivery route."""

from datetime import timedelta
from importlib.util import find_spec
from io import StringIO
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.db import OperationalError, connection, transaction
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from evennia.comms.models import Msg
from evennia.utils.create import create_account, create_message, create_object

from evennia_links.notices import NoticeContext, RouteResult
from evennia_social import ignore, notices
from evennia_social.commands.messaging import CmdPage
from evennia_social.integrations.notices import GENERATION_TAG, SocialPageNoticeSource, stored_event
from evennia_social.models import PageDelivery
from evennia_social.tests.base import SocialTestCase

REGISTRY = {"social-pages": "evennia_social.integrations.notices.SocialPageNoticeSource"}
HAS_INBOX = find_spec("evennia_notices") is not None
SESSION_LIST = "evennia.server.sessionhandler.SESSIONS.get_sessions"


class PageFixture(SocialTestCase):
    def setUp(self):
        super().setUp()
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.char2.account = None

    def page(self, body="Sample private text", *targets):
        command = CmdPage()
        command.caller = self.char1
        with self.captureOnCommitCallbacks(execute=True):
            command._send_page(self.char1, list(targets) or [self.char2], body)
        return Msg.objects.latest("pk")

    def legacy(self, *, timestamp=None, body="Older private text", receiver=None, sender=None):
        receiver = receiver or self.char2
        page = create_message(
            sender or self.char1,
            body,
            receivers=[receiver],
            locks=f"read:id({receiver.pk})",
            tags=[("page", "comms")],
        )
        if timestamp is not None:
            Msg.objects.filter(pk=page.pk).update(db_date_created=timestamp)
        return page

    def login_session(self, *, account=None, character=None):
        session = Mock()
        session.get_account.return_value = account or self.account2
        session.get_puppet.return_value = character or self.char2
        return session


@override_settings(LINKS_NOTICE_SOURCES={})
class StandalonePageTests(PageFixture):
    def test_record_rollback_and_route_replay(self):
        live = self.char1
        live.account = self.account
        with (
            patch.object(live, "msg") as socket,
            patch.object(live.sessions, "count", return_value=1),
            self.captureOnCommitCallbacks(execute=True),
        ):
            with transaction.atomic():
                command = CmdPage()
                command.caller = self.char1
                command._send_page(self.char1, [live, self.char2], "Rolled back both receipts")
                transaction.set_rollback(True)
            self.assertEqual(socket.call_count, 2)
            self.assertIn("You paged", socket.call_args_list[0].args[0])
        self.assertFalse(Msg.objects.filter(db_message="Rolled back both receipts").exists())
        self.assertFalse(PageDelivery.objects.exists())

    def test_session_leaves_before_send_remains_pending(self):
        page = self.page()
        session = self.login_session()
        with patch(SESSION_LIST, return_value=[session]) as sessions:

            def disconnect(count):
                sessions.return_value = []
                return "Rendered reminder"

            with patch.object(notices, "_render_reminder", side_effect=disconnect):
                notices._standalone(self.char2)
            session.msg.assert_not_called()
            self.assertIsNone(self.char2.last_page_seen)
            self.assertEqual(PageDelivery.objects.get(message=page).state, "pending")
            sessions.return_value = [session]
            notices._standalone(self.char2)
            notices._standalone(self.char2)
        session.msg.assert_called_once_with(
            "|wYou have 1 unread page.|n Use |wpage/last 1|n to view."
        )
        self.assertEqual(PageDelivery.objects.get(message=page).state, "fallback")

    def test_finalizer_retries_unused_claim_before_next_connection(self):
        page = self.page()
        session = self.login_session()
        finish = notices._finish_fallback

        def disconnect(count):
            sessions.return_value = []
            return "Rendered reminder"

        def retry(*args):
            if finalizer.call_count == 1:
                raise OperationalError("database is locked")
            return finish(*args)

        with patch(SESSION_LIST, return_value=[session]) as sessions:
            with (
                patch.object(notices, "_render_reminder", side_effect=disconnect),
                patch.object(notices, "_finish_fallback", side_effect=retry) as finalizer,
            ):
                notices._standalone(self.char2)
            self.assertEqual(finalizer.call_count, 2)
            session.msg.assert_not_called()
            self.assertEqual(PageDelivery.objects.get(message=page).state, "pending")
            sessions.return_value = [session]
            notices._standalone(self.char2)
            notices._standalone(self.char2)
        session.msg.assert_called_once()
        self.assertEqual(PageDelivery.objects.get(message=page).state, "fallback")

    def test_finalizer_retry_preserves_uncertain_socket_without_replay(self):
        page = self.page()
        session = self.login_session()
        session.msg.side_effect = RuntimeError
        finish = notices._finish_fallback

        def retry(*args):
            if finalizer.call_count == 1:
                raise OperationalError("database is locked")
            return finish(*args)

        with (
            patch(SESSION_LIST, return_value=[session]),
            patch.object(notices, "_finish_fallback", side_effect=retry) as finalizer,
        ):
            notices._standalone(self.char2)
            self.assertEqual(PageDelivery.objects.get(message=page).state, "uncertain")
            notices._standalone(self.char2)
        self.assertEqual(finalizer.call_count, 2)
        session.msg.assert_called_once()
        self.assertEqual(PageDelivery.objects.get(message=page).state, "uncertain")

    def test_ownership_loss_releases_unused_claim(self):
        page = self.page()
        session = self.login_session()

        def lose_ownership(count):
            self.account2.characters.remove(self.char2)
            return "Rendered reminder"

        with patch(SESSION_LIST, return_value=[session]):
            with patch.object(notices, "_render_reminder", side_effect=lose_ownership):
                notices._standalone(self.char2)
            session.msg.assert_not_called()
            self.assertEqual(PageDelivery.objects.get(message=page).state, "pending")
            self.account2.characters.add(self.char2)
            notices._standalone(self.char2)
            notices._standalone(self.char2)
        session.msg.assert_called_once()
        self.assertEqual(PageDelivery.objects.get(message=page).state, "fallback")

    def test_puppet_dispatch_waits_for_outer_commit_including_guest(self):
        guest = create_account(
            "GuestRollbackFixture", None, None, typeclass="evennia.accounts.accounts.DefaultGuest"
        )
        for account, guest_mode in ((self.account2, False), (guest, True)):
            with self.subTest(guest=guest_mode):
                self.char2.account = account
                session = self.login_session(account=account)
                with (
                    patch(SESSION_LIST, return_value=[session]),
                    self.captureOnCommitCallbacks(execute=True),
                    transaction.atomic(),
                ):
                    self.legacy(body="Rollback-only page")
                    notices.puppet_reminder(self.char2)
                    session.msg.assert_not_called()
                    transaction.set_rollback(True)
                session.msg.assert_not_called()
                self.assertFalse(PageDelivery.objects.exists())
                self.assertFalse(Msg.objects.filter(db_message="Rollback-only page").exists())
                self.assertIsNone(self.char2.last_page_seen)
                self.assertIsNone(self.char2.ndb.social_page_claim)

    def test_broken_session_lookups_do_not_block_healthy_siblings(self):
        page = self.page()
        bad, good = self.login_session(), self.login_session()
        bad.get_account.side_effect = RuntimeError
        with patch(SESSION_LIST, return_value=[bad, good]):
            notices._standalone(self.char2)
        bad.msg.assert_not_called()
        good.msg.assert_called_once()
        self.assertEqual(PageDelivery.objects.get(message=page).state, "fallback")

    def test_writer_lookup_failure_leaves_claim_pending(self):
        page = self.page()
        bad, good = self.login_session(), self.login_session()

        class BadWriter:
            get_account = bad.get_account
            get_puppet = bad.get_puppet

            @property
            def msg(self):
                raise RuntimeError

        with patch(SESSION_LIST, return_value=[BadWriter()]) as sessions:
            notices._standalone(self.char2)
            self.assertEqual(PageDelivery.objects.get(message=page).state, "pending")
            sessions.return_value = [good]
            notices._standalone(self.char2)
        good.msg.assert_called_once()
        self.assertEqual(PageDelivery.objects.get(message=page).state, "fallback")

    def test_fallback_socket_attempt_uncertain_and_delivers_other_sessions(self):
        page = self.page()
        first, second = self.login_session(), self.login_session()
        first.msg.side_effect = RuntimeError
        with patch(SESSION_LIST, return_value=[first, second]):
            notices._standalone(self.char2)
            notices._standalone(self.char2)
        first.msg.assert_called_once()
        second.msg.assert_called_once()
        self.assertEqual(PageDelivery.objects.get(message=page).state, "fallback")
        other = self.page("Another offline sample")
        with patch(SESSION_LIST, return_value=[first]):
            notices._standalone(self.char2)
            notices._standalone(self.char2)
        self.assertEqual(first.msg.call_count, 2)
        self.assertEqual(PageDelivery.objects.get(message=other).state, "uncertain")

    def test_renderer_failure_and_cutoff_and_live_aggregate(self):
        now = timezone.now()
        self.char2.last_page_seen = (now - timedelta(days=1)).isoformat()
        self.legacy(timestamp=now - timedelta(days=2))
        self.legacy(timestamp=now - timedelta(days=1))
        visible = self.legacy(timestamp=now)
        revoked = self.legacy(timestamp=now)
        revoked.locks.add("read:false()")
        self.char2.account = self.account2
        with patch.object(self.char2.sessions, "count", return_value=1):
            live = self.page()
        session = self.login_session()
        with patch(SESSION_LIST, return_value=[session]):
            with patch.object(notices, "_render_reminder", side_effect=ValueError):
                notices._standalone(self.char2)
            session.msg.assert_not_called()
            self.assertEqual(PageDelivery.objects.get(message=visible).state, "pending")
            notices._standalone(self.char2)
        session.msg.assert_called_once_with(
            "|wYou have 2 unread pages.|n Use |wpage/last 2|n to view."
        )
        self.assertEqual(PageDelivery.objects.get(message=live).origin, "live")
        self.assertEqual(PageDelivery.objects.filter(state="fallback").count(), 2)

    def test_fallback_retires_invalid_and_all_owner_suppressed_but_keeps_deferral(self):
        visible = self.legacy()
        invalid = self.legacy()
        invalid.locks.add("read:false()")
        blocked_account = create_account("Blocked Page Fixture", None, None)
        blocked = create_object(self.character_typeclass, key="Blocked Page Sender")
        blocked_account.characters.add(blocked)
        ignore.set_entry(self.account2, blocked)
        hidden = self.legacy(sender=blocked)
        temporary = create_object(self.character_typeclass, key="Temporary Page Sender")
        deferred = self.legacy(sender=temporary)
        session = self.login_session()

        from evennia_links.ignoring import notice_ignore_status

        def policy(viewer, sender, **kwargs):
            if sender == temporary:
                return "defer"
            return notice_ignore_status(viewer, sender, **kwargs)

        with patch(SESSION_LIST, return_value=[session]):
            with patch("evennia_links.ignoring.notice_ignore_status", side_effect=policy):
                notices._standalone(self.char2)
                notices._standalone(self.char2)
                session.msg.assert_called_once()
                self.assertEqual(
                    dict(PageDelivery.objects.values_list("message_id", "state")),
                    {
                        visible.pk: "fallback",
                        invalid.pk: "suppressed",
                        hidden.pk: "suppressed",
                        deferred.pk: "pending",
                    },
                )
            ignore.remove_entry(self.account2, blocked)
            notices._standalone(self.char2)
        self.assertEqual(session.msg.call_count, 2)
        self.assertEqual(PageDelivery.objects.get(message=deferred).state, "fallback")
        self.assertEqual(PageDelivery.objects.get(message=hidden).state, "suppressed")

    def test_standalone_counts_more_than_one_preparation_batch(self):
        for _ in range(101):
            self.legacy()
        session = self.login_session()
        with patch(SESSION_LIST, return_value=[session]):
            notices._standalone(self.char2)
            notices._standalone(self.char2)
        session.msg.assert_called_once_with(
            "|wYou have 101 unread pages.|n Use |wpage/last 101|n to view."
        )
        self.assertEqual(PageDelivery.objects.filter(state="fallback").count(), 101)

    def test_game_without_registry_preserves_broken_binding_for_retry(self):
        page = self.page()
        session = self.login_session()
        with (
            self.settings(LINKS_NOTICE_SOURCES={"social-pages": "absent.bindings.Adapter"}),
            patch(SESSION_LIST, return_value=[session]),
        ):
            notices._standalone(self.char2)
        session.msg.assert_not_called()
        self.assertEqual(PageDelivery.objects.get(message=page).state, "pending")

    def test_guest_session_drops_before_write_can_resume(self):
        guest = create_account(
            "GuestPageFixture", None, None, typeclass="evennia.accounts.accounts.DefaultGuest"
        )
        self.char2.account = guest
        self.char2.tags.add("character", category="guest")
        self.legacy()
        session = self.login_session(account=guest)
        with patch(SESSION_LIST, return_value=[session]) as sessions:

            def disconnect(count):
                sessions.return_value = []
                return "Rendered guest reminder"

            with (
                patch.object(notices, "_render_reminder", side_effect=disconnect),
                self.captureOnCommitCallbacks(execute=True),
            ):
                notices.puppet_reminder(self.char2)
            session.msg.assert_not_called()
            sessions.return_value = [session]
            with self.captureOnCommitCallbacks(execute=True):
                notices.puppet_reminder(self.char2)
                notices.puppet_reminder(self.char2)
            reconnected = self.login_session(account=guest)
            sessions.return_value = [reconnected]
            with self.captureOnCommitCallbacks(execute=True):
                notices.puppet_reminder(self.char2)
            reconnected.msg.assert_called_once()
        session.msg.assert_called_once_with(
            "|wYou have 1 unread page.|n Use |wpage/last 1|n to view."
        )
        self.assertFalse(PageDelivery.objects.exists())
        self.assertIsNone(self.char2.last_page_seen)

    def test_live_disconnect_before_write_routes_offline(self):
        self.char2.account = self.account2
        with (
            patch.object(self.char2, "msg") as socket,
            patch.object(self.char2.sessions, "count", side_effect=(1, 0)),
            self.captureOnCommitCallbacks(execute=True),
        ):
            command = CmdPage()
            command.caller = self.char1
            command._send_page(self.char1, [self.char2], "Sample across disconnect")
            self.char2.account = None
        socket.assert_not_called()
        self.assertEqual(PageDelivery.objects.get().origin, "offline")


@skipUnless(HAS_INBOX, "Inbox package required")
@override_settings(LINKS_NOTICE_SOURCES=REGISTRY, NOTICES_ENABLED=True)
class InboxPageTests(PageFixture):
    def context(self):
        return NoticeContext(self.account2, self.char2)

    def test_page_transport_population(self):
        live_owner = create_account("Live Page Fixture", None, None)
        live = create_object(self.character_typeclass, key="Live Page Recipient")
        live_owner.characters.add(live)
        live.account = live_owner
        ignored_owner = create_account("Ignored Page Fixture", None, None)
        ignored = create_object(self.character_typeclass, key="Ignored Page Recipient")
        ignored_owner.characters.add(ignored)
        ignored.db.account = ignored_owner
        ignore.set_entry(ignored_owner, self.char1)
        self.account.permissions.clear()
        self.account2.permissions.add("Builder")
        with (
            patch.object(live.sessions, "count", return_value=1),
            patch.object(live, "msg") as live_socket,
            patch.object(self.account2, "msg") as account_socket,
        ):
            multi = self.page("Multi-recipient source body", live, self.char2, ignored)
            account_page = self.page("Account-only reply body", self.account2)
        live_socket.assert_called_once()
        account_socket.assert_called_once()
        self.assertTrue(multi.db_hide_from_objects.filter(pk=ignored.pk).exists())
        self.assertTrue(account_page.db_receivers_accounts.filter(pk=self.account2.pk).exists())
        self.assertEqual(
            list(PageDelivery.objects.values_list("character_id", "message_id", "state")),
            [(self.char2.pk, multi.pk, "inbox")],
        )

    def test_populated_cutoff_transfer_and_retry_are_idempotent(self):
        from evennia_notices.models import DeliveryReceipt

        cutoff = timezone.now() - timedelta(days=1)
        self.char2.last_page_seen = cutoff.isoformat()
        self.legacy(timestamp=cutoff - timedelta(seconds=1))
        self.legacy(timestamp=cutoff)
        pending = self.legacy(timestamp=cutoff + timedelta(seconds=1))
        with patch.object(notices, "transfer", return_value=RouteResult("retry")):
            self.assertEqual(notices.prepare(self.context())[0]["retry"], 1)
        self.assertEqual(PageDelivery.objects.get().message, pending)
        self.assertEqual(notices.prepare(self.context())[0]["inbox"], 1)
        notices.prepare(self.context())
        self.assertEqual(DeliveryReceipt.objects.count(), 1)
        self.assertEqual(self.char2.last_page_seen, cutoff.isoformat())

    def test_clean_prepare_fallback_waits_for_outer_commit(self):
        session = self.login_session()
        with (
            patch(SESSION_LIST, return_value=[session]),
            patch.object(notices, "transfer", return_value=RouteResult("fallback_pending")),
            self.captureOnCommitCallbacks(execute=True),
            transaction.atomic(),
        ):
            self.legacy(body="Rollback-only prepared page")
            counts, _ = notices.prepare(self.context(), allow_fallback=True)
            self.assertEqual(counts["fallback_pending"], 1)
            session.msg.assert_not_called()
            transaction.set_rollback(True)
        session.msg.assert_not_called()
        self.assertFalse(PageDelivery.objects.exists())
        self.assertFalse(Msg.objects.filter(db_message="Rollback-only prepared page").exists())

    def test_explicit_character_bounded_transfer_resumes(self):
        from evennia_notices.models import DeliveryReceipt

        self.legacy()
        self.legacy()
        for _ in range(2):
            output = StringIO()
            call_command(
                "transfer_social_page_notices", character=self.char2.dbref, limit=1, stdout=output
            )
            self.assertIn("inbox=1", output.getvalue())
        self.assertEqual(DeliveryReceipt.objects.count(), 2)

    def test_new_live_page_is_never_imported_after_enable(self):
        from evennia_notices.models import DeliveryReceipt

        self.char2.account = self.account2
        with self.settings(NOTICES_ENABLED=False):
            with patch.object(self.char2.sessions, "count", return_value=1):
                live = self.page("Live history")
            self.char2.account = None
            offline = self.page("Offline history")
        Msg.objects.filter(pk=live.pk).update(db_date_created=offline.db_date_created)
        self.assertTrue(live.tags.has(*GENERATION_TAG))
        notices.prepare(self.context())
        self.assertEqual(DeliveryReceipt.objects.count(), 1)
        self.assertEqual(PageDelivery.objects.get().message, offline)

    def test_disabled_duplicate_and_reenable_do_not_replay(self):
        from evennia_notices.models import DeliveryReceipt

        page = self.page()
        row = PageDelivery.objects.get(message=page)
        self.assertEqual(row.state, "inbox")
        PageDelivery.objects.filter(pk=row.pk).update(state="pending")
        session = self.login_session()
        with self.settings(NOTICES_ENABLED=False), patch(SESSION_LIST, return_value=[session]):
            notices._standalone(self.char2)
        session.msg.assert_not_called()
        self.assertEqual(PageDelivery.objects.get(pk=row.pk).state, "inbox")
        self.assertEqual(DeliveryReceipt.objects.count(), 1)

    @override_settings(NOTICES_ROUTINE_LIMIT=1)
    def test_batch_visibility_and_compaction(self):
        from evennia_notices.services import project

        visible = self.page()
        revoked_pages = [self.page() for _ in range(5)]
        self.assertEqual(project(self.context())[0].text, "You received pages while offline.")
        for revoked in revoked_pages:
            revoked.locks.add("read:false()")
        self.assertEqual(len(project(self.context())), 1)
        self.assertEqual(project(self.context())[0].text, "You received a page while offline.")
        self.assertEqual(Msg.objects.get(pk=visible.pk).db_message, "Sample private text")
        row = PageDelivery.objects.get(message=visible)
        event = stored_event(row)
        source = SocialPageNoticeSource()
        outcome = source.evaluate([event], NoticeContext(None, self.char2))
        self.assertEqual(outcome[event.event_id].reason, "context")
        batch = [stored_event(row) for row in PageDelivery.objects.all()]
        with CaptureQueriesContext(connection) as queries:
            outcomes = source.evaluate(batch, self.context())
        self.assertLessEqual(len(queries), 10)
        self.assertTrue(all('"db_message"' not in query["sql"] for query in queries))
        self.assertEqual(
            sorted(item.status for item in outcomes.values()), ["hidden"] * 5 + ["visible"]
        )

    def test_added_and_removed_ignore_snapshots_existing_pending_owner(self):
        from evennia_notices.models import DeliveryReceipt
        from evennia_notices.services import project

        self.account.permissions.clear()
        co_owner = create_account("Pending Co-Owner Fixture", None, None)
        co_owner.characters.add(self.char2)
        with patch.object(notices, "notify", return_value=RouteResult("retry")):
            page = self.page()
        row = PageDelivery.objects.get(message=page)
        self.assertEqual(row.suppressed_owners, [])
        self.assertFalse(DeliveryReceipt.objects.exists())
        ignore.set_entry(self.account2, self.char1, ignore.HIDDEN)
        self.assertFalse(DeliveryReceipt.objects.exists())
        ignore.remove_entry(self.account2, self.char1)
        row.refresh_from_db()
        self.assertEqual(row.suppressed_owners, [self.account2.pk])
        self.assertFalse(DeliveryReceipt.objects.exists())
        self.assertEqual(notices.prepare(self.context())[0]["inbox"], 1)
        self.assertEqual(project(self.context()), [])
        self.assertEqual(len(project(NoticeContext(co_owner, self.char2))), 1)
        self.assertTrue(page.db_receivers_objects.filter(pk=self.char2.pk).exists())
        self.assertFalse(page.db_hide_from_objects.filter(pk=self.char2.pk).exists())

    def test_pending_ignored_before_receipt_does_not_revive(self):
        from evennia_notices.services import project

        alt = create_object(self.character_typeclass, key="Sender Alt")
        self.account.characters.add(alt)
        self.account.permissions.remove("Developer")
        self.account2.characters.add(self.char2)
        third = create_account("OtherFixtureOwner", None, None)
        third.characters.add(self.char2)
        ignore.set_entry(self.char2 if self.char2.account else self.account2, alt, ignore.HIDDEN)
        with patch.object(notices, "notify", return_value=RouteResult("retry")):
            page = self.page()
        ignore.remove_entry(self.account2, alt)
        notices.prepare(self.context())
        self.assertEqual(project(self.context()), [])
        self.assertEqual(len(project(NoticeContext(third, self.char2))), 1)
        self.assertIn(self.char2, page.receivers)
