# SPDX-License-Identifier: BSD-3-Clause
"""Admissions lifecycle and account-wide enforcement under real Jobs services."""

from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth.hashers import check_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, override_settings
from django.utils import timezone
from evennia.accounts.accounts import DefaultGuest
from evennia.accounts.models import AccountDB
from evennia.utils.create import create_account, create_object
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from evennia_jobs.models import Job, RequestDecision, RequestSubmission
from evennia_jobs.review import review_request

from evennia_links.communication import denial
from evennia_moderation import admissions, services
from evennia_moderation.auth import ModerationBackend, ModerationMiddleware
from evennia_moderation.commands import CmdAdmissions, CmdMute, CmdNotes, CmdReferral, CmdSoftban
from evennia_moderation.models import Application, ModerationAction, Notice, Referral, StaffNote
from evennia_moderation.policy import connection_restriction
from evennia_moderation.signals import account_admitted

FORMS = {
    "admission": {
        "owner": "moderation",
        "outcomes": ["approved", "declined"],
        "questions": [{"key": "reason", "label": "Why join?"}],
    }
}
PASSWORD = "long-test-passphrase-379"


class AdmissionFixture:
    def setUp(self):
        super().setUp()
        self.account.is_superuser = True
        self.account.save()
        self.account2.is_superuser = False
        self.account2.permissions.clear()
        self.account2.permissions.add("Player")
        self.account2.save()
        self.char1.account = self.account
        self.char2.account = self.account2
        self.account.characters.add(self.char1)
        self.account2.characters.add(self.char2)
        self.visitor = create_account(
            "GuestTrial", "", PASSWORD, typeclass=DefaultGuest, permissions=["Guests"]
        )
        self.guest = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Applicant", location=self.room1
        )
        self.guest.account = self.visitor
        self.visitor.characters.add(self.guest)
        self.guest.tags.add("character", category="guest")

    def apply(self, username="NewPlayer", **kwargs):
        return admissions.submit_application(
            guest=self.guest,
            username=username,
            password=PASSWORD,
            answers={"reason": "I would like to play."},
            address="192.0.2.44",
            **kwargs,
        )

    def review(self, application, outcome="approved"):
        return review_request(
            job=application.job,
            reviewer=self.char1,
            outcome=outcome,
            reason="Staff decision",
            expected_revision=1,
        )


