# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Exercise Plots notices through shared source writes and real Inbox projection."""

from importlib.util import find_spec
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.db import OperationalError, connection, transaction
from django.test import override_settings
from evennia.utils.create import create_account, create_object
from evennia.utils.test_resources import EvenniaTest

from evennia_links.ignoring import ignore_mode_requested, notify_ignore_policy_changing
from evennia_links.notices import NoticeContext, RouteResult, evaluate
from evennia_plots import notices, threads
from evennia_plots.integrations.notices import PlotNoticeSource, Witnesses, stored_event
from evennia_plots.models import PlotNoticeReceipt, PlotThread, StoryThread

REGISTRY = {"plots": "evennia_plots.integrations.notices.PlotNoticeSource"}
HAS_INBOX = find_spec("evennia_notices") is not None
HAS_SOCIAL = find_spec("evennia_social") is not None
SESSION_LIST = "evennia.server.sessionhandler.SESSIONS.get_sessions"
State = PlotNoticeReceipt.State
Kind = PlotNoticeReceipt.Kind


def connected(account, character):
    session = Mock(logged_in=True)
    session.get_account.return_value = account
    session.get_puppet.return_value = character
    return session


class PlotNoticeFixture(EvenniaTest):
    def setUp(self):
        super().setUp()
        sessions = patch(SESSION_LIST, return_value=[])
        sessions.start()
        self.addCleanup(sessions.stop)
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.char2.account = None
        self.requester = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Notice requester", nohome=True
        )
        self.account2.characters.add(self.requester)
        # The default Evennia fixture configures the first character as staff.
        self.plot = PlotThread.create_thread(
            "Confidential plot name", self.char1, thread_policy=PlotThread.ThreadPolicy.REQUEST
        )
        self.plot.activate()

    def request(self, title="Original request"):
        with self.captureOnCommitCallbacks(execute=True):
            return threads.add_thread(self.plot, self.requester, title)

    def puppet(self, character, session):
        with self.captureOnCommitCallbacks(execute=True):
            notices._puppet(character, session=session)


