# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Historical outcomes, ownership, policy and one durable delivery path."""

import io
from dataclasses import replace
from datetime import timedelta
from importlib.util import find_spec
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from evennia.utils.test_resources import EvenniaTest

from evennia_jobs.models import RequestDecision
from evennia_jobs.review import review_request
from evennia_links.notices import NoticeContext, StoredEvent, evaluate
from evennia_moderation import admissions, notices
from evennia_moderation.integrations.notices import ModerationNoticeSource, event_for
from evennia_moderation.models import Application, Notice, NoticeCursor, Referral
from evennia_moderation.tests import FORMS, AdmissionFixture

REGISTRY = {"moderation": "evennia_moderation.integrations.notices.ModerationNoticeSource"}
HAS_INBOX = find_spec("evennia_notices") is not None
LONG_SHARED_REASON = "📝" * 1500


class OutcomeFixture(AdmissionFixture):
    def outcome(self, kind="approved", *, shared=False, name="OutcomeApplicant"):
        code = admissions.issue_code(self.account2)
        app = self.apply(name, code=code.code)
        if kind == "lapsed":
            Application.objects.filter(pk=app.pk).update(
                expires_at=timezone.now() - timedelta(seconds=1)
            )
            admissions.expire_applications()
        else:
            if shared:
                Application.objects.filter(pk=app.pk).update(share_decline_reason=True)
            self.review(app, kind)
        return Notice.objects.latest("pk")

    def stored(self, row):
        return StoredEvent(
            **event_for(row).__dict__, recipient_kind="account", recipient_id=row.account_id
        )

    def make_session(self, account=None, character=None):
        session = Mock()
        session.get_account.return_value = account or self.account2
        session.get_puppet.return_value = character
        return session

    def long_shared_decline(self):
        code = admissions.issue_code(self.account2)
        application = self.apply(code=code.code)
        review_request(
            job=application.job,
            reviewer=self.char1,
            outcome="declined",
            reason=LONG_SHARED_REASON,
            expected_revision=1,
            review_options={"share_decline_reason": True},
        )
        return Notice.objects.get(account=self.account2)