@override_settings(JOBS_REQUEST_FORMS=FORMS, MODERATION_REFERRAL_ALLOWANCE=3)
class TestAdmissions(AdmissionFixture, EvenniaTest):
    def test_credentials_are_separate_from_immutable_questionnaire(self):
        application = self.apply()
        self.assertTrue(check_password(PASSWORD, application.password_hash))
        submission = application.job.submissions.get()
        self.assertEqual(submission.answers, {"reason": "I would like to play."})
        self.assertNotIn(PASSWORD, application.job.description)
        self.assertNotIn(application.password_hash, str(submission.answers))

    def test_approval_uses_hash_and_deletes_address_and_pending_credentials(self):
        application = self.apply()
        encoded = application.password_hash
        self.review(application)
        account = AccountDB.objects.get(username="NewPlayer")
        self.assertEqual(account.password, encoded)
        self.assertTrue(account.check_password(PASSWORD))
        self.assertFalse(account.attributes.has("creator_ip"))
        self.assertFalse(Application.objects.exists())
        self.assertTrue(Job.objects.filter(pk=application.job_id).exists())
        self.assertEqual(
            Referral.objects.get(account=account).submission_id,
            application.job.submissions.get().pk,
        )

    def test_pending_status_requires_password(self):
        self.apply()
        self.assertIn("pending", admissions.application_status("newplayer", PASSWORD))
        self.assertIsNone(admissions.application_status("NewPlayer", "wrong"))

    def test_decline_releases_name_and_password_but_retains_address_temporarily(self):
        application = self.apply()
        self.review(application, "declined")
        application.refresh_from_db()
        self.assertIsNone(application.reserved_name)
        self.assertEqual(application.password_hash, "")
        self.assertEqual(application.address, "192.0.2.44")
        self.assertIsNone(admissions.application_status("NewPlayer", PASSWORD))
        self.apply()

    def test_case_insensitive_name_reservation_and_existing_account(self):
        self.apply()
        with self.assertRaisesMessage(ValidationError, "unavailable"):
            self.apply("newplayer")
        with self.assertRaises(ValidationError):
            self.apply(self.account2.key)

    @override_settings(MODERATION_PLAYER_CAP=2)
    def test_pending_applications_reserve_seats(self):
        self.assertEqual(admissions.seat_count(), 1)
        self.apply()
        self.assertEqual(admissions.seat_count(), 2)
        with self.assertRaisesMessage(ValidationError, "capacity"):
            self.apply("OtherPlayer")
        self.assertEqual(Application.objects.count(), 1)

    def test_staff_and_guests_are_excluded_from_cap(self):
        self.assertEqual(admissions.seat_count(), 1)

    @override_settings(
        MODERATION_INTAKE_CLOSED=True, MODERATION_CLOSED_MESSAGE="Closed for the next chapter."
    )
    def test_closed_intake_has_own_message(self):
        with self.assertRaisesMessage(ValidationError, "next chapter"):
            self.apply()

    def test_lower_cap_and_closed_intake_honor_existing_reservation(self):
        application = self.apply()
        with override_settings(MODERATION_PLAYER_CAP=0, MODERATION_INTAKE_CLOSED=True):
            self.review(application)
        self.assertTrue(AccountDB.objects.filter(username="NewPlayer").exists())

    def test_expiry_is_immediate_for_status_and_review_without_waiting_for_sweep(self):
        application = self.apply()
        Application.objects.filter(pk=application.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertIsNone(admissions.application_status("NewPlayer", PASSWORD))
        with self.assertRaisesMessage(ValidationError, "no longer pending"):
            self.review(application)
        self.assertFalse(RequestDecision.objects.exists())
        admissions.expire_applications()
        application.refresh_from_db()
        self.assertEqual(application.status, "lapsed")
        self.assertEqual(application.password_hash, "")

    def test_guest_logout_keeps_job_and_application(self):
        application = self.apply()
        self.guest.delete()
        application.job.refresh_from_db()
        self.assertIsNone(application.job.author_id)
        self.assertEqual(application.job.author_name, "Applicant")
        self.review(application)

    def test_approval_receiver_failure_rolls_back_account_referral_and_decision(self):
        application = self.apply()

        def fail(**kwargs):
            raise ValueError("Receiver failed")

        account_admitted.connect(fail, weak=False)
        try:
            with self.assertRaisesMessage(ValueError, "Receiver failed"):
                self.review(application)
        finally:
            account_admitted.disconnect(fail)
        self.assertFalse(AccountDB.objects.filter(username="NewPlayer").exists())
        self.assertFalse(Referral.objects.exists())
        self.assertFalse(RequestDecision.objects.exists())
        self.assertTrue(Application.objects.filter(pk=application.pk, status="pending").exists())
        self.review(application)

    def test_repeated_approval_creates_only_one_account_and_referral(self):
        application = self.apply()
        first = self.review(application)
        second = self.review(application)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Referral.objects.count(), 1)

    def test_no_changes_requested_for_admissions(self):
        with self.assertRaisesMessage(ValidationError, "unavailable for this form"):
            self.review(self.apply(), "changes_requested")

    def test_only_guests_can_apply(self):
        with self.assertRaises(PermissionDenied):
            admissions.submit_application(
                guest=self.char2,
                username="NewPlayer",
                password=PASSWORD,
                answers={"reason": "Hi"},
                address="192.0.2.5",
            )

    @override_settings(MODERATION_APPLICATION_ATTEMPTS=1)
    def test_application_throttle_commits_even_when_name_is_unavailable(self):
        with self.assertRaises(ValidationError):
            self.apply(self.account2.key)
        with self.assertRaisesMessage(ValidationError, "Too many"):
            self.apply("OtherPlayer")

    def test_retirement_is_reversible_and_does_not_delete_account(self):
        admissions.retire_seat(self.char1, self.account2)
        self.assertEqual(admissions.seat_count(), 0)
        self.assertTrue(AccountDB.objects.filter(pk=self.account2.pk).exists())
        admissions.retire_seat(self.char1, self.account2, retire=False)
        self.assertEqual(admissions.seat_count(), 1)

    def test_nonstaff_cannot_retire_or_reset_or_backfill(self):
        for fn in (
            lambda: admissions.retire_seat(self.char2, self.account2),
            lambda: admissions.reset_allowances(self.char2),
            lambda: admissions.backfill_referral(self.char2, self.account2),
        ):
            with self.assertRaises(PermissionDenied):
                fn()

    def test_reapplication_checks_do_not_automatically_decline(self):
        services.restrict(self.char1, kind="softban", address="192.0.2.0/24", reason="Incident")
        application = self.apply()
        self.assertTrue(admissions.reapplication_flags(application))
        self.assertEqual(application.status, "pending")


