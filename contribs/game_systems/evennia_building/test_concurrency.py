"""Quota changes serialize across projects owned by the same character."""

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TransactionTestCase, override_settings
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaTestMixin

from evennia_links.test_transactions import committed_race

from . import attachments, lifecycle, services
from .models import BuildProject, BuildReview, Property
from .request_form import FORM, FORM_KEY


@override_settings(BUILDING_REVEALED=True, BUILDING_PROJECT_LIMIT=2)
class TestQuotaRace(EvenniaTestMixin, TransactionTestCase):
    def test_two_new_projects_cannot_exceed_owner_quota(self):
        if connection.vendor == "sqlite" and "mode=memory" in connection.settings_dict["NAME"]:
            self.skipTest("Race gate runs separately with a file-backed SQLite TEST database")
        services.new_project(self.char2, "Existing proposal")
        with self.assertRaisesMessage(ValidationError, "open-project"):
            committed_race(
                lambda: services.new_project(self.char2, "Winning proposal"),
                lambda: services.new_project(self.char2, "Losing proposal"),
            )
        self.assertEqual(BuildProject.objects.filter(owner=self.char2).count(), 2)


@override_settings(
    BUILDING_REVEALED=True,
    JOBS_REQUEST_FORMS={FORM_KEY: FORM},
    BUILDING_REUSE_ACKNOWLEDGEMENT="Race acknowledgement",
)
class TestApartmentRaces(EvenniaTestMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        if connection.vendor == "sqlite" and "mode=memory" in connection.settings_dict["NAME"]:
            self.skipTest("Race gate runs separately with a file-backed SQLite TEST database")
        self.tenant = create_object(self.character_typeclass, key="Race tenant")
        self.room1.db.room_type = "ic"
        parent = services.new_project(self.char2, "Race parent")
        services.attach(self.char2, parent, self.room1, "parent")
        parent.refresh_from_db()
        submission = services.submit(
            self.char2,
            parent,
            expected_version=parent.version,
            acknowledgement="Race acknowledgement",
        )
        services.review(
            self.char1,
            submission,
            expected_revision=1,
            outcome="approved",
            reason="Parent approved",
        )
        self.parent = Property.objects.get(promotion=submission)
        project = services.new_project(self.tenant, "Race apartment")
        services.attach(self.tenant, project, parent.rooms.get(entry=True).room, "apartment")
        project.refresh_from_db()
        self.consent = attachments.request_consent(
            self.tenant, project, expected_version=project.version
        )
        attachments.answer_consent(
            self.char2, self.consent, action="grant", acknowledgement=self.consent.wording
        )
        self.submission = services.submit(
            self.tenant,
            project,
            expected_version=project.version,
            acknowledgement="Race acknowledgement",
        )

    def approve(self):
        return services.review(
            self.char1,
            self.submission,
            expected_revision=1,
            outcome="approved",
            reason="Race reviewed",
        )

    def revoke(self):
        return attachments.answer_consent(self.char2, self.consent, action="revoke")

    def test_revoke_commits_first_blocks_approval(self):
        with self.assertRaisesMessage(ValidationError, "consent"):
            committed_race(self.revoke, self.approve)
        self.assertFalse(Property.objects.filter(promotion=self.submission).exists())
        self.assertFalse(BuildReview.objects.filter(submission=self.submission).exists())

    def test_approval_commits_first_blocks_revoke(self):
        with self.assertRaises(ValidationError):
            committed_race(self.approve, self.revoke)
        self.assertEqual(Property.objects.filter(promotion=self.submission).count(), 1)
        self.consent.refresh_from_db()
        self.assertEqual(self.consent.state, "consumed")

    def test_parent_archive_commits_first_blocks_promotion(self):
        with self.assertRaisesMessage(ValidationError, "unavailable"):
            committed_race(
                lambda: lifecycle.archive(
                    self.char1, self.parent, reason="Archive before apartment approval"
                ),
                self.approve,
            )
        self.assertFalse(Property.objects.filter(promotion=self.submission).exists())

    def test_promotion_commits_first_blocks_stranding_archive(self):
        with self.assertRaisesMessage(ValidationError, "strand"):
            committed_race(
                self.approve,
                lambda: lifecycle.archive(self.char1, self.parent, reason="Parent archive race"),
            )
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.state, "live")
