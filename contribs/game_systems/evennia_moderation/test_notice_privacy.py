# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Real admissions fallback must respect the host's communication identity."""

from unittest.mock import Mock, patch

from django.test import override_settings
from evennia.utils.test_resources import EvenniaTest

from evennia_moderation import admissions
from evennia_moderation.tests import FORMS, AdmissionFixture


@override_settings(
    JOBS_REQUEST_FORMS=FORMS,
    MODERATION_REFERRAL_ALLOWANCE=3,
    NOTICES_ENABLED=False,
    LINKS_NOTICE_SOURCES={},
)
class TestOutcomeIdentity(AdmissionFixture, EvenniaTest):
    """Use APIs present before the adapter, with positive transport evidence."""

    def deliver_approval(self):
        code = admissions.issue_code(self.account2)
        application = self.apply("DistinctiveApplicantAccount", code=code.code)
        self.review(application)
        output = []
        session = Mock()
        session.get_account.return_value = self.account2
        session.get_puppet.return_value = self.char2
        session.msg.side_effect = output.append
        with (
            patch.object(self.account2.sessions, "count", return_value=1),
            patch.object(self.account2, "msg", side_effect=output.append),
            patch("evennia.server.sessionhandler.SESSIONS.get_sessions", return_value=[session]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            admissions.deliver_notices(self.account2)
        self.assertEqual(len(output), 1, "One real source outcome must reach transport")
        self.assertIn("approved", output[0])
        return output[0]

    @override_settings(EVENNIA_COMMS_IDENTITY="character")
    def test_character_mode_does_not_disclose_applicant_account(self):
        self.assertNotIn("DistinctiveApplicantAccount", self.deliver_approval())

    @override_settings(EVENNIA_COMMS_IDENTITY="account")
    def test_account_mode_preserves_intended_applicant_name(self):
        self.assertIn("DistinctiveApplicantAccount", self.deliver_approval())