@override_settings(
    JOBS_REQUEST_FORMS=FORMS, MODERATION_REFERRAL_ALLOWANCE=1, MODERATION_REFERRAL_MODE="required"
)
class TestReferrals(AdmissionFixture, EvenniaTest):
    def test_referrer_deletion_keeps_pending_application_and_name_snapshot(self):
        code = admissions.issue_code(self.account2)
        application = self.apply(code=code.code)
        name = self.account2.key
        self.account2.delete()
        application.refresh_from_db()
        self.assertIsNone(application.code.owner_id)
        self.assertEqual(application.code.owner_name, name)
        self.review(application)
        self.assertEqual(Referral.objects.get().referrer_name, name)
        # Evennia's fixture teardown expects its second account to exist.
        self.account2 = create_account("ReplacementFixture", "", PASSWORD)

    def test_one_code_uses_allowance_across_alts(self):
        admissions.issue_code(self.account2)
        with self.assertRaisesMessage(ValidationError, "no referral allowance"):
            admissions.issue_code(self.char2)

    def test_decline_returns_allowance_but_does_not_reactivate_code(self):
        code = admissions.issue_code(self.account2)
        application = self.apply(code=code.code)
        self.review(application, "declined")
        self.assertEqual(admissions.remaining_allowance(self.account2, 1), 1)
        with self.assertRaisesMessage(ValidationError, "code is unavailable"):
            self.apply("Again", code=code.code)
        admissions.issue_code(self.account2)

    def test_reserved_code_survives_its_original_unused_expiry(self):
        code = admissions.issue_code(self.account2)
        application = self.apply(code=code.code)
        type(code).objects.filter(pk=code.pk).update(expires_at=timezone.now() - timedelta(days=1))
        services.purge()
        self.assertEqual(admissions.remaining_allowance(self.account2, 1), 0)
        self.review(application)
        self.assertEqual(Referral.objects.get().referrer_id, self.account2.pk)

    def test_code_is_single_use_and_expired_unused_codes_free_allowance(self):
        code = admissions.issue_code(self.account2)
        self.apply(code=code.code)
        with self.assertRaisesMessage(ValidationError, "code is unavailable"):
            self.apply("SecondPlayer", code=code.code)

    def test_required_optional_and_off_modes(self):
        with self.assertRaisesMessage(ValidationError, "code is required"):
            self.apply()
        with override_settings(MODERATION_REFERRAL_MODE="optional"):
            self.apply()
        with override_settings(MODERATION_REFERRAL_MODE="off"):
            self.apply("AnotherPlayer", code="ignored")

    def test_approval_notice_and_referral_history_survive_allowance_reset(self):
        code = admissions.issue_code(self.account2)
        self.review(self.apply(code=code.code))
        self.assertIn("approved", Notice.objects.get(account=self.account2).text)
        self.assertEqual(admissions.remaining_allowance(self.account2, 1), 0)
        self.assertEqual(admissions.reset_allowances(self.char1), 2)
        self.assertEqual(admissions.remaining_allowance(self.account2, 2), 1)
        self.assertEqual(Referral.objects.count(), 1)

    def test_decline_reason_is_staff_choice(self):
        code = admissions.issue_code(self.account2)
        application = self.apply(code=code.code)
        self.review(application, "declined")
        self.assertNotIn("Staff decision", Notice.objects.get().text)
        code = admissions.issue_code(self.account2)
        application = self.apply("OtherPlayer", code=code.code)
        application.share_decline_reason = True
        application.save()
        self.review(application, "declined")
        self.assertIn("Staff decision", Notice.objects.order_by("pk").last().text)

    def test_reset_refuses_pending_applications(self):
        self.apply(code=admissions.issue_code(self.account2).code)
        with self.assertRaisesMessage(ValidationError, "pending applications"):
            admissions.reset_allowances(self.char1)

    def test_backfill_is_idempotent_and_rejects_cycles(self):
        admissions.backfill_referral(self.char1, self.account2, self.account)
        admissions.backfill_referral(self.char1, self.account2, self.account)
        self.assertEqual(Referral.objects.count(), 1)
        with self.assertRaisesMessage(ValidationError, "cycle"):
            admissions.backfill_referral(self.char1, self.account, self.account2)