@override_settings(
    JOBS_REQUEST_FORMS=FORMS, MODERATION_REFERRAL_ALLOWANCE=10, LINKS_NOTICE_SOURCES=REGISTRY
)
class OutcomeIdentityTests(OutcomeFixture, EvenniaTest):
    def test_three_outcomes_have_durable_submission_and_real_or_system_actors(self):
        for kind in ("approved", "declined", "lapsed"):
            row = self.outcome(kind, name=kind + "Applicant")
            self.assertTrue(row.provenance_known)
            self.assertIn(str(row.envelope["payload"]["submission"]), row.event_key)
            self.assertEqual(
                row.envelope["actors"],
                [] if kind == "lapsed" else [{"kind": "character", "id": self.char1.pk}],
            )
            self.assertEqual(
                ModerationNoticeSource()
                .evaluate([self.stored(row)], NoticeContext(self.account2))[row.event_key]
                .status,
                "visible",
            )
        self.assertEqual(Notice.objects.count(), 3)
        self.assertFalse(Application.objects.filter(status="pending").exists())

    def test_repeat_review_and_expiry_do_not_recreate_outcome(self):
        code = admissions.issue_code(self.account2)
        app = self.apply(code=code.code)
        self.review(app)
        self.review(app)
        admissions.expire_applications()
        self.assertEqual(Notice.objects.count(), 1)
        self.assertEqual(Referral.objects.count(), 1)
        self.assertEqual(RequestDecision.objects.count(), 1)
        self.outcome(name="SecondApplicant")
        self.assertEqual(len(set(Notice.objects.values_list("event_key", flat=True))), 2)

    def test_private_reason_never_enters_envelope_and_shared_snapshot_stays_historical(self):
        private = self.outcome("declined")
        shared = self.outcome("declined", shared=True, name="SharedApplicant")
        self.assertNotIn("Staff decision", str(private.envelope))
        self.assertEqual(shared.envelope["payload"]["reason"], "Staff decision")
        RequestDecision.objects.all().update(reason="Later secret")
        self.assertIn(
            "Staff decision",
            ModerationNoticeSource()
            .render([self.stored(shared)], NoticeContext(self.account2))
            .text,
        )
        self.assertNotIn("Later secret", str(shared.envelope))
        for row in (private, shared):
            self.assertFalse(
                {"password", "password_hash", "address", "answers", "code"}
                & row.envelope["payload"].keys()
            )

    def test_dynamic_identity_modes_do_not_guess_an_alt(self):
        row = self.outcome()
        source = ModerationNoticeSource()
        for character in (None, self.char2):
            context = NoticeContext(self.account2, character)
            with self.settings(EVENNIA_COMMS_IDENTITY="character"):
                text = source.render([self.stored(row)], context).text
                self.assertIn("using your referral", text)
                for forbidden in ("OutcomeApplicant", self.account.key, self.char1.key):
                    self.assertNotIn(forbidden, text)
            with self.settings(EVENNIA_COMMS_IDENTITY="account"):
                self.assertIn("OutcomeApplicant", source.render([self.stored(row)], context).text)

    def test_unknown_custom_and_delivered_legacy_preserved(self):
        pending = admissions.notice(self.account2, "Unknown private applicant")
        delivered = Notice.objects.create(
            account=self.account2, text="Old delivered", delivered_at=timezone.now()
        )
        stamp = delivered.delivered_at
        self.assertEqual(notices.route_notice(pending.pk), "held")
        self.assertEqual(notices.route_notice(delivered.pk), "fallback")
        pending.refresh_from_db()
        delivered.refresh_from_db()
        self.assertIsNone(pending.acknowledged_at)
        self.assertEqual(pending.text, "Unknown private applicant")
        self.assertEqual(delivered.delivered_at, stamp)

    def test_forged_or_reassigned_source_never_authorizes_other_account(self):
        row = self.outcome()
        source, event = ModerationNoticeSource(), self.stored(row)
        context = NoticeContext(self.account2)
        forged = replace(event, payload={**event.payload, "reason": "forged"})
        self.assertEqual(source.evaluate([forged], context)[event.event_id].status, "invalid")
        self.assertEqual(
            source.evaluate([event], NoticeContext(self.account))[event.event_id].status, "invalid"
        )
        Notice.objects.filter(pk=row.pk).update(account=self.account)
        self.assertEqual(source.evaluate([event], context)[event.event_id].status, "invalid")
        self.assertEqual(
            source.evaluate([event], NoticeContext(self.account))[event.event_id].status, "invalid"
        )
        row.delete()
        self.assertEqual(source.evaluate([event], context)[event.event_id].status, "invalid")

    def test_missing_actor_and_malformed_constituents_do_not_hide_valid_peer(self):
        bad = self.outcome()
        good = self.outcome("lapsed", name="ValidPeer")
        event = self.stored(bad)
        malformed = replace(event, event_id="malformed", payload={"notice": []})
        self.char1.delete()
        statuses = evaluate(
            ModerationNoticeSource(),
            [event, malformed, self.stored(good)],
            NoticeContext(self.account2),
        )
        self.assertEqual(statuses[event.event_id].status, "defer")
        self.assertEqual(statuses["malformed"].status, "invalid")
        self.assertEqual(statuses[good.event_key].status, "visible")

    def test_source_record_collision_cannot_change_original_snapshot(self):
        row = self.outcome()
        with self.assertRaises(ValueError):
            notices.record_outcome(
                self.account2,
                kind="approved",
                submission_id=row.envelope["payload"]["submission"],
                applicant_name="Changed",
                actor=self.char1,
            )
        row.refresh_from_db()
        self.assertEqual(row.envelope["payload"]["applicant_name"], "OutcomeApplicant")

    def test_bounded_cursor_advances_past_held_and_exception_then_wraps(self):
        unknown = admissions.notice(self.account2, "Held")
        good = self.outcome("lapsed")
        with patch.object(notices, "route_notice", side_effect=RuntimeError("isolated")):
            self.assertEqual(notices.transfer_pending(self.account2, limit=1)["retry"], 1)
        self.assertEqual(
            NoticeCursor.objects.get(scope=f"account-{self.account2.pk}").last_pk, unknown.pk
        )
        with patch.object(notices, "_safe_route", return_value="pending") as route:
            notices.transfer_pending(self.account2, limit=1)
            route.assert_called_once_with(good.pk, context=None)
            route.reset_mock()
            notices.transfer_pending(self.account2, limit=1)
            route.assert_called_once_with(unknown.pk, context=None)
        for limit in (0, 1001, True):
            with self.assertRaises(ValueError):
                notices.transfer_pending(self.account2, limit=limit)

    def test_management_output_is_counts_only(self):
        admissions.notice(self.account2, "Private never output")
        output = io.StringIO()
        call_command(
            "transfer_moderation_notices", account=self.account2.pk, limit=1, stdout=output
        )
        self.assertIn("held: 1", output.getvalue())
        self.assertNotIn("Private", output.getvalue())

    def test_guest_outcomes_never_persist_and_connected_claim_is_transient(self):
        before_cursors = set(NoticeCursor.objects.values_list("pk", flat=True))
        inbox_counts = None
        if HAS_INBOX:
            from evennia_notices.models import DeliveryReceipt, NoticeEvent, Recipient

            inbox_counts = (
                DeliveryReceipt.objects.count(),
                NoticeEvent.objects.count(),
                Recipient.objects.count(),
            )
        session = self.make_session(self.visitor)
        context = NoticeContext(self.visitor, None, session)
        session._moderation_notice_attempts = set()
        with (
            patch.object(notices, "connected_contexts", return_value=[context]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            for _ in range(2):
                notices.record_outcome(
                    self.visitor, kind="lapsed", submission_id=9, applicant_name="Guest example"
                )
            admissions.notice(self.visitor, "Unknown")
            notices.transfer_pending(self.visitor)
        self.assertEqual(session.msg.call_count, 1)
        self.assertFalse(Notice.objects.exists())
        self.assertEqual(set(NoticeCursor.objects.values_list("pk", flat=True)), before_cursors)
        self.assertFalse(NoticeCursor.objects.filter(scope=f"account-{self.visitor.pk}").exists())
        if inbox_counts is not None:
            self.assertEqual(
                inbox_counts,
                (
                    DeliveryReceipt.objects.count(),
                    NoticeEvent.objects.count(),
                    Recipient.objects.count(),
                ),
            )

    def test_offline_guest_retains_nothing(self):
        with (
            patch.object(notices, "connected_contexts", return_value=[]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            notices.record_outcome(
                self.visitor, kind="lapsed", submission_id=9, applicant_name="Guest example"
            )
        self.assertFalse(Notice.objects.exists())


@skipUnless(HAS_INBOX, "Optional Inbox physically absent")
@override_settings(
    JOBS_REQUEST_FORMS=FORMS, MODERATION_REFERRAL_ALLOWANCE=10, LINKS_NOTICE_SOURCES=REGISTRY
)
class InboxOutcomeTests(OutcomeFixture, EvenniaTest):
    def test_long_shared_decline_reason_is_readable_in_inbox(self):
        from evennia_notices.services import project

        row = self.long_shared_decline()
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        [item] = project(NoticeContext(self.account2))
        self.assertTrue(item.text.endswith(LONG_SHARED_REASON))

    def test_account_select_and_two_characters_share_one_read_clear_state(self):
        from evennia_notices.models import NoticeEvent, Recipient
        from evennia_notices.services import mutate, project

        self.account2.characters.add(self.char1)
        row = self.outcome()
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        contexts = [
            NoticeContext(self.account2),
            NoticeContext(self.account2, self.char1),
            NoticeContext(self.account2, self.char2),
        ]
        item = project(contexts[0])[0]
        self.assertEqual(Recipient.objects.get().identity, ("account", self.account2.pk))
        self.assertEqual(NoticeEvent.objects.count(), 1)
        before = (
            Application.objects.count(),
            Referral.objects.count(),
            RequestDecision.objects.count(),
        )
        mutate(contexts[1], item.notice.public_ref, "read")
        for context in contexts:
            self.assertFalse(project(context)[0].unread)
        self.assertEqual(project(NoticeContext(self.account)), [])
        mutate(contexts[2], item.notice.public_ref, "clear")
        for context in contexts:
            self.assertEqual(project(context), [])
        self.assertEqual(
            before,
            (
                Application.objects.count(),
                Referral.objects.count(),
                RequestDecision.objects.count(),
            ),
        )
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        from evennia_notices.services import maintain

        old = timezone.now() - timedelta(days=31)
        NoticeEvent.objects.update(read_at=old, cleared_at=old)
        maintain()
        self.assertFalse(NoticeEvent.objects.exists())
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        self.assertFalse(NoticeEvent.objects.exists())

    def test_preferences_and_imported_pending_are_quiet(self):
        from evennia_notices.models import DeliveryReceipt, SourcePreference

        session = self.make_session()
        context = NoticeContext(self.account2, None, session)
        with patch("evennia.server.sessionhandler.SESSIONS.get_sessions", return_value=[session]):
            with self.captureOnCommitCallbacks(execute=True):
                self.outcome()
            session.msg.assert_not_called()
            SourcePreference.objects.create(
                account=self.account2, source="moderation", mode="immediate"
            )
            with self.captureOnCommitCallbacks(execute=True):
                self.outcome(name="ImmediateApplicant")
            self.assertEqual(session.msg.call_count, 1)
            session.msg.reset_mock()
            row = self.outcome(name="ImportedApplicant")
            with self.captureOnCommitCallbacks(execute=True):
                notices.route_notice(row.pk, context=context)
            session.msg.assert_not_called()
            SourcePreference.objects.filter(account=self.account2).update(mode="off")
            row = self.outcome(name="OffApplicant")
            self.assertEqual(notices.route_notice(row.pk), "suppressed")
            self.assertEqual(DeliveryReceipt.objects.count(), 4)

    def test_source_ack_failure_rolls_back_receipt_and_hint_but_not_outcome(self):
        from evennia_notices.models import DeliveryReceipt

        row = self.outcome()
        with patch.object(notices, "_ack", side_effect=RuntimeError("source ack")):
            self.assertEqual(notices.route_notice(row.pk, fresh=True), "retry")
        row.refresh_from_db()
        self.assertEqual(row.route_state, "pending")
        self.assertTrue(Referral.objects.exists())
        self.assertFalse(DeliveryReceipt.objects.exists())
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        self.assertEqual(DeliveryReceipt.objects.count(), 1)

    def test_missing_actor_is_excluded_from_counts_and_compaction(self):
        from evennia_notices.services import maintain, project, summarize

        bad = self.outcome()
        good = self.outcome("lapsed", name="GoodApplicant")
        for row in (bad, good):
            self.assertEqual(notices.route_notice(row.pk), "inbox")
        self.char1.delete()
        context = NoticeContext(self.account2)
        maintain()
        self.assertEqual(len(project(context)), 1)
        self.assertIn("GoodApplicant", project(context)[0].text)
        self.assertNotIn("OutcomeApplicant", str(summarize(context)))

    def test_deleted_source_and_forged_envelope_are_not_counted(self):
        from evennia_notices.services import project, summarize

        row = self.outcome()
        context = NoticeContext(self.account2)
        notices.route_notice(row.pk)
        row.envelope["payload"]["applicant_name"] = "ForgedApplicant"
        row.save(update_fields=["envelope"])
        self.assertEqual(project(context), [])
        self.assertEqual(summarize(context), (0, 0))
        Notice.objects.filter(pk=row.pk).update(envelope={})
        self.assertEqual(project(context), [])
        row.delete()
        self.assertEqual(project(context), [])

    @skipUnless(find_spec("evennia_social") is not None, "Optional Social physically absent")
    def test_real_ignore_and_compaction_never_restore_hidden_actor_activity(self):
        from evennia_notices.services import maintain, project
        from evennia_social import ignore

        bad = self.outcome()
        good = self.outcome("lapsed", name="SafeSystemApplicant")
        with self.settings(NOTICES_ROUTINE_LIMIT=1):
            for row in (bad, good):
                notices.route_notice(row.pk)
            self.account.is_superuser = False
            self.account.permissions.clear()
            self.account.save(update_fields=["is_superuser"])
            self.char1.permissions.clear()
            ignore.set_entry(self.char2, self.char1, ignore.HIDDEN)
            maintain()
            page = project(NoticeContext(self.account2))
            self.assertEqual(sum(len(item.events) for item in page), 1)
            self.assertNotIn("OutcomeApplicant", str([item.text for item in page]))
            ignore.clear(self.account2)
            page = project(NoticeContext(self.account2))
            self.assertEqual(sum(len(item.events) for item in page), 1)
            self.assertNotIn("OutcomeApplicant", str([item.text for item in page]))

    def test_policy_error_defers_without_fallback_or_count(self):
        from evennia_notices.services import project

        row = self.outcome()
        with patch(
            "evennia_links.ignoring.notice_ignore_status", side_effect=RuntimeError("policy")
        ):
            self.assertEqual(notices.route_notice(row.pk), "retry")
        self.assertEqual(notices.route_notice(row.pk), "inbox")
        with patch("evennia_links.ignoring.notice_ignore_status", return_value="defer"):
            self.assertEqual(project(NoticeContext(self.account2)), [])


@override_settings(
    JOBS_REQUEST_FORMS=FORMS,
    MODERATION_REFERRAL_ALLOWANCE=10,
    LINKS_NOTICE_SOURCES=REGISTRY,
    NOTICES_ENABLED=False,
)
class StandaloneOutcomeTests(OutcomeFixture, EvenniaTest):
    def test_long_shared_decline_reason_is_delivered_without_inbox(self):
        row = self.long_shared_decline()
        session = self.make_session()
        with (
            patch("evennia.server.sessionhandler.SESSIONS.get_sessions", return_value=[session]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.assertEqual(notices.route_notice(row.pk), "attempting")
        session.msg.assert_called_once()
        self.assertTrue(session.msg.call_args.args[0].endswith(LONG_SHARED_REASON))

    def test_fallback_all_account_sessions_once_and_no_other_account(self):
        row = self.outcome()
        first, second, other = (
            self.make_session(),
            self.make_session(character=self.char2),
            self.make_session(self.account),
        )
        with (
            patch(
                "evennia.server.sessionhandler.SESSIONS.get_sessions",
                return_value=[first, second, other],
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            notices.route_notice(row.pk)
        self.assertEqual(first.msg.call_count, 1)
        self.assertEqual(second.msg.call_count, 1)
        other.msg.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.route_state, "fallback")
        self.assertIsNotNone(row.delivered_at)
        with self.settings(NOTICES_ENABLED=True):
            self.assertEqual(notices.route_notice(row.pk), "fallback")

    def test_transport_failure_is_uncertain_and_never_replayed(self):
        row = self.outcome()
        session = self.make_session()
        session.msg.side_effect = RuntimeError("socket uncertain")
        with (
            patch("evennia.server.sessionhandler.SESSIONS.get_sessions", return_value=[session]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            notices.route_notice(row.pk)
        row.refresh_from_db()
        self.assertEqual(row.route_state, "uncertain")
        self.assertIsNone(row.acknowledged_at)
        self.assertIsNone(row.delivered_at)
        self.assertEqual(notices.route_notice(row.pk), "uncertain")
        self.assertEqual(session.msg.call_count, 1)

    def test_session_loses_account_before_send_so_no_output_and_later_retry(self):
        row = self.outcome()
        session = self.make_session()
        with (
            patch("evennia.server.sessionhandler.SESSIONS.get_sessions", return_value=[session]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.assertEqual(notices.route_notice(row.pk), "attempting")
            session.get_account.return_value = self.account
        session.msg.assert_not_called()
        row.refresh_from_db()
        # Nothing reached a socket, so the outcome is not uncertain or consumed.
        self.assertEqual(row.route_state, "pending")
        self.assertIsNone(row.acknowledged_at)
        later = self.make_session()
        with (
            patch("evennia.server.sessionhandler.SESSIONS.get_sessions", return_value=[later]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            notices.route_notice(row.pk)
        later.msg.assert_called_once()
        row.refresh_from_db()
        self.assertEqual(row.route_state, "fallback")

    def test_malformed_registry_or_backend_error_never_falls_back(self):
        row = self.outcome()
        session = self.make_session()
        with patch("evennia.server.sessionhandler.SESSIONS.get_sessions", return_value=[session]):
            for registry in ([], {"moderation": "missing.module.Source"}):
                with self.settings(LINKS_NOTICE_SOURCES=registry):
                    self.assertEqual(notices.route_notice(row.pk), "retry")
            with patch.object(notices, "transfer", side_effect=RuntimeError("backend")):
                self.assertEqual(notices.route_notice(row.pk), "retry")
        session.msg.assert_not_called()
        row.refresh_from_db()
        self.assertIsNone(row.acknowledged_at)

    def test_missing_valid_registry_key_uses_validated_local_fallback(self):
        row = self.outcome()
        session = self.make_session()
        with (
            self.settings(LINKS_NOTICE_SOURCES={}),
            patch("evennia.server.sessionhandler.SESSIONS.get_sessions", return_value=[session]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            notices.route_notice(row.pk)
        self.assertEqual(session.msg.call_count, 1)

    def test_invalid_identity_config_is_retryable_before_any_socket_claim(self):
        session = self.make_session()
        with (
            self.settings(EVENNIA_COMMS_IDENTITY="invalid"),
            patch("evennia.server.sessionhandler.SESSIONS.get_sessions", return_value=[session]),
        ):
            row = self.outcome()
            self.assertTrue(Referral.objects.exists())
            self.assertEqual(notices.route_notice(row.pk), "retry")
            row.refresh_from_db()
            self.assertEqual(row.route_state, "pending")
            self.assertIsNone(row.delivered_at)
            self.assertIsNone(row.acknowledged_at)
            session.msg.assert_not_called()
        with (
            self.settings(EVENNIA_COMMS_IDENTITY="character"),
            patch("evennia.server.sessionhandler.SESSIONS.get_sessions", return_value=[session]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            notices.route_notice(row.pk)
        self.assertEqual(session.msg.call_count, 1)
        self.assertNotIn("OutcomeApplicant", session.msg.call_args.args[0])
        row.refresh_from_db()
        self.assertEqual(row.route_state, "fallback")
