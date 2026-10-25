"""Apartments retain independent rights while protecting only agreed passage."""

from datetime import timedelta
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.http import Http404
from django.test import RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTestMixin, EvenniaTest

from . import attachments, lifecycle, services
from .access import can_enter, can_teleport, room_permission
from .models import (
    AttachmentAgreement,
    AttachmentConsent,
    BuildAudit,
    BuildingClock,
    BuildReview,
    Property,
    QuietFlag,
)
from .request_form import FORM, FORM_KEY
from .tests import ACK
from .visibility import room_visibility


@override_settings(
    ROOT_URLCONF="evennia_building.tests",
    BUILDING_REVEALED=True,
    BUILDING_REUSE_ACKNOWLEDGEMENT=ACK,
    JOBS_REQUEST_FORMS={FORM_KEY: FORM},
    LINKS_ROOM_PERMISSION="evennia_building.access.room_permission",
    LINKS_ROOM_OWNER="evennia_building.access.owner_of",
    LINKS_ROOM_TRAVEL="evennia_building.access.can_teleport",
    LINKS_ROOM_VISIBILITY="evennia_building.visibility.room_visibility",
    BUILDING_ACTIVITY_PROVIDER="evennia_building.lifecycle.last_played",
)
class TestApartments(EvenniaCommandTestMixin, EvenniaTest):
    def setUp(self):
        super().setUp()
        self.room1.db.room_type = "ic"
        self.room1.db.allow_teleport = "public"
        self.tenant = create_object(
            self.character_typeclass, key="Apartment Owner", location=self.room1
        )
        self.guest = create_object(
            self.character_typeclass, key="Apartment Guest", location=self.room1
        )
        self.parent_project = services.new_project(self.char2, "Parent home")
        self.entry = self.parent_project.rooms.get(entry=True)
        self.hall = services.dig(
            self.char2, self.parent_project, self.entry, "Passage hall", door="hall", x=1
        )
        self.bedroom = services.dig(
            self.char2, self.parent_project, self.hall, "Parent bedroom", door="bedroom", x=2
        )
        services.attach(self.char2, self.parent_project, self.room1, "parent home")
        self.parent = self.approve(self.char2, self.parent_project)
        self.project = services.new_project(self.tenant, "Independent apartment")
        self.child_entry = self.project.rooms.get(entry=True)
        services.attach(self.tenant, self.project, self.hall.room, "apartment")
        self.project.refresh_from_db()

    def submit(self, actor, project):
        project.refresh_from_db()
        return services.submit(
            actor, project, expected_version=project.version, acknowledgement=ACK
        )

    def approve(self, actor, project):
        submission = self.submit(actor, project)
        services.review(
            self.char1,
            submission,
            expected_revision=submission.revision,
            outcome="approved",
            reason="Reviewed exact proposal.",
        )
        return Property.objects.get(promotion=submission)

    def consent(self):
        self.project.refresh_from_db()
        consent = attachments.request_consent(
            self.tenant, self.project, expected_version=self.project.version
        )
        attachments.answer_consent(
            self.char2, consent, action="grant", acknowledgement=consent.wording
        )
        consent.refresh_from_db()
        return consent

    def apartment(self):
        self.consent()
        self.child = self.approve(self.tenant, self.project)
        self.agreement = AttachmentAgreement.objects.get(child=self.child)
        return self.child

    def test_owner_only_exact_consent_and_inspection(self):
        consent = attachments.request_consent(
            self.tenant, self.project, expected_version=self.project.version
        )
        self.assertIn("cannot lock", consent.wording)
        services.set_resident(self.char2, self.parent, self.guest)
        for actor in (self.guest, self.tenant, self.char1):
            with self.assertRaises(PermissionDenied):
                attachments.answer_consent(
                    actor, consent, action="grant", acknowledgement=consent.wording
                )
        with self.assertRaisesMessage(ValidationError, "acknowledge"):
            attachments.answer_consent(self.char2, consent, action="grant")
        self.assertFalse(room_visibility(self.child_entry.room, self.char2))
        self.assertFalse(room_permission(self.char2, self.child_entry.room, "describe"))
        self.assertTrue(attachments.visible_consents(self.char2).filter(pk=consent.pk).exists())
        self.assertFalse(attachments.visible_consents(self.guest).filter(pk=consent.pk).exists())
        attachments.answer_consent(self.char2, consent, action="decline")
        with self.assertRaisesMessage(ValidationError, "consent"):
            self.submit(self.tenant, self.project)

    def test_candidate_edits_invalidate_grant_and_history_survives(self):
        consent = self.consent()
        services.edit_project(
            self.tenant, self.project, room=self.child_entry, description="Changed material content"
        )
        consent.refresh_from_db()
        self.assertEqual(consent.state, "invalidated")
        self.assertEqual(consent.candidate["rooms"][0]["description"], "")
        with self.assertRaisesMessage(ValidationError, "consent"):
            self.submit(self.tenant, self.project)
        self.consent()
        self.approve(self.tenant, self.project)
        self.assertEqual(AttachmentConsent.objects.count(), 2)

    def test_direct_edit_transfer_route_and_policy_revalidated(self):
        consent = self.consent()
        self.child_entry.room.db.desc = "Direct staff mutation"
        with self.assertRaisesMessage(ValidationError, "consent"):
            self.submit(self.tenant, self.project)
        self.child_entry.room.db.desc = ""
        services.transfer(
            self.char1,
            self.parent,
            self.guest,
            expected_owner=self.char2.pk,
            reason="Transfer before approval",
        )
        consent.refresh_from_db()
        self.assertEqual(consent.state, "invalidated")
        with self.assertRaisesMessage(ValidationError, "consent"):
            self.submit(self.tenant, self.project)
        with self.assertRaises(PermissionDenied):
            attachments.answer_consent(self.char2, consent, action="revoke")

    def test_revocation_rolls_back_review_and_jobs(self):
        consent = self.consent()
        submission = self.submit(self.tenant, self.project)
        attachments.answer_consent(self.char2, consent, action="revoke")
        with self.assertRaisesMessage(ValidationError, "consent"):
            services.review(
                self.char1,
                submission,
                expected_revision=1,
                outcome="approved",
                reason="No longer consented",
            )
        self.assertFalse(BuildReview.objects.filter(submission=submission).exists())
        self.assertFalse(Property.objects.filter(promotion=submission).exists())
        if apps.is_installed("evennia_jobs"):
            from evennia_jobs.models import RequestDecision

            self.assertFalse(
                RequestDecision.objects.filter(submission_id=submission.jobs_submission_id).exists()
            )
        self.project.refresh_from_db()
        self.assertEqual(self.project.state, "submitted")

    def test_promotion_consumes_receipt_and_independent_ownership(self):
        child = self.apartment()
        self.assertEqual(self.agreement.consent.state, "consumed")
        self.assertEqual(self.agreement.route["rooms"], [self.entry.room_id, self.hall.room_id])
        self.assertEqual(child.owner_id, self.tenant.pk)
        for action in ("describe", "configure", "install"):
            self.assertFalse(room_permission(self.char2, self.child_entry.room, action))
            self.assertFalse(room_permission(self.tenant, self.hall.room, action))
        self.assertEqual(services.promote(child.promotion, self.char1).pk, child.pk)
        with self.assertRaisesMessage(ValidationError, "consent"):
            attachments.answer_consent(self.char2, self.agreement.consent, action="revoke")

    def test_guest_passage_survives_parent_locks_overrides_and_removals(self):
        child = self.apartment()
        services.set_locked(self.char2, self.parent, True)
        services.set_override(self.char2, self.hall.room, [])
        services.set_resident(self.char2, self.parent, self.tenant, remove=True)
        for room in (self.entry.room, self.hall.room):
            self.assertTrue(can_enter(self.tenant, room))
            self.assertFalse(room_visibility(room, self.tenant))
            self.assertFalse(can_teleport(self.tenant, room))
        self.assertFalse(can_enter(self.tenant, self.bedroom.room))
        self.assertFalse(can_enter(self.guest, self.entry.room))
        invitation = services.invite(self.tenant, child, self.guest, entry=True, maps=False)
        self.assertFalse(can_enter(self.guest, self.entry.room))
        services.answer_invitation(self.guest, invitation, accept=True)
        for room in (self.entry.room, self.hall.room):
            self.assertTrue(can_enter(self.guest, room))
            self.assertFalse(room_visibility(room, self.guest))
        self.assertFalse(can_enter(self.guest, self.bedroom.room))
        self.assertFalse(room_visibility(self.child_entry.room, self.guest))
        services.set_locked(self.tenant, child, True)
        self.assertTrue(can_enter(self.guest, self.child_entry.room))
        services.invite(self.tenant, child, self.guest, revoke=True)
        self.assertFalse(can_enter(self.guest, self.entry.room))
        self.assertTrue(attachments.departure_allows(self.parent.departure))

    def test_unrelated_traversal_does_not_revalidate_agreed_routes(self):
        self.apartment()
        bedroom_door = ObjectDB.objects.get(
            db_location=self.hall.room, db_destination=self.bedroom.room
        )
        with patch.object(attachments, "route_valid", wraps=attachments.route_valid) as checked:
            self.assertFalse(attachments.departure_allows(self.exit))
            self.assertFalse(attachments.departure_allows(bedroom_door))
        checked.assert_not_called()
        self.assertTrue(attachments.departure_allows(self.parent.departure))

    def test_exit_deletion_checks_only_related_agreements(self):
        child = self.apartment()
        with CaptureQueriesContext(connection) as queries:
            self.assertFalse(attachments.protected_exit(self.exit))
        self.assertFalse(
            any("attachmentagreement" in row["sql"].lower() for row in queries.captured_queries)
        )
        route_door = ObjectDB.objects.get(
            db_location=self.entry.room, db_destination=self.hall.room
        )
        for exit in (
            route_door,
            self.parent.entrance,
            self.parent.departure,
            child.entrance,
            child.departure,
        ):
            self.assertTrue(attachments.protected_exit(exit))
        bedroom_door = ObjectDB.objects.get(
            db_location=self.hall.room, db_destination=self.bedroom.room
        )
        self.assertFalse(attachments.protected_exit(bedroom_door))

    def test_map_only_invitation_and_unlocked_child_do_not_grant_passage(self):
        child = self.apartment()
        services.set_locked(self.char2, self.parent, True)
        invitation = services.invite(self.tenant, child, self.guest, entry=False, maps=True)
        services.answer_invitation(self.guest, invitation, accept=True)
        self.assertTrue(room_visibility(self.child_entry.room, self.guest))
        self.assertFalse(can_enter(self.guest, self.entry.room))

    def test_resident_and_transfer_preserve_passage_without_parent_grants(self):
        child = self.apartment()
        services.set_resident(self.tenant, child, self.guest)
        services.set_locked(self.char2, self.parent, True)
        self.assertTrue(can_enter(self.guest, self.hall.room))
        services.transfer(
            self.char1,
            self.parent,
            self.guest,
            expected_owner=self.char2.pk,
            reason="New parent owner",
        )
        self.assertTrue(can_enter(self.tenant, self.hall.room))
        self.assertFalse(room_permission(self.guest, self.child_entry.room, "install"))
        services.transfer(
            self.char1, child, self.char2, expected_owner=self.tenant.pk, reason="New child owner"
        )
        self.assertTrue(can_enter(self.char2, self.hall.room))
        self.assertFalse(can_enter(self.tenant, self.hall.room))

    def test_nested_cross_property_cyclic_and_broken_routes_refused(self):
        child = self.apartment()
        project = services.new_project(self.char2, "Nested")
        with self.assertRaisesMessage(ValidationError, "Nested"):
            services.attach(self.char2, project, self.child_entry.room, "nested")
        for route in (
            [self.entry.room_id, self.room1.pk, self.hall.room_id],
            [self.entry.room_id, self.entry.room_id, self.hall.room_id],
            [self.hall.room_id],
        ):
            with self.assertRaises(ValidationError):
                attachments.route_snapshot(self.parent, route, self.hall.room_id)
        door = self.parent_project.doors.get(source=self.entry, target=self.hall).exit
        door.destination = self.room1
        services.set_locked(self.char2, self.parent, True)
        self.assertFalse(can_enter(self.tenant, self.hall.room))
        self.assertEqual(child.state, "live")
        door.destination = self.hall.room
        self.assertEqual(self.parent.entrance.db_destination_id, self.entry.room_id)
        ObjectDB.objects.filter(pk=self.parent.entrance_id).update(
            db_destination_id=self.bedroom.room_id
        )
        # Another process's edit must be checked against SQL, not an idmapper instance.
        self.assertEqual(self.parent.entrance.db_destination_id, self.entry.room_id)
        with self.assertRaisesMessage(ValidationError, "usable entrance"):
            attachments.route_snapshot(
                self.parent, [self.entry.room_id, self.hall.room_id], self.hall.room_id
            )

    def test_closed_policy_after_consent_blocks_promotion(self):
        self.consent()
        submission = self.submit(self.tenant, self.project)
        self.hall.room.tags.add("closed", category="build_policy")
        with self.assertRaisesMessage(ValidationError, "closed"):
            services.review(
                self.char1, submission, expected_revision=1, outcome="approved", reason="Closed now"
            )
        self.assertFalse(BuildReview.objects.filter(submission=submission).exists())

    def test_self_owned_attachment_is_recorded_and_not_blanket_consent(self):
        project = services.new_project(self.char2, "Self-owned wing")
        services.attach(self.char2, project, self.entry.room, "wing")
        project.refresh_from_db()
        consent = attachments.request_consent(self.char2, project, expected_version=project.version)
        self.assertEqual(consent.state, "granted")
        wing = self.approve(self.char2, project)
        self.assertEqual(AttachmentAgreement.objects.get(child=wing).consent_id, consent.pk)

    def test_promotion_failure_restores_consent_and_connections(self):
        consent = self.consent()
        submission = self.submit(self.tenant, self.project)
        with (
            patch(
                "evennia_building.attachments.consume",
                side_effect=ValidationError("Injected agreement failure"),
            ),
            self.assertRaises(ValidationError),
        ):
            services.review(
                self.char1,
                submission,
                expected_revision=1,
                outcome="approved",
                reason="Fail atomically",
            )
        consent.refresh_from_db()
        self.assertEqual(consent.state, "granted")
        self.assertFalse(
            ObjectDB.objects.filter(
                db_location=self.hall.room, db_destination=self.child_entry.room
            ).exists()
        )
        self.assertFalse(Property.objects.filter(promotion=submission).exists())

    def test_archive_refuses_stranding_and_requires_staff(self):
        child = self.apartment()
        for actor in (self.char2, self.tenant):
            with self.assertRaises(PermissionDenied):
                lifecycle.archive(actor, child, reason="No ordinary owner archival")
        with self.assertRaisesMessage(ValidationError, "strand"):
            lifecycle.archive(self.char1, self.parent, reason="Parent alone")
        self.assertEqual(self.parent.entrance.location, self.room1)

    def test_archive_restore_keeps_ids_contents_ownership_agreement_and_exit(self):
        child = self.apartment()
        keepsake = create_object(
            "evennia.objects.objects.DefaultObject", key="Keepsake", location=self.child_entry.room
        )
        self.guest.location = self.child_entry.room
        before = (
            child.pk,
            self.child_entry.room_id,
            child.entrance_id,
            child.departure_id,
            self.agreement.pk,
        )
        lifecycle.archive(self.char1, child, reason="Temporary retirement")
        child.refresh_from_db()
        self.assertEqual(child.state, "archived")
        self.assertIsNone(child.entrance.location)
        self.assertEqual(keepsake.location, self.child_entry.room)
        self.assertEqual(self.guest.location, self.room1)
        self.assertTrue(attachments.departure_allows(self.parent.departure))
        self.assertFalse(room_visibility(self.child_entry.room, self.tenant))
        self.assertFalse(can_enter(self.tenant, self.child_entry.room))
        lifecycle.restore(self.char1, child, reason="Return home")
        child.refresh_from_db()
        self.assertEqual(
            before,
            (
                child.pk,
                self.child_entry.room_id,
                child.entrance_id,
                child.departure_id,
                self.agreement.pk,
            ),
        )
        self.assertEqual(child.entrance.location, self.hall.room)
        self.assertEqual(child.owner_id, self.tenant.pk)
        self.assertEqual(keepsake.location, self.child_entry.room)

    def test_group_archive_and_parent_first_restore(self):
        child = self.apartment()
        lifecycle.archive(self.char1, self.parent, reason="Retire together", include_children=True)
        self.parent.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual((self.parent.state, child.state), ("archived", "archived"))
        with self.assertRaisesMessage(ValidationError, "parent"):
            lifecycle.restore(self.char1, child, reason="Wrong order")
        lifecycle.restore(self.char1, self.parent, reason="Parent first")
        lifecycle.restore(self.char1, child, reason="Child next")
        self.assertTrue(can_enter(self.tenant, self.hall.room))

    def test_restore_collision_closed_policy_and_route_tampering(self):
        child = self.apartment()
        lifecycle.archive(self.char1, child, reason="Retire")
        collision = create_object(
            "evennia.objects.objects.DefaultExit",
            key="apartment",
            location=self.hall.room,
            destination=self.room1,
        )
        with self.assertRaisesMessage(ValidationError, "already in use"):
            lifecycle.restore(self.char1, child, reason="Collision")
        collision.delete()
        self.hall.room.tags.add("closed", category="build_policy")
        with self.assertRaisesMessage(ValidationError, "closed"):
            lifecycle.restore(self.char1, child, reason="Closed")
        self.hall.room.tags.remove("closed", category="build_policy")
        door = self.parent_project.doors.get(source=self.entry, target=self.hall).exit
        door.key = "changed route door"
        with self.assertRaisesMessage(ValidationError, "passage changed"):
            lifecycle.restore(self.char1, child, reason="Tampered route")

    def test_archive_failure_rolls_back_occupants_exit_and_state(self):
        child = self.apartment()
        self.guest.location = self.child_entry.room
        with (
            patch(
                "evennia_building.services._changed",
                side_effect=ValidationError("Injected audit failure"),
            ),
            self.assertRaises(ValidationError),
        ):
            lifecycle.archive(self.char1, child, reason="Atomic failure")
        child.refresh_from_db()
        self.assertEqual(child.state, "live")
        self.assertEqual(child.entrance.location, self.hall.room)
        self.assertEqual(self.guest.location, self.child_entry.room)

    def test_passage_replacement_needs_both_owners_and_staff(self):
        self.apartment()
        change = attachments.propose_passage(
            self.char1, self.agreement, self.agreement.route["rooms"], reason="Renew passage"
        )
        attachments.accept_passage(self.char2, change, acknowledgement=change.wording)
        with self.assertRaisesMessage(ValidationError, "Both"):
            attachments.apply_passage(self.char1, change)
        attachments.accept_passage(self.tenant, change, acknowledgement=change.wording)
        with self.assertRaises(PermissionDenied):
            attachments.apply_passage(self.tenant, change)
        attachments.apply_passage(self.char1, change)
        change.refresh_from_db()
        self.assertEqual(change.state, "applied")

    def test_restore_after_parent_transfer_needs_renewed_consent(self):
        child = self.apartment()
        lifecycle.archive(self.char1, child, reason="Retire child")
        services.transfer(
            self.char1,
            self.parent,
            self.guest,
            expected_owner=self.char2.pk,
            reason="New parent owner",
        )
        with self.assertRaisesMessage(ValidationError, "Ownership changed"):
            lifecycle.restore(self.char1, child, reason="Old owners")
        change = attachments.propose_passage(
            self.char1,
            self.agreement,
            self.agreement.route["rooms"],
            reason="Renew with current owners",
        )
        attachments.accept_passage(self.guest, change, acknowledgement=change.wording)
        attachments.accept_passage(self.tenant, change, acknowledgement=change.wording)
        attachments.apply_passage(self.char1, change)
        lifecycle.restore(self.char1, child, reason="Renewed consent")

    def test_quiet_flags_use_character_play_deduplicate_and_resolve(self):
        child = self.apartment()
        now = timezone.now()
        old = now - timedelta(days=40)
        BuildingClock.objects.create(pk=1, revealed_at=old)
        Property.objects.all().update(created_at=old)
        self.tenant.db.building_last_played = old
        self.char2.db.building_last_played = now
        self.account.last_login = now
        self.account.save(update_fields=["last_login"])
        self.assertEqual([flag.property_id for flag in lifecycle.check_quiet(now=now)], [child.pk])
        lifecycle.check_quiet(now=now)
        self.assertEqual(QuietFlag.objects.filter(resolved_at__isnull=True).count(), 1)
        self.assertEqual(Property.objects.get(pk=child.pk).state, "live")
        self.tenant.db.building_last_played = now
        lifecycle.check_quiet(now=now)
        self.assertFalse(QuietFlag.objects.filter(resolved_at__isnull=True).exists())
        self.assertTrue(BuildAudit.objects.filter(property=child, action="promoted").exists())

    def test_quiet_grace_reveal_threshold_and_permissions(self):
        now = timezone.now()
        Property.objects.all().update(created_at=now - timedelta(days=90))
        self.assertEqual(lifecycle.check_quiet(now=now), [])
        with override_settings(BUILDING_REVEALED=False):
            self.assertEqual(lifecycle.check_quiet(now=now + timedelta(days=90)), [])
        with self.assertRaises(PermissionDenied):
            lifecycle.quiet_list(self.char2)
        with override_settings(BUILDING_QUIET_DAYS=2):
            self.assertEqual(len(lifecycle.check_quiet(now=now + timedelta(days=3))), 1)

    def test_consent_web_renders_exact_candidate_without_preview_rights(self):
        from .views import consent_detail

        consent = attachments.request_consent(
            self.tenant, self.project, expected_version=self.project.version
        )
        request = RequestFactory().get("/")
        request.user = self.account
        request.session = {}
        with patch("evennia_building.views.actor_for", return_value=self.char2):
            response = consent_detail(request, consent.pk)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Independent apartment")
        self.assertContains(response, "cannot lock")
        self.assertFalse(room_visibility(self.child_entry.room, self.char2))

    def test_selected_character_consent_post_and_guest_api_privacy(self):
        from evennia_links.web import WebCharacterMiddleware

        from . import views
        from .api.views import properties

        consent = attachments.request_consent(
            self.tenant, self.project, expected_version=self.project.version
        )
        self.account2.characters.add(self.char2)
        self.account2.characters.add(self.guest)
        factory = RequestFactory()
        request = factory.post("/", {"action": "grant", "acknowledgement": "on"})
        request.user = self.account2
        request.session = {"puppet": self.guest.pk}
        with self.assertRaises(Http404):
            WebCharacterMiddleware(lambda req: views.consent_detail(req, consent.pk))(request)
        request.session = {"puppet": self.char2.pk}
        response = WebCharacterMiddleware(lambda req: views.consent_detail(req, consent.pk))(
            request
        )
        self.assertEqual(response.status_code, 302)
        child = self.approve(self.tenant, self.project)
        services.set_locked(self.char2, self.parent, True)
        invitation = services.invite(self.tenant, child, self.guest, entry=True, maps=False)
        services.answer_invitation(self.guest, invitation, accept=True)
        request = factory.get("/")
        request.user = self.account2
        request.session = {"puppet": self.guest.pk}
        response = WebCharacterMiddleware(properties)(request)
        self.assertEqual(response.data, [])
        self.assertTrue(can_enter(self.guest, self.hall.room))

    def test_command_consent_and_staff_lifecycle_adapters(self):
        from .commands import CmdBuildAdmin, CmdConsent

        services.enter(self.tenant, self.project)
        self.call(CmdConsent(), "/request", caller=self.tenant)
        consent = self.project.consents.get()
        shown = self.call(CmdConsent(), str(consent.pk), caller=self.char2)
        self.assertIn("cannot lock", shown)
        preview = self.call(CmdConsent(), f"/grant {consent.pk}", caller=self.char2)
        token = preview.split(f"+consent/grant {consent.pk}=")[-1].split()[0]
        self.call(CmdConsent(), f"/grant {consent.pk}={token}", caller=self.char2)
        child = self.approve(self.tenant, self.project)
        self.call(CmdBuildAdmin(), f"/archive {child.pk} # Temporary retirement", caller=self.char1)
        preview = self.call(CmdBuildAdmin(), "/finish", caller=self.char1)
        token = preview.split("+buildadmin/finish ")[-1].split()[0]
        self.call(CmdBuildAdmin(), f"/finish {token}", caller=self.char1)
        child.refresh_from_db()
        self.assertEqual(child.state, "archived")
        preview = self.call(
            CmdBuildAdmin(), f"/restore {child.pk} # Return home", caller=self.char1
        )
        token = preview.split(f"+buildadmin/restore {child.pk}=")[-1].split()[0]
        self.call(CmdBuildAdmin(), f"/restore {child.pk}={token} # Return home", caller=self.char1)
        child.refresh_from_db()
        self.assertEqual(child.state, "live")

    def test_staff_web_archive_restore_and_passage_actions_render(self):
        from . import views

        child = self.apartment()
        factory = RequestFactory()

        def request(method, values=None):
            req = factory.post("/", values) if method == "POST" else factory.get("/")
            req.user = self.account
            req.session = {}
            return req

        with patch("evennia_building.views.actor_for", return_value=self.char1):
            response = views.property_detail(
                request("POST", {"action": "archive", "reason": "Web retirement"}), child.pk
            )
            self.assertEqual(response.status_code, 302)
            response = views.property_detail(request("GET"), child.pk)
            self.assertContains(response, "archived")
            response = views.property_detail(
                request("POST", {"action": "restore", "reason": "Web restore"}), child.pk
            )
            self.assertEqual(response.status_code, 302)
            response = views.property_detail(
                request(
                    "POST",
                    {
                        "action": "passage",
                        "passage": f"{self.entry.room_id},{self.hall.room_id}",
                        "reason": "Web renewal",
                    },
                ),
                child.pk,
            )
            self.assertEqual(response.status_code, 302)
            change = self.agreement.changes.get()
            response = views.passage_detail(request("GET"), change.pk)
            self.assertContains(response, "Replacement passage")
        for owner in (self.char2, self.tenant):
            with patch("evennia_building.views.actor_for", return_value=owner):
                self.assertEqual(
                    views.passage_detail(
                        request("POST", {"action": "accept", "acknowledgement": "on"}), change.pk
                    ).status_code,
                    302,
                )
        with patch("evennia_building.views.actor_for", return_value=self.char1):
            self.assertEqual(
                views.passage_detail(request("POST", {"action": "apply"}), change.pk).status_code,
                302,
            )

    def test_durable_consent_and_missing_route_fail_closed(self):
        consent = self.consent()
        consent.wording = "Different concession"
        with self.assertRaisesMessage(ValidationError, "immutable"):
            consent.save()
        self.child = self.approve(self.tenant, self.project)
        self.parent.entrance.locks.add("traverse:building_entry() and false()")
        services.set_locked(self.char2, self.parent, True)
        self.assertFalse(can_enter(self.tenant, self.hall.room))

    def test_archived_child_transfer_requires_new_owners_to_restore(self):
        child = self.apartment()
        lifecycle.archive(self.char1, child, reason="Retire before transfer")
        services.transfer(
            self.char1,
            child,
            self.guest,
            expected_owner=self.tenant.pk,
            reason="New archived owner",
        )
        with self.assertRaisesMessage(ValidationError, "Ownership changed"):
            lifecycle.restore(self.char1, child, reason="Must renew")
        change = attachments.propose_passage(
            self.char1, self.agreement, self.agreement.route["rooms"], reason="Current owners renew"
        )
        attachments.accept_passage(self.char2, change, acknowledgement=change.wording)
        attachments.accept_passage(self.guest, change, acknowledgement=change.wording)
        attachments.apply_passage(self.char1, change)
        lifecycle.restore(self.char1, child, reason="Renewed owners")

    def test_group_archive_refuses_deeper_legacy_property_stranding(self):
        child = self.apartment()
        # Release 0.1 allowed a self-owned wing within another self-owned wing.
        # Reproduce that populated legacy shape without the new one-level check.
        grandchild_project = services.new_project(self.tenant, "Legacy inner wing")
        with patch("evennia_building.attachments.parent_for", return_value=None):
            services.attach(self.tenant, grandchild_project, self.child_entry.room, "legacy wing")
            grandchild = self.approve(self.tenant, grandchild_project)
        with self.assertRaisesMessage(ValidationError, "deeper legacy"):
            lifecycle.archive(
                self.char1, self.parent, reason="Keep all homes reachable", include_children=True
            )
        for property in (self.parent, child, grandchild):
            property.refresh_from_db()
            self.assertEqual(property.state, "live")
            self.assertIsNotNone(property.entrance.location)

    def test_proposal_selection_cannot_discover_a_restricted_parent_route(self):
        services.set_override(self.char2, self.bedroom.room, [])
        with self.assertRaises(PermissionDenied):
            services.attach(self.tenant, self.project, self.bedroom.room, "guessed private unit")
        services.set_locked(self.char2, self.parent, True)
        self.project.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            attachments.request_consent(
                self.tenant, self.project, expected_version=self.project.version
            )
        invitation = services.invite(self.char2, self.parent, self.tenant, entry=False, maps=True)
        services.answer_invitation(self.tenant, invitation, accept=True)
        services.attach(self.tenant, self.project, self.hall.room, "previewed apartment")
        self.project.refresh_from_db()
        self.consent()
        child = self.approve(self.tenant, self.project)
        self.assertTrue(can_enter(self.tenant, self.hall.room))
        self.assertEqual(child.owner_id, self.tenant.pk)