@override_settings(JOBS_REQUEST_FORMS=FORMS)
class TestModeration(AdmissionFixture, EvenniaTest):
    def test_softban_is_account_wide_and_expiry_does_not_need_sweep(self):
        action = services.restrict(
            self.char1, kind="softban", account=self.account2, reason="Cool down"
        )
        self.assertIn("banned until", connection_restriction(self.account2))
        ModerationAction.objects.filter(pk=action.pk).update(
            ends_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertIsNone(connection_restriction(self.account2))

    def test_lift_keeps_append_only_actor_history(self):
        action = services.restrict(
            self.char1, kind="softban", account=self.account2, reason="Cool down"
        )
        services.lift(self.char1, action)
        services.lift(self.char1, action)
        self.assertIsNone(connection_restriction(self.account2))
        self.assertEqual(ModerationAction.objects.filter(kind="lift", lifts=action).count(), 1)

    def test_ipv4_ipv6_and_cidr_are_supported(self):
        for network, inside, outside in [
            ("192.0.2.0/24", "192.0.2.99", "198.51.100.2"),
            ("2001:db8::/64", "2001:db8::12", "2001:db9::12"),
        ]:
            action = services.restrict(
                self.char1, kind="softban", address=network, reason="Network incident"
            )
            self.assertIsNotNone(connection_restriction(address=inside))
            self.assertIsNone(connection_restriction(address=outside))
            services.lift(self.char1, action)

    def test_mute_blocks_other_players_but_leaves_staff_and_ic_open(self):
        services.restrict(
            self.char1, kind="mute", account=self.account2, reason="Stop OOC disruption"
        )
        self.assertIsNotNone(denial(self.char2, "page", self.guest))
        self.assertIsNone(denial(self.char2, "page", self.char1))
        for kind in ("channel", "board"):
            self.assertIn("muted", denial(self.char2, kind))
        self.assertIsNone(denial(self.char2, "request"))
        self.char2.location = self.room1
        self.room1.room_type = "ic"
        self.assertIsNone(denial(self.char2, "room"))
        self.room1.room_type = "ooc"
        self.assertIn("muted", denial(self.char2, "room"))

    def test_offline_roster_and_all_alts_share_mute(self):
        services.restrict(self.char1, kind="mute", account=self.account2, reason="Stop")
        alt = create_object("evennia.objects.objects.DefaultCharacter", key="OtherAlt")
        self.account2.characters.add(alt)
        self.assertIn("muted", denial(alt, "board"))

    def test_staff_notes_are_service_guarded_and_not_profile_fields(self):
        services.add_note(self.char1, self.account2, "Private discussion")
        self.assertEqual(StaffNote.objects.get().actor_id, self.account.pk)
        with self.assertRaises(PermissionDenied):
            services.add_note(self.char2, self.account2, "Fake note")

    def test_web_backend_blocks_password_and_autologin_during_softban(self):
        self.account2.set_password(PASSWORD)
        self.account2.save()
        request = RequestFactory().post("/accounts/login/", REMOTE_ADDR="198.51.100.12")
        backend = ModerationBackend()
        self.assertEqual(
            backend.authenticate(request, username=self.account2.key, password=PASSWORD),
            self.account2,
        )
        services.restrict(self.char1, kind="softban", account=self.account2, reason="Stop")
        with self.assertRaises(PermissionDenied):
            backend.authenticate(request, username=self.account2.key, password=PASSWORD)
        with self.assertRaises(PermissionDenied):
            backend.authenticate(request, autologin=self.account2)

    def test_existing_web_session_is_logged_out_and_ip_bans_apply_to_anonymous_requests(self):
        services.restrict(self.char1, kind="softban", account=self.account2, reason="Stop")
        request = RequestFactory().get("/", REMOTE_ADDR="198.51.100.1")
        request.user = self.account2
        with patch("evennia_moderation.auth.logout") as logout:
            response = ModerationMiddleware(Mock())(request)
        self.assertEqual(response.status_code, 403)
        logout.assert_called_once_with(request)
        services.restrict(self.char1, kind="softban", address="192.0.2.0/24", reason="Stop")
        request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.12")
        self.assertEqual(ModerationMiddleware(Mock())(request).status_code, 403)

    def test_connections_are_disconnected_only_after_commit(self):
        with patch("evennia_moderation.services._disconnect") as disconnect:
            with self.captureOnCommitCallbacks(execute=True):
                services.restrict(self.char1, kind="softban", account=self.account2, reason="Stop")
                disconnect.assert_not_called()
            disconnect.assert_called_once()

    def test_address_purge_keeps_history_and_active_restrictions(self):
        application = self.apply()
        self.review(application, "declined")
        Application.objects.filter(pk=application.pk).update(
            decided_at=timezone.now() - timedelta(days=91)
        )
        expired = services.restrict(self.char1, kind="softban", address="192.0.2.1", reason="Old")
        ModerationAction.objects.filter(pk=expired.pk).update(
            ends_at=timezone.now() - timedelta(days=91)
        )
        active = services.restrict(
            self.char1, kind="softban", address="198.51.100.1", reason="Current"
        )
        services.purge()
        application.refresh_from_db()
        expired.refresh_from_db()
        active.refresh_from_db()
        self.assertIsNone(application.address)
        self.assertEqual(expired.address, "")
        self.assertEqual(expired.reason, "Old")
        self.assertNotEqual(active.address, "")


@override_settings(JOBS_REQUEST_FORMS=FORMS, MODERATION_REFERRAL_ALLOWANCE=2)
class TestCommands(AdmissionFixture, EvenniaCommandTest):
    def test_account_paging_cannot_bypass_mute_before_puppeting(self):
        from evennia_moderation.commands import CmdAccountPage

        services.restrict(self.char1, kind="mute", account=self.account2, reason="Stop")
        self.call(
            CmdAccountPage(), f"{self.visitor.key}=A message", "You are muted", caller=self.account2
        )
        self.call(
            CmdAccountPage(),
            f"{self.account.key}=Staff, please help.",
            "You paged",
            caller=self.account2,
        )

    def test_invalid_duration_preserves_existing_restriction(self):
        services.restrict(self.char1, kind="softban", account=self.account2, reason="Stop")
        self.call(CmdSoftban(), f"/duration {self.account2.key}=99999999999999", "Duration must be")
        self.assertEqual(ModerationAction.objects.count(), 1)
        self.assertIsNone(ModerationAction.objects.get().lifted_at)

    @override_settings(MODERATION_REFERRAL_MODE="off")
    def test_interactive_application_never_records_password_in_job(self):
        from evennia_moderation.commands import CmdApply

        command = CmdApply()
        command.caller = self.guest
        command.session = self.session
        with (
            patch.object(self.session, "address", ("192.0.2.77", 4000)),
            patch.object(self.guest, "msg") as messages,
        ):
            flow = command.func()
            self.assertIn("account name", next(flow))
            self.assertIn("password", flow.send("InteractivePlayer"))
            self.assertEqual(flow.send(PASSWORD), "Why join?")
            with self.assertRaises(StopIteration):
                flow.send("I enjoy roleplay.")
            self.assertIn("submitted", str(messages.call_args))
        application = Application.objects.get(account_name="InteractivePlayer")
        self.assertTrue(check_password(PASSWORD, application.password_hash))
        self.assertNotIn(PASSWORD, str(application.job.submissions.get().answers))

    def test_stock_ban_and_unban_keep_action_history(self):
        from evennia.server.models import ServerConfig

        from evennia_moderation.commands import CmdBan, CmdUnban

        ServerConfig.objects.conf("server_bans", [])
        self.call(CmdBan(), self.account2.key + ": Incident", inputs=["yes"])
        self.assertEqual(ModerationAction.objects.filter(kind="ban").count(), 1)
        self.call(CmdUnban(), "1", inputs=["yes"])
        self.assertEqual(ModerationAction.objects.filter(kind="lift").count(), 1)

    def test_stock_wildcard_ip_ban_is_captured_and_lifted(self):
        from evennia_moderation.commands import CmdBan, CmdUnban
        from evennia_moderation.policy import stock_banned

        self.call(CmdBan(), "/ip 192.0.2.*: Incident", inputs=["yes"])
        self.assertTrue(stock_banned(address="192.0.2.77"))
        self.assertIsNotNone(connection_restriction(address="192.0.2.77"))
        self.call(CmdUnban(), "1", inputs=["yes"])
        self.assertFalse(stock_banned(address="192.0.2.77"))
        self.assertIsNone(connection_restriction(address="192.0.2.77"))

    def test_ambiguous_character_name_is_refused_before_moderating(self):
        duplicate = create_object("evennia.objects.objects.DefaultCharacter", key=self.char2.key)
        self.account.characters.add(duplicate)
        self.call(CmdSoftban(), f"{self.char2.key}=Reason", "That character name is ambiguous")
        self.assertFalse(ModerationAction.objects.exists())

    def test_player_cannot_read_notes_or_admissions_or_apply_staff_restrictions(self):
        for command, args in [
            (CmdNotes(), self.account.key),
            (CmdAdmissions(), ""),
            (CmdSoftban(), f"{self.account.key}=test"),
            (CmdMute(), f"{self.account.key}=test"),
        ]:
            self.call(command, args, "Only moderation staff", caller=self.char2)
        self.assertFalse(ModerationAction.objects.exists())

    def test_staff_commands_are_unavailable_and_unlisted_for_players(self):
        for command in (CmdNotes(), CmdAdmissions(), CmdSoftban(), CmdMute()):
            with self.subTest(command=command.key):
                self.assertFalse(command.access(self.char2, "cmd"))
                self.assertTrue(command.access(self.char1, "cmd"))
        self.account.is_superuser = False  # superusers bypass every lock
        self.account.save()
        with override_settings(MODERATION_STAFF_LOCK="cmd:false()"):
            self.assertFalse(CmdSoftban().access(self.char1, "cmd"))

    def test_staff_softban_and_lift(self):
        self.call(CmdSoftban(), f"{self.account2.key}=Reason", "Recorded softban")
        self.call(CmdSoftban(), f"/lift {self.account2.key}", "Lifted 1")

    def test_player_can_issue_and_list_only_their_codes(self):
        self.call(CmdReferral(), "", "Referral code", caller=self.char2)
        self.call(CmdReferral(), "/list", "Remaining allowance: 1", caller=self.char2)

    def test_staff_admission_approval_uses_real_jobs_review(self):
        application = self.apply()
        self.call(
            CmdAdmissions(),
            f"/approve {application.job.job_number}=Welcome",
            "Application reviewed",
        )
        self.assertTrue(AccountDB.objects.filter(username="NewPlayer").exists())