@override_settings(LINKS_NOTICE_SOURCES={})
class StandalonePlotNoticeTests(PlotNoticeFixture):
    def test_offline_standalone_is_terminal_and_rollback_is_silent(self):
        request = self.request()
        self.assertEqual(PlotNoticeReceipt.objects.get().state, State.STANDALONE_OFFLINE)
        puppet = connected(self.account, self.char1)
        with patch(SESSION_LIST, return_value=[puppet]):
            self.puppet(self.char1, puppet)
            with self.captureOnCommitCallbacks(execute=True) as callbacks, transaction.atomic():
                threads.accept(request, self.char1)
                transaction.set_rollback(True)
            self.assertEqual(callbacks, [])
        puppet.msg.assert_not_called()
        request.refresh_from_db()
        self.assertEqual(request.status, StoryThread.Status.REQUESTED)
        self.assertEqual(PlotNoticeReceipt.objects.count(), 1)

    def test_legacy_copy_goes_to_exact_puppet_only(self):
        puppet = connected(self.account, self.char1)
        account_select = connected(self.account, None)
        unrelated = connected(self.account2, self.char1)
        with patch(SESSION_LIST, return_value=[account_select, unrelated, puppet]):
            request = self.request()
            self.puppet(self.char1, puppet)
        puppet.msg.assert_called_once()
        self.assertIn(f"+thread/accept {request.ref}", puppet.msg.call_args.args[0])
        account_select.msg.assert_not_called()
        unrelated.msg.assert_not_called()
        self.assertEqual(PlotNoticeReceipt.objects.get().state, State.FALLBACK_DELIVERED)

    def test_session_leaves_after_claim_and_later_puppet_sends_once(self):
        first = connected(self.account, self.char1)
        second = connected(self.account, self.char1)
        presentation = Witnesses.presentation
        with patch(SESSION_LIST, return_value=[first]) as sessions:

            def disconnect(*args, **kwargs):
                sessions.return_value = []
                return presentation(*args, **kwargs)

            with patch.object(Witnesses, "presentation", autospec=True, side_effect=disconnect):
                self.request()
            first.msg.assert_not_called()
            self.assertEqual(PlotNoticeReceipt.objects.get().state, State.PENDING)
            sessions.return_value = [second]
            self.puppet(self.char1, second)
            self.puppet(self.char1, second)
        second.msg.assert_called_once()
        self.assertEqual(PlotNoticeReceipt.objects.get().state, State.FALLBACK_DELIVERED)

    def test_missing_writer_can_retry_and_second_connection_can_succeed(self):
        first = connected(self.account, self.char1)
        first.msg = None
        with patch(SESSION_LIST, return_value=[first]) as sessions:
            self.request()
            self.assertEqual(PlotNoticeReceipt.objects.get().state, State.PENDING)
            first.msg = Mock(side_effect=OSError)
            second = connected(self.account, self.char1)
            sessions.return_value = [first, second]
            self.puppet(self.char1, second)
        first.msg.assert_called_once()
        second.msg.assert_called_once()
        self.assertEqual(PlotNoticeReceipt.objects.get().state, State.FALLBACK_DELIVERED)

    def test_uncertain_is_only_for_started_writes_and_finalizer_retries_without_send(self):
        first = connected(self.account, self.char1)
        first.msg.side_effect = OSError
        finalize = notices._finalize

        def locked_once(*args, **kwargs):
            if finalizer.call_count == 1 and connection.vendor == "sqlite":
                raise OperationalError("database is locked")
            return finalize(*args, **kwargs)

        with (
            patch(SESSION_LIST, return_value=[first]),
            patch.object(notices, "_finalize", side_effect=locked_once) as finalizer,
        ):
            self.request()
            self.puppet(self.char1, first)
        first.msg.assert_called_once()
        self.assertEqual(finalizer.call_count, 2 if connection.vendor == "sqlite" else 1)
        self.assertEqual(PlotNoticeReceipt.objects.get().state, State.UNCERTAIN)

    def test_exhausted_finalizer_retries_never_repeat_a_known_write(self):
        first = connected(self.account, self.char1)
        second = connected(self.account, self.char1)
        no_call = connected(self.account, self.char1)
        no_call.msg = None
        with (
            patch(SESSION_LIST, return_value=[no_call]) as sessions,
            patch.object(notices, "_finalize", side_effect=OperationalError("database is locked")),
        ):
            pending = self.request("No transport")
            self.assertEqual(PlotNoticeReceipt.objects.get(thread=pending).state, State.ATTEMPTING)
            sessions.return_value = [first]
            delivered = self.request("Known write")
            self.assertEqual(
                PlotNoticeReceipt.objects.get(thread=delivered).state, State.ATTEMPTING
            )
        first.msg.assert_called_once()
        with patch(SESSION_LIST, return_value=[second]):
            self.puppet(self.char1, second)
            self.puppet(self.char1, second)
        second.msg.assert_called_once()
        self.assertIn(pending.ref, second.msg.call_args.args[0])
        self.assertEqual(
            set(PlotNoticeReceipt.objects.values_list("state", flat=True)),
            {State.FALLBACK_DELIVERED},
        )

    def test_legacy_closed_but_requested_rows_can_be_declined_and_withdrawn(self):
        decline = self.request()
        withdraw = self.request("Withdraw this old request")
        PlotThread.objects.filter(pk=self.plot.pk).update(status=PlotThread.Status.ARCHIVED)
        with self.assertRaises(threads.ThreadError):
            threads.accept(decline, self.char1)
        with self.captureOnCommitCallbacks(execute=True):
            threads.decline(decline, self.char1)
            before = withdraw.ref
            self.assertEqual(threads.withdraw(withdraw, self.requester), before)
        self.assertEqual(decline.status, StoryThread.Status.DECLINED)
        self.assertEqual(PlotNoticeReceipt.objects.filter(kind=Kind.DECLINE).count(), 1)

    def test_transient_keeps_emission_and_pending_ignore_masks(self):
        target = create_object("evennia.DefaultCharacter", key="Ignored transient", nohome=True)
        puppet = connected(self.account2, target)
        ignored = True

        def ignore(sender, viewer, sender_object, kind, **kwargs):
            if ignored and viewer == self.account2 and sender_object == self.char1:
                return "hide"
            return None

        ignore_mode_requested.connect(ignore)
        self.addCleanup(ignore_mode_requested.disconnect, ignore)
        with patch(SESSION_LIST, return_value=[puppet]):
            with self.captureOnCommitCallbacks(execute=True):
                threads.add_owner(self.plot, self.char1, target)
                ignored = False
            puppet.msg.assert_not_called()
            threads.remove_owner(self.plot, self.char1, target)

            # The viewer was eligible at emission, but the socket could not
            # send; a later ignore and unignore must survive the pending retry.
            writer = puppet.msg
            puppet.msg = None
            with self.captureOnCommitCallbacks(execute=True):
                threads.add_owner(self.plot, self.char1, target)
            ignored = True
            with self.captureOnCommitCallbacks(execute=True):
                notify_ignore_policy_changing(self.account2, "notices")
                ignored = False
            puppet.msg = writer
            self.puppet(target, puppet)
        writer.assert_not_called()
        self.assertFalse(PlotNoticeReceipt.objects.exists())

    def test_transient_suppression_after_render_is_consumed_without_a_write(self):
        target = create_object("evennia.DefaultCharacter", key="Transient write gate", nohome=True)
        puppet = connected(self.account2, target)
        presentation = Witnesses.presentation
        ignored = False

        def ignore(sender, viewer, sender_object, kind, **kwargs):
            if ignored and viewer == self.account2:
                return "hide"
            return None

        def changed(*args, **kwargs):
            nonlocal ignored
            ignored = True
            return presentation(*args, **kwargs)

        ignore_mode_requested.connect(ignore)
        self.addCleanup(ignore_mode_requested.disconnect, ignore)
        with patch(SESSION_LIST, return_value=[puppet]):
            with (
                patch.object(Witnesses, "presentation", autospec=True, side_effect=changed),
                self.captureOnCommitCallbacks(execute=True),
            ):
                threads.add_owner(self.plot, self.char1, target)
            ignored = False
            self.puppet(target, puppet)
        puppet.msg.assert_not_called()

    def test_real_guest_is_transient_and_checks_latest_authenticated_identity(self):
        guest = create_account(
            "Plot guest",
            "plot-guest@fixture.test",
            "twenty-giant-falcons-83",
            typeclass="evennia.DefaultGuest",
        )
        target = create_object("evennia.DefaultCharacter", key="Guest target", nohome=True)
        target.account = guest
        puppet = connected(guest, target)
        with (
            patch(SESSION_LIST, return_value=[puppet]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            threads.add_owner(self.plot, self.char1, target)
        puppet.msg.assert_called_once()
        self.assertFalse(PlotNoticeReceipt.objects.exists())

        threads.remove_owner(self.plot, self.char1, target)
        puppet.msg.reset_mock()
        with (
            patch(SESSION_LIST, return_value=[puppet]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            threads.add_owner(self.plot, self.char1, target)
            puppet.get_account.return_value = self.account2
        puppet.msg.assert_not_called()
        self.assertFalse(PlotNoticeReceipt.objects.exists())

    def test_nonroster_puppet_is_transient_and_roster_appearance_aborts_send(self):
        target = create_object("evennia.DefaultCharacter", key="Nonroster target", nohome=True)
        puppet = connected(self.account, target)
        select = connected(self.account, None)
        with (
            patch(SESSION_LIST, return_value=[puppet, select]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            threads.add_owner(self.plot, self.char1, target)
        puppet.msg.assert_called_once()
        select.msg.assert_not_called()
        self.assertFalse(PlotNoticeReceipt.objects.exists())

        threads.remove_owner(self.plot, self.char1, target)
        puppet.msg.reset_mock()
        with (
            patch(SESSION_LIST, return_value=[puppet]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            threads.add_owner(self.plot, self.char1, target)
            self.account2.characters.add(target)
        puppet.msg.assert_not_called()
        self.assertFalse(PlotNoticeReceipt.objects.exists())


@skipUnless(HAS_INBOX, "Inbox physically absent")
@override_settings(LINKS_NOTICE_SOURCES=REGISTRY, NOTICES_ENABLED=True)
class InboxPlotNoticeTests(PlotNoticeFixture):
    def project(self, account=None, character=None):
        from evennia_notices.services import project

        return project(NoticeContext(account or self.account, character or self.char1))

    def test_request_fanout_records_owner_generation_and_exact_character(self):
        with self.captureOnCommitCallbacks(execute=True):
            second_owner = threads.add_owner(self.plot, self.char1, self.char2)
        request = self.request()
        rows = PlotNoticeReceipt.objects.filter(kind=Kind.REQUEST, thread=request)
        self.assertEqual(
            set(rows.values_list("character_id", flat=True)), {self.char1.pk, self.char2.pk}
        )
        self.assertTrue(rows.filter(owner=second_owner).exists())
        self.assertEqual(len(self.project()), 1)
        self.assertEqual(len(self.project(self.account2, self.char2)), 2)
        self.assertFalse(self.project(self.account2, self.requester))
        from evennia_notices.services import project

        self.assertFalse(project(NoticeContext(self.account)))
        threads.remove_owner(self.plot, self.char1, self.char2)
        with self.captureOnCommitCallbacks(execute=True):
            replacement = threads.add_owner(self.plot, self.char1, self.char2)
        self.assertNotEqual(second_owner.pk, replacement.pk)
        self.assertFalse(rows.filter(owner=replacement).exists())
        self.assertEqual(len(self.project(self.account2, self.char2)), 1)

    def test_explicit_decisions_follow_lifecycle_and_permission(self):
        accepted = self.request()
        declined = self.request("Other request")
        silent = self.request("Unanswered request")
        with self.captureOnCommitCallbacks(execute=True):
            self.assertIs(threads.accept(accepted, self.char1), accepted)
            threads.decline(declined, self.char1, "Private decision prose")
        self.assertEqual(accepted.status, StoryThread.Status.OPEN)
        self.plot.archive()
        accepted.refresh_from_db()
        silent.refresh_from_db()
        self.assertEqual(accepted.status, StoryThread.Status.LOOSE_END)
        self.assertEqual(silent.status, StoryThread.Status.DECLINED)
        self.assertIsNone(silent.decided_by_id)
        self.assertFalse(self.project())
        projected = self.project(self.account2, self.requester)
        self.assertEqual(len(projected), 2)
        self.assertNotIn("Private decision prose", repr([item.text for item in projected]))
        self.plot.privacy = PlotThread.Privacy.PRIVATE
        self.plot.save(update_fields=["privacy"])
        self.assertFalse(self.project(self.account2, self.requester))

    def test_private_inbox_text_uses_only_safe_commands_and_rechecks_deleted_actor(self):
        request = self.request("Secret request title")
        self.plot.privacy = PlotThread.Privacy.PRIVATE
        self.plot.save(update_fields=["privacy"])
        [item] = self.project()
        self.assertIn("private plot", item.text)
        for secret in ("Confidential plot name", "Secret request title", self.requester.key):
            self.assertNotIn(secret, item.text)
        self.assertEqual(item.actions[0][1], f"+thread {request.ref}")
        self.assertIsNone(item.actions[0][2])
        self.account2.characters.remove(self.requester)
        self.requester.delete()
        self.assertFalse(self.project())

    def test_retry_transfers_quietly_and_offline_standalone_never_transfers(self):
        from evennia_notices.models import DeliveryReceipt, SourcePreference

        with override_settings(NOTICES_ENABLED=False):
            self.request("Offline with no backend")
        with patch.object(notices, "notify", return_value=RouteResult("retry")):
            request = self.request("Active backend deferred")
        SourcePreference.objects.create(account=self.account, source="plots", mode="immediate")
        puppet = connected(self.account, self.char1)
        with (
            patch(SESSION_LIST, return_value=[puppet]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            notices.prepare(NoticeContext(self.account, self.char1, puppet))
        puppet.msg.assert_not_called()
        receipt = DeliveryReceipt.objects.get(source="plots")
        self.assertEqual(receipt.event_id, PlotNoticeReceipt.objects.get(thread=request).event_key)
        self.assertEqual(receipt.transfer_id, receipt.event_id)
        self.assertEqual(
            set(PlotNoticeReceipt.objects.values_list("state", flat=True)),
            {State.INBOX, State.STANDALONE_OFFLINE},
        )

    def test_backend_restoration_between_claim_and_write_transfers_quietly(self):
        from django.conf import settings

        from evennia_notices.models import DeliveryReceipt

        puppet = connected(self.account, self.char1)
        presentation = Witnesses.presentation

        def restore(*args, **kwargs):
            settings.NOTICES_ENABLED = True
            return presentation(*args, **kwargs)

        with (
            override_settings(NOTICES_ENABLED=False),
            patch(SESSION_LIST, return_value=[puppet]),
        ):
            with patch.object(Witnesses, "presentation", autospec=True, side_effect=restore):
                request = self.request()
            puppet.msg.assert_not_called()
            self.assertEqual(PlotNoticeReceipt.objects.get(thread=request).state, State.PENDING)
            with self.captureOnCommitCallbacks(execute=True):
                notices.prepare(NoticeContext(self.account, self.char1, puppet))
        puppet.msg.assert_not_called()
        row = PlotNoticeReceipt.objects.get(thread=request)
        self.assertEqual(row.state, State.INBOX)
        self.assertEqual(DeliveryReceipt.objects.get(source="plots").transfer_id, row.event_key)

    def test_broken_binding_never_falls_back_even_with_connected_character(self):
        puppet = connected(self.account, self.char1)
        with (
            override_settings(LINKS_NOTICE_SOURCES={"plots": "missing.module.Plots"}),
            patch(SESSION_LIST, return_value=[puppet]),
        ):
            self.request()
        puppet.msg.assert_not_called()
        self.assertEqual(PlotNoticeReceipt.objects.get().state, State.PENDING)

    def test_live_immediate_off_and_clear_dont_change_source_state(self):
        from evennia_notices.models import DeliveryReceipt, SourcePreference
        from evennia_notices.services import mutate

        puppet = connected(self.account, self.char1)
        SourcePreference.objects.create(account=self.account, source="plots", mode="immediate")
        with patch(SESSION_LIST, return_value=[puppet]):
            request = self.request()
        puppet.msg.assert_called_once()
        [item] = self.project()
        mutate(NoticeContext(self.account, self.char1), item.notice.public_ref, "clear")
        self.assertFalse(self.project())
        self.assertEqual(PlotNoticeReceipt.objects.get(thread=request).state, State.INBOX)
        self.assertEqual(
            StoryThread.objects.get(pk=request.pk).status, StoryThread.Status.REQUESTED
        )
        SourcePreference.objects.filter(account=self.account).update(mode="off")
        self.request("Off preference")
        self.assertEqual(DeliveryReceipt.objects.filter(source="plots").count(), 2)
        self.assertEqual(PlotNoticeReceipt.objects.latest("pk").state, State.SUPPRESSED)

    def test_real_compactor_rolls_up_independent_requests_and_safe_survivors(self):
        with override_settings(NOTICES_ROUTINE_LIMIT=1):
            first = self.request("Compacted Secret A")
            second = self.request("Compacted Secret B")
            [item] = self.project()
            self.assertEqual(len(item.events), 2)
            self.assertEqual(item.text, "There is new plot activity.")
            threads.withdraw(first, self.requester)
            [item] = self.project()
            self.assertEqual(len(item.events), 1)
            self.assertIn(second.ref, item.text)

    def test_failed_fanout_route_keeps_other_owner_and_recovers_quietly(self):
        with self.captureOnCommitCallbacks(execute=True):
            threads.add_owner(self.plot, self.char1, self.char2)
        notify = notices.notify

        def fail_one(character, **kwargs):
            if character == self.char1:
                raise RuntimeError("One recipient deferred")
            return notify(character, **kwargs)

        with patch.object(notices, "notify", side_effect=fail_one):
            self.request()
        self.assertEqual(
            PlotNoticeReceipt.objects.get(kind=Kind.REQUEST, character=self.char1).state,
            State.PENDING,
        )
        self.assertEqual(
            PlotNoticeReceipt.objects.get(kind=Kind.REQUEST, character=self.char2).state,
            State.INBOX,
        )
        with self.captureOnCommitCallbacks(execute=True):
            notices.prepare(NoticeContext(self.account, self.char1))
        self.assertEqual(len(self.project()), 1)

    @skipUnless(HAS_SOCIAL, "Social physically absent")
    def test_ignore_snapshots_before_unignore_preserve_other_roster_viewer(self):
        from evennia_social import ignore

        shared = create_account(
            "Other plot viewer", "plot-viewer@fixture.test", "twenty-giant-falcons-83"
        )
        shared.characters.add(self.char1)
        self.account.permissions.clear()
        self.account2.permissions.clear()
        self.account.is_superuser = False
        self.account.save(update_fields=["is_superuser"])
        ignore.set_entry(self.account, self.requester)
        first = self.request("Ignored while emitted")
        ignore.remove_entry(self.account, self.requester)
        with patch.object(notices, "notify", return_value=RouteResult("retry")):
            pending = self.request("Ignored during pending")
        ignore.set_entry(self.account, self.requester)
        ignore.remove_entry(self.account, self.requester)
        with self.captureOnCommitCallbacks(execute=True):
            notices.prepare(NoticeContext(shared, self.char1))
        self.assertFalse(self.project())
        self.assertEqual(len(self.project(shared, self.char1)), 2)
        for request in (first, pending):
            self.assertEqual(
                PlotNoticeReceipt.objects.get(thread=request).suppressed_accounts, [self.account.pk]
            )

    def test_nonroster_with_inbox_uses_only_exact_transient_connection(self):
        from evennia_notices.models import DeliveryReceipt

        target = create_object("evennia.DefaultCharacter", key="Unrostered owner", nohome=True)
        puppet = connected(self.account, target)
        wrong_puppet = connected(self.account, self.char1)
        with (
            patch(SESSION_LIST, return_value=[puppet, wrong_puppet]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            threads.add_owner(self.plot, self.char1, target)
        puppet.msg.assert_called_once()
        wrong_puppet.msg.assert_not_called()
        self.assertFalse(PlotNoticeReceipt.objects.exists())
        self.assertFalse(DeliveryReceipt.objects.filter(source="plots").exists())

        threads.remove_owner(self.plot, self.char1, target)
        self.account2.characters.add(target)
        puppet.msg.reset_mock()
        with (
            patch(SESSION_LIST, return_value=[puppet]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            threads.add_owner(self.plot, self.char1, target)
        puppet.msg.assert_not_called()
        self.assertEqual(len(self.project(self.account2, target)), 1)
        self.assertFalse(self.project(self.account2, self.char2))

    def test_policy_failure_defers_only_the_affected_actor_dispatch(self):
        failing_actor = self.requester

        def broken_actor(sender, viewer, sender_object, kind, **kwargs):
            if sender_object == failing_actor:
                return object()
            return None

        ignore_mode_requested.connect(broken_actor)
        self.addCleanup(ignore_mode_requested.disconnect, broken_actor)
        affected = self.request()
        with self.captureOnCommitCallbacks(execute=True):
            unaffected = threads.add_thread(self.plot, self.char2, "Other actor")
        self.assertEqual(PlotNoticeReceipt.objects.get(thread=affected).state, State.PENDING)
        self.assertEqual(PlotNoticeReceipt.objects.get(thread=unaffected).state, State.INBOX)
        [item] = self.project()
        self.assertIn(unaffected.ref, item.text)
        ignore_mode_requested.disconnect(broken_actor)
        with self.captureOnCommitCallbacks(execute=True):
            notices.prepare(NoticeContext(self.account, self.char1))
        self.assertEqual(len(self.project()), 2)

    def test_system_checks_missing_witness_individually(self):
        first = self.request()
        second = self.request()
        rows = list(PlotNoticeReceipt.objects.all())
        first.created_by = None
        first.save(update_fields=["created_by"])
        outcomes = evaluate(
            PlotNoticeSource(), [stored_event(row) for row in rows], NoticeContext(None)
        )
        self.assertEqual(outcomes[rows[0].event_key].status, "invalid")
        self.assertEqual(outcomes[rows[1].event_key].reason, "context")
        self.assertEqual(second.status, StoryThread.Status.REQUESTED)
