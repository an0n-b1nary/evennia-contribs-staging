# SPDX-License-Identifier: BSD-3-Clause
"""File-backed races: seats, codes, allowances and review decisions."""

from unittest.mock import Mock

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TransactionTestCase, override_settings
from evennia.server.models import ServerConfig
from evennia.utils.test_resources import EvenniaTestMixin
from evennia_jobs.models import RequestDecision

from evennia_links.test_transactions import committed_race
from evennia_moderation import admissions
from evennia_moderation.commands import CmdBan, CmdUnban
from evennia_moderation.models import AdmissionsState, Application, ModerationAction, Referral
from evennia_moderation.policy import active_actions, stock_bans
from evennia_moderation.tests import FORMS, AdmissionFixture


@override_settings(JOBS_REQUEST_FORMS=FORMS, MODERATION_REFERRAL_ALLOWANCE=1)
class TestAdmissionRaces(AdmissionFixture, EvenniaTestMixin, TransactionTestCase):
    def prompt(self, command_type, args):
        command = command_type()
        command.caller = self.char1
        command.args = args
        command.switches = []
        command.session = Mock(address="192.0.2.1")
        command.msg = Mock()
        flow = command.func()
        next(flow)
        return flow

    @staticmethod
    def finish(flow):
        try:
            flow.send("yes")
        except StopIteration:
            return
        raise AssertionError("Unexpected additional confirmation prompt")

    def test_two_staff_bans_cannot_overwrite_each_other(self):
        first = self.prompt(CmdBan, self.account2.key + ": first incident")
        second = self.prompt(CmdBan, self.account2.key + ": second incident")
        committed_race(lambda: self.finish(first), lambda: self.finish(second))
        self.assertEqual(len(stock_bans()), 2)
        self.assertEqual(ModerationAction.objects.filter(kind="ban").count(), 2)

    def test_two_unbans_do_not_restore_a_cleared_ban(self):
        self.finish(self.prompt(CmdBan, self.account2.key + ": first incident"))
        self.finish(self.prompt(CmdBan, self.account2.key + ": second incident"))
        first = self.prompt(CmdUnban, "1")
        second = self.prompt(CmdUnban, "2")
        committed_race(lambda: self.finish(first), lambda: self.finish(second))
        self.assertEqual(stock_bans(), [])
        self.assertFalse(active_actions("ban").exists())

    def setUp(self):
        super().setUp()
        if connection.vendor == "sqlite" and "mode=memory" in connection.settings_dict["NAME"]:
            self.skipTest("Run separately with a file-backed TEST database")
        AdmissionsState.objects.get_or_create(pk=1)
        ServerConfig.objects.conf("server_bans", [])

    @override_settings(MODERATION_PLAYER_CAP=2)
    def test_two_applications_for_final_seat(self):
        with self.assertRaisesMessage(ValidationError, "capacity"):
            committed_race(lambda: self.apply("FirstPlayer"), lambda: self.apply("SecondPlayer"))
        self.assertEqual(Application.objects.filter(status="pending").count(), 1)

    def test_two_applications_for_same_code(self):
        code = admissions.issue_code(self.account2).code
        with self.assertRaisesMessage(ValidationError, "code is unavailable"):
            committed_race(
                lambda: self.apply("FirstPlayer", code=code),
                lambda: self.apply("SecondPlayer", code=code),
            )
        self.assertEqual(Application.objects.count(), 1)

    def test_two_applications_for_case_insensitive_name(self):
        with self.assertRaisesMessage(ValidationError, "unavailable"):
            committed_race(lambda: self.apply("FirstPlayer"), lambda: self.apply("firstplayer"))
        self.assertEqual(Application.objects.count(), 1)

    def test_two_code_issues_for_final_allowance(self):
        with self.assertRaisesMessage(ValidationError, "no referral allowance"):
            committed_race(
                lambda: admissions.issue_code(self.account2),
                lambda: admissions.issue_code(self.account2),
            )

    def test_two_approvals_create_only_one_account_and_referral(self):
        application = self.apply()
        committed_race(lambda: self.review(application), lambda: self.review(application))
        self.assertEqual(Referral.objects.count(), 1)
        self.assertEqual(RequestDecision.objects.count(), 1)

    def test_decline_and_approval_cannot_both_commit(self):
        application = self.apply()
        with self.assertRaisesMessage(ValidationError, "already been reviewed"):
            committed_race(
                lambda: self.review(application, "declined"), lambda: self.review(application)
            )
        self.assertFalse(Referral.objects.exists())
        self.assertEqual(RequestDecision.objects.get().outcome, "declined")
