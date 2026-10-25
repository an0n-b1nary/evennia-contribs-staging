# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Exercise the data migration on populated receipts, archives and pending reviews."""

from importlib import import_module

from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaTest

from . import attachments, collaboration, doors, lifecycle, services
from .models import AttachmentAgreement, BuildSubmission, Property
from .request_form import FORM, FORM_KEY


@override_settings(
    BUILDING_REVEALED=True,
    JOBS_REQUEST_FORMS={FORM_KEY: FORM},
    LINKS_ROOM_PERMISSION="evennia_building.access.room_permission",
    LINKS_ROOM_OWNER="evennia_building.access.owner_of",
)
class DestinationDoorUpgradeTests(EvenniaTest):
    """Run the frozen migration with historical models against real legacy data."""

    def submit(self, actor, project):
        project.refresh_from_db()
        return services.submit(
            actor,
            project,
            expected_version=project.version,
            acknowledgement=collaboration.wording("contributor"),
        )

    def approve(self, actor, project):
        submission = self.submit(actor, project)
        services.review(
            self.char1,
            submission,
            expected_revision=submission.revision,
            outcome="approved",
            reason="Reviewed",
        )
        return Property.objects.get(promotion=submission)

    def test_populated_upgrade_preserves_passage_archives_and_jobs_review(self):
        self.room1.db.room_type = "ic"
        self.room1.db.allow_teleport = "public"
        self.room1.key = "Market Street"
        project = services.new_project(self.char2, "Parent Home")
        entry = project.rooms.get(entry=True)
        hall = services.dig(
            self.char2, project, entry, "Passage Hall", door="inside", back="out", x=1
        )
        services.attach(self.char2, project, self.room1, "Parent Home")
        parent = self.approve(self.char2, project)
        # Reproduce the 0.3 boundary names before creating its agreements.
        parent.entrance.aliases.clear()
        parent.departure.attributes.remove(doors.FOLLOW)
        parent.departure.aliases.clear()
        parent.departure.key = "outside"
        tenant = create_object("evennia.objects.objects.DefaultCharacter", key="Apartment Owner")
        child_project = services.new_project(tenant, "Child Home")
        services.attach(tenant, child_project, hall.room, "Child Home")
        child_project.refresh_from_db()
        consent = attachments.request_consent(
            tenant, child_project, expected_version=child_project.version
        )
        attachments.answer_consent(
            self.char2, consent, action="grant", acknowledgement=consent.wording
        )
        child = self.approve(tenant, child_project)
        child.entrance.aliases.clear()
        child.departure.attributes.remove(doors.FOLLOW)
        child.departure.aliases.clear()
        child.departure.key = "outside"
        lifecycle.archive(self.char1, parent, reason="Temporary closure", include_children=True)

        pending = services.new_project(self.char2, "Pending Home")
        pending_entry = pending.rooms.get(entry=True)
        services.dig(self.char2, pending, pending_entry, "Kitchen", door="inside", back="out", y=1)
        self.room2.db.room_type = "ic"
        self.room2.db.allow_teleport = "public"
        services.attach(self.char2, pending, self.room2, "Pending Home")
        submission = self.submit(self.char2, pending)
        previous_fingerprint = submission.fingerprint
        ids = set(ObjectDB.objects.values_list("pk", flat=True))
        historical = MigrationExecutor(connection).loader.project_state().apps
        migration = import_module("evennia_building.migrations.0005_destination_door_names")
        # RunPython performs data writes only; its schema editor is not entered
        # because EvenniaTest already owns the surrounding SQLite transaction.
        migration.destination_door_names(historical, connection.schema_editor())
        # Historical models bypass Evennia's idmapper. A deployed upgrade
        # starts a fresh process; mirror that by refreshing scalar cache data.
        for obj in ObjectDB.get_all_cached_instances():
            obj.__dict__.update(ObjectDB.objects.filter(pk=obj.pk).values("db_key").get())
            obj._state.fields_cache.clear()
            obj.attributes.reset_cache()
            obj.aliases.reset_cache()
            obj.tags.reset_cache()
        self.assertEqual(set(ObjectDB.objects.values_list("pk", flat=True)), ids)
        parent.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(parent.departure.key, "Market Street")
        self.assertEqual(set(parent.departure.aliases.all()), {"out", "o", "outside"})
        self.assertIn("in", parent.entrance.aliases.all())
        self.assertEqual(project.doors.get(target=hall).exit.key, "Passage Hall")
        self.assertEqual(
            doors.canonical(services._exit_data(parent.entrance)),
            doors.canonical({**parent.archive_data["entrance"], "source": None}),
        )
        self.assertEqual(
            doors.canonical(services._exit_data(parent.departure)),
            doors.canonical(parent.archive_data["departure"]),
        )
        lifecycle.restore(self.char1, parent, reason="Reopen parent")
        lifecycle.restore(self.char1, child, reason="Reopen child")
        agreement = AttachmentAgreement.objects.get(child=child)
        self.assertTrue(attachments.route_valid(agreement))
        self.room1.key = "Market Square"
        self.assertEqual(parent.departure.key, "Market Square")
        self.assertTrue(attachments.route_valid(agreement))
        submission = BuildSubmission.objects.get(pk=submission.pk)
        self.assertNotEqual(submission.fingerprint, previous_fingerprint)
        if apps.is_installed("evennia_jobs"):
            from evennia_jobs.models import RequestSubmission

            from .jobs import _binding

            self.assertEqual(
                _binding(RequestSubmission.objects.get(pk=submission.jobs_submission_id)),
                submission,
            )
        services.review(
            self.char1,
            submission,
            expected_revision=submission.revision,
            outcome="approved",
            reason="Approve upgraded pending proposal",
        )
        self.assertTrue(Property.objects.filter(promotion=submission).exists())
