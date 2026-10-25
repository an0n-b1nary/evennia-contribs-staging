"""Behavioral tests shared by full-partner and core-only fresh-process profiles."""

from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, override_settings
from django.urls import include, path
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTestMixin, EvenniaTest
from evennia.web.urls import urlpatterns as evennia_default_urlpatterns

from . import services, signals
from .access import can_enter, can_teleport, owner_of, room_permission
from .models import BuildAudit, BuildProject, BuildReview, BuildSubmission, Property, RoomOverride
from .request_form import FORM, FORM_KEY
from .visibility import room_visibility

ACK = "My submitted content may be reused."

# A contrib-only suite runs under a host URLconf that need not mount Building.
# Evennia's routes come along because website/base.html reverses them.
urlpatterns = [
    path("building/", include("evennia_building.urls")),
    *evennia_default_urlpatterns,
]


@override_settings(
    ROOT_URLCONF=__name__,
    BUILDING_REVEALED=True,
    BUILDING_REUSE_ACKNOWLEDGEMENT=ACK,
    JOBS_REQUEST_FORMS={FORM_KEY: FORM},
    LINKS_ROOM_PERMISSION="evennia_building.access.room_permission",
    LINKS_ROOM_OWNER="evennia_building.access.owner_of",
)
class TestInteriors(EvenniaCommandTestMixin, EvenniaTest):
    def setUp(self):
        super().setUp()
        self.project = services.new_project(self.char2, "Garden home")
        self.entry = self.project.rooms.get(entry=True)
        self.room1.db.room_type = "ic"
        self.room1.db.allow_teleport = "public"
        services.attach(self.char2, self.project, self.room1, "garden home")
        self.project.refresh_from_db()

    def submit(self):
        self.project.refresh_from_db()
        return services.submit(
            self.char2, self.project, expected_version=self.project.version, acknowledgement=ACK
        )

    def approve(self, submission=None):
        submission = submission or self.submit()
        services.review(
            self.char1,
            submission,
            expected_revision=submission.revision,
            outcome="approved",
            reason="Fits the setting.",
        )
        return Property.objects.get(promotion=submission)

    def extra(self):
        return services.dig(
            self.char2,
            self.project,
            self.entry,
            "Private bedroom",
            door="upstairs",
            floor=1,
            x=0,
            y=0,
        )

    def test_isolation_and_no_general_builder_rights(self):
        room = self.entry.room
        self.assertEqual(room.db.room_type, "ooc")
        self.assertEqual(room.db.allow_teleport, "secret")
        self.assertFalse(room.access(self.char2, "control"))
        self.assertFalse(room_permission(self.char2, room, "describe"))
        self.assertFalse(room_permission(self.char2, room, "configure"))
        self.assertFalse(room_visibility(room))
        self.assertFalse(can_enter(self.char1.location, room))
        self.assertTrue(room_visibility(room, self.char2))
        self.assertFalse(ObjectDB.objects.filter(db_destination=room).exists())
        with self.assertRaises(PermissionDenied):
            services.edit_project(self.char1, self.project, name="Staff as collaborator")

    def test_unsupported_kind_and_apartment_requires_consent(self):
        with self.assertRaisesMessage(ValidationError, "interior or frontier"):
            services.new_project(self.char2, "Unknown", kind="unsupported")
        property = self.approve()
        project = services.new_project(self.char1, "Apartment")
        services.attach(self.char1, project, self.entry.room, "apartment")
        project.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "consent"):
            services.submit(
                self.char1, project, expected_version=project.version, acknowledgement=ACK
            )
        self.assertEqual(property.owner_id, self.char2.pk)

    def test_quotas_include_submitted_and_multiple_projects(self):
        self.submit()
        services.new_project(self.char2, "Second")
        with self.assertRaisesMessage(ValidationError, "open-project"):
            services.new_project(self.char2, "Third")
        with override_settings(BUILDING_ROOM_LIMIT=2):
            second = BuildProject.objects.get(name="Second")
            with self.assertRaisesMessage(ValidationError, "draft-room"):
                services.dig(self.char2, second, second.rooms.get(entry=True), "Extra", x=1)

    def test_frozen_edits_withdraw_revision_and_stale_review(self):
        first = self.submit()
        with self.assertRaises(ValidationError):
            services.edit_project(self.char2, self.project, name="Changed")
        self.assertFalse(room_permission(self.char2, self.entry.room, "describe"))
        services.withdraw(self.char2, first, expected_revision=first.revision, reason="Revision")
        services.edit_project(
            self.char2, self.project, room=self.entry, description="Revised description"
        )
        second = self.submit()
        self.assertEqual(second.revision, 2)
        self.assertEqual(first.snapshot["rooms"][0]["description"], "")
        self.assertEqual(BuildReview.objects.get(submission=first).outcome, "withdrawn")
        with self.assertRaises(ValidationError):
            services.review(
                self.char1, first, expected_revision=1, outcome="approved", reason="Old"
            )
        self.approve(second)
        self.assertEqual(Property.objects.count(), 1)

    def test_changes_requested_and_decline_preserve_distinct_cycles(self):
        first = self.submit()
        services.review(
            self.char1,
            first,
            expected_revision=1,
            outcome="changes_requested",
            reason="More detail",
        )
        second = self.submit()
        services.review(
            self.char1,
            second,
            expected_revision=2,
            outcome="declined",
            reason="Choose another approach",
        )
        third = self.submit()
        self.assertEqual(
            list(self.project.submissions.values_list("revision", flat=True)), [1, 2, 3]
        )
        if apps.is_installed("evennia_jobs"):
            from evennia_jobs.models import RequestSubmission

            one, two, three = [
                RequestSubmission.objects.get(pk=row.jobs_submission_id)
                for row in (first, second, third)
            ]
            self.assertEqual(one.job_id, two.job_id)
            self.assertNotEqual(two.job_id, three.job_id)
        self.assertEqual(BuildReview.objects.get(submission=second).outcome, "declined")

    def test_direct_staff_edit_or_closed_policy_blocks_atomic_review(self):
        first = self.submit()
        self.entry.room.db.desc = "Direct edit"
        with self.assertRaisesMessage(ValidationError, "changed"):
            self.approve(first)
        self.assertFalse(Property.objects.exists())
        self.assertFalse(BuildReview.objects.exists())
        if apps.is_installed("evennia_jobs"):
            from evennia_jobs.models import RequestDecision

            self.assertFalse(RequestDecision.objects.exists())
        self.entry.room.db.desc = ""
        self.entry.room.db.room_mood = "Unreviewed atmosphere"
        with self.assertRaisesMessage(ValidationError, "changed"):
            self.approve(first)
        self.entry.room.attributes.remove("room_mood")
        self.room1.tags.add("closed", category="build_policy")
        with self.assertRaisesMessage(ValidationError, "closed"):
            self.approve(first)

    def test_promotion_preserves_ids_private_stack_and_is_idempotent(self):
        upper = self.extra()
        ids = list(self.project.rooms.values_list("room_id", flat=True))
        submission = self.submit()
        property = self.approve(submission)
        self.assertEqual(sorted(property.rooms.values_list("room_id", flat=True)), sorted(ids))
        self.assertFalse(property.locked)
        self.assertEqual(owner_of(upper.room), self.char2)
        self.assertEqual(upper.room.db.room_type, "ic")
        self.assertEqual(upper.room.db.allow_teleport, "private")
        self.assertTrue(property.departure.access(self.char2, "traverse"))
        self.assertEqual(services.promote(submission, self.char1).pk, property.pk)
        if apps.is_installed("evennia_maps"):
            from evennia_maps.models import RoomTile

            self.assertEqual(
                RoomTile.objects.get(room=upper.room).plane.visibility_room_id, self.entry.room_id
            )

    def test_required_listener_failure_rolls_back_geometry_and_review(self):
        submission = self.submit()
        before = ObjectDB.objects.count()

        def fail(**kwargs):
            raise ValidationError("Partner write failed")

        signals.property_promoted.connect(fail, weak=False)
        try:
            with (
                self.captureOnCommitCallbacks(execute=True) as callbacks,
                self.assertRaisesMessage(ValidationError, "Partner write failed"),
            ):
                self.approve(submission)
            self.assertEqual(callbacks, [])
            self.assertEqual(ObjectDB.objects.count(), before)
            self.assertFalse(Property.objects.exists())
            self.project.refresh_from_db()
            self.assertEqual(self.project.state, "submitted")
        finally:
            signals.property_promoted.disconnect(fail)
        self.approve(submission)

    def test_later_jobs_receiver_failure_restores_promotion_and_cached_objects(self):
        if not apps.is_installed("evennia_jobs"):
            self.skipTest("Jobs is intentionally absent")
        from evennia_jobs.models import RequestDecision
        from evennia_jobs.signals import request_reviewed

        submission = self.submit()

        def fail_after_building(**kwargs):
            self.assertTrue(Property.objects.filter(promotion=submission).exists())
            raise ValidationError("Later Jobs receiver failed")

        request_reviewed.connect(fail_after_building, weak=False)
        try:
            with self.assertRaisesMessage(ValidationError, "Later Jobs receiver failed"):
                self.approve(submission)
            self.assertFalse(Property.objects.exists())
            self.assertFalse(RequestDecision.objects.exists())
            self.assertEqual(self.entry.room.db.room_type, "ooc")
            self.assertEqual(self.entry.room.db.allow_teleport, "secret")
            self.assertFalse(
                ObjectDB.objects.filter(
                    db_location=self.room1, db_destination=self.entry.room
                ).exists()
            )
        finally:
            request_reviewed.disconnect(fail_after_building)
        self.approve(submission)

    def test_resident_guest_scopes_overrides_and_departure(self):
        upper = self.extra()
        property = self.approve()
        guest = create_object("evennia.objects.objects.DefaultCharacter", key="Guest")
        self.assertTrue(can_enter(guest, self.entry.room))
        self.assertFalse(room_visibility(self.entry.room, guest))
        services.set_locked(self.char2, property, True)
        self.assertFalse(can_enter(guest, self.entry.room))
        services.set_resident(self.char2, property, guest)
        self.assertTrue(can_enter(guest, upper.room))
        self.assertTrue(room_visibility(upper.room, guest))
        for action in ("describe", "configure", "transfer", "install", "lock", "admit"):
            self.assertFalse(room_permission(guest, upper.room, action))
        services.set_resident(self.char2, property, guest, can_install=True)
        self.assertTrue(room_permission(guest, upper.room, "install"))
        services.set_override(self.char2, upper.room, [])
        self.assertFalse(can_enter(guest, upper.room))
        self.assertFalse(room_visibility(upper.room, guest))
        self.assertFalse(room_permission(guest, upper.room, "install"))
        self.assertTrue(room_visibility(upper.room, self.char2))
        guest.location = upper.room
        services.set_resident(self.char2, property, guest, remove=True)
        self.assertEqual(guest.location, upper.room)
        outward = self.project.doors.get(source=upper, outward=True).exit
        self.assertTrue(outward.access(guest, "traverse"))
        self.assertTrue(property.departure.access(guest, "traverse"))
        invitation = services.invite(self.char2, property, guest, entry=True, maps=False)
        self.assertFalse(can_enter(guest, self.entry.room))
        services.answer_invitation(guest, invitation, accept=True)
        self.assertTrue(can_enter(guest, self.entry.room))
        self.assertFalse(room_visibility(self.entry.room, guest))
        self.assertFalse(can_enter(guest, upper.room))
        services.invite(self.char2, property, guest, revoke=True)
        self.assertFalse(can_enter(guest, self.entry.room))

    def test_transfer_preserves_objects_and_items_clears_rights(self):
        upper = self.extra()
        property = self.approve()
        item = create_object(
            "evennia.objects.objects.DefaultObject", key="Keepsake", location=upper.room
        )
        new_owner = create_object("evennia.objects.objects.DefaultCharacter", key="New owner")
        services.set_resident(self.char2, property, new_owner, can_install=True)
        before = list(property.rooms.values_list("room_id", flat=True))
        with self.assertRaises(ValidationError):
            services.transfer(self.char1, property, new_owner, expected_owner=0, reason="Wrong")
        services.transfer(
            self.char1, property, new_owner, expected_owner=self.char2.pk, reason="Staff assignment"
        )
        self.assertEqual(owner_of(upper.room), new_owner)
        self.assertEqual(list(property.rooms.values_list("room_id", flat=True)), before)
        self.assertEqual(item.location, upper.room)
        self.assertFalse(property.residents.exists())
        self.assertFalse(room_permission(self.char2, upper.room, "describe"))

    def test_transfer_command_keeps_semicolons_in_reason(self):
        from .commands import CmdBuildAdmin

        property = self.approve()
        new_owner = create_object("evennia.objects.objects.DefaultCharacter", key="New owner")
        self.call(
            CmdBuildAdmin(),
            f"/transfer {property.pk}=#{new_owner.pk} # Owner left; keys handed over",
            caller=self.char1,
        )
        preview = self.call(CmdBuildAdmin(), "/finish", caller=self.char1)
        token = preview.split("+buildadmin/finish ")[-1].split()[0]
        self.call(CmdBuildAdmin(), f"/finish {token}", caller=self.char1)
        property.refresh_from_db()
        self.assertEqual(property.owner_id, new_owner.pk)
        record = BuildAudit.objects.get(property=property, action="transferred")
        self.assertEqual(record.data["reason"], "Owner left; keys handed over")

    def test_stale_discard_then_safe_cleanup_preserves_belongings_and_history(self):
        upper = self.extra()
        token = services.discard_token(self.char2, self.project)
        services.edit_project(self.char2, self.project, room=upper, description="A changed bedroom")
        with self.assertRaisesMessage(ValidationError, "changed"):
            services.discard(self.char2, self.project, token)
        self.char2.db.building_return = self.room1.pk
        self.char2.location = upper.room
        item = create_object(
            "evennia.objects.objects.DefaultObject", key="Keepsake", location=upper.room
        )
        carried = create_object(
            "evennia.objects.objects.DefaultObject", key="Bag", location=self.char2
        )
        ids = list(self.project.rooms.values_list("object_id", flat=True))
        services.discard(self.char2, self.project, services.discard_token(self.char2, self.project))
        self.assertEqual(self.char2.location, self.room1)
        self.assertEqual(item.location, self.room1)
        self.assertEqual(carried.location, self.char2)
        self.assertFalse(ObjectDB.objects.filter(pk__in=ids).exists())
        self.assertTrue(
            BuildAudit.objects.filter(project=self.project, action="discarded").exists()
        )
        services.discard(self.char2, self.project, token)

    def test_discard_fails_without_safe_return(self):
        self.char2.location = self.entry.room
        with override_settings(BUILDING_SAFE_ROOM="#999999"):
            token = services.discard_token(self.char2, self.project)
            with self.assertRaisesMessage(ValidationError, "safe return"):
                services.discard(self.char2, self.project, token)
        self.assertTrue(ObjectDB.objects.filter(pk=self.entry.room_id).exists())

    def test_dark_deploy_and_unmanaged_neutrality(self):
        permission = self.room1.access(self.char2, "control")
        with override_settings(BUILDING_REVEALED=False):
            self.assertIsNone(room_visibility(self.room1, self.char2))
            self.assertIsNone(can_teleport(self.char2, self.room1))
            self.assertEqual(room_permission(self.char2, self.room1, "configure"), permission)
            self.assertIsNone(owner_of(self.room1))
            self.assertFalse(room_visibility(self.entry.room, self.char2))
            with self.assertRaises(PermissionDenied):
                services.new_project(self.char2, "Dark")

    def test_real_privacy_boundaries_and_rendered_pages(self):
        upper = self.extra()
        property = self.approve()
        guest = create_object("evennia.objects.objects.DefaultCharacter", key="Resident")
        services.set_resident(self.char2, property, guest)
        services.set_override(self.char2, upper.room, [])
        if apps.is_installed("evennia_maps"):
            from evennia_maps.models import RoomTile
            from evennia_maps.permissions import is_plane_visible

            with override_settings(
                MAPS_ROOM_VISIBILITY="evennia_building.visibility.room_visibility"
            ):
                self.assertTrue(
                    is_plane_visible(RoomTile.objects.get(room=self.entry.room).plane, viewer=guest)
                )
                self.assertFalse(
                    is_plane_visible(RoomTile.objects.get(room=upper.room).plane, viewer=guest)
                )
        from . import views
        from .api.views import properties

        request = RequestFactory().get("/building/")
        request.user = self.account2
        request.session = {}
        with patch("evennia_building.views.web_character", return_value=guest):
            response = views.property_detail(request, property.pk)
            self.assertNotIn(b"Private bedroom", response.content)
            api = properties(request, pk=property.pk)
            self.assertNotIn("Private bedroom", str(api.data))
        with patch("evennia_building.views.web_character", return_value=self.char2):
            for view, pk in (
                (views.project_detail, self.project.pk),
                (views.submission_detail, property.promotion_id),
                (views.property_detail, property.pk),
            ):
                self.assertEqual(view(request, pk).status_code, 200)

    def test_forged_jobs_pointer_cannot_approve(self):
        if not apps.is_installed("evennia_jobs"):
            self.skipTest("Jobs is intentionally absent")
        from evennia_jobs.models import RequestSubmission
        from evennia_jobs.review import review_request

        submission = self.submit()
        linked = RequestSubmission.objects.get(pk=submission.jobs_submission_id)
        linked.answers["snapshot"] = "forged"
        linked.save(update_fields=["answers"])
        with self.assertRaisesMessage(ValidationError, "authentic"):
            review_request(
                job=linked.job,
                reviewer=self.char1,
                outcome="approved",
                reason="Forged",
                expected_revision=linked.revision,
            )
        self.assertFalse(Property.objects.exists())

    def test_native_queue_if_jobs_removed_and_no_duplicate_after_return(self):
        submission = self.submit()
        original = apps.is_installed
        with patch.object(
            apps,
            "is_installed",
            side_effect=lambda label: False if label == "evennia_jobs" else original(label),
        ):
            self.approve(submission)
        self.assertEqual(Property.objects.count(), 1)
        self.approve(submission)
        self.assertEqual(Property.objects.count(), 1)

    def test_requested_environment_needs_explicit_staff_approval(self):
        services.request_environment(self.char2, self.project, {"terrain": ["forest"]})
        submission = self.submit()
        with self.assertRaisesMessage(ValidationError, "explicitly approve"):
            self.approve(submission)
        with self.assertRaises(PermissionDenied):
            services.approve_environment(
                self.char2, submission, expected_revision=1, reason="Owner"
            )
        services.approve_environment(
            self.char1, submission, expected_revision=1, reason="Fits the setting"
        )
        property = self.approve(submission)
        self.assertEqual(set(self.entry.room.db.terrain_tags), {"forest"})
        self.assertEqual(property.provenance["terrain"], ["forest"])
        self.room1.db.terrain_tags = {"water"}
        self.assertEqual(set(self.entry.room.db.terrain_tags), {"forest"})
        self.assertEqual(self.entry.room.db.allow_teleport, "private")

    def test_staff_only_terrain_cannot_be_opened_by_inheritance_or_request(self):
        self.room1.db.terrain_tags = {"restricted"}
        with override_settings(BUILDING_STAFF_ONLY_TERRAINS=("restricted",)):
            services.request_environment(self.char2, self.project, {"terrain": []})
            with self.assertRaisesMessage(ValidationError, "staff-only"):
                self.submit()

    def test_policy_service_authorization_and_precedence(self):
        from .policy import resolve_policy, set_policy

        with self.assertRaises(PermissionDenied):
            set_policy(self.char2, self.room1, "closed")
        set_policy(self.char1, self.room1, "commercial")
        self.assertEqual(resolve_policy(self.room1), "commercial")
        set_policy(self.char1, self.room1, "reset")
        self.assertEqual(resolve_policy(self.room1), "open")
        if apps.is_installed("evennia_regions"):
            from evennia_regions.models import Region, RegionMembership

            region = Region.objects.create(name="Policy region")
            RegionMembership.objects.create(
                region=region, room=self.room1, room_name=self.room1.key, is_primary=True
            )
            set_policy(self.char1, region.pk, "residential", region=True)
            self.assertEqual(resolve_policy(self.room1), "residential")
            set_policy(self.char1, self.room1, "closed")
            self.assertEqual(resolve_policy(self.room1), "closed")

    def test_membership_and_transfer_reject_noncharacters(self):
        property = self.approve()
        for operation in (
            lambda: services.set_resident(self.char2, property, self.room1),
            lambda: services.invite(self.char2, property, self.room1),
            lambda: services.set_override(self.char2, self.entry.room, [self.room1.pk]),
            lambda: services.set_override(self.char2, self.entry.room, [9999999]),
            lambda: services.transfer(
                self.char1, property, self.room1, expected_owner=self.char2.pk, reason="Invalid"
            ),
        ):
            with self.assertRaises(ValidationError):
                operation()

    def test_persisted_exit_edit_invalidates_submission_despite_cached_exit(self):
        self.extra()
        submission = self.submit()
        door = self.project.doors.first().exit
        original = door.key
        ObjectDB.objects.filter(pk=door.pk).update(db_key="Changed outside the cache")
        self.assertEqual(door.key, original)
        with self.assertRaisesMessage(ValidationError, "changed"):
            self.approve(submission)
        self.assertFalse(Property.objects.exists())

    def test_invitation_web_stale_and_invalid_answers_are_readable(self):
        from .views import invitation_answer

        property = self.approve()
        guest = create_object("evennia.objects.objects.DefaultCharacter", key="Web guest")
        invitation = services.invite(self.char2, property, guest)
        services.invite(self.char2, property, guest, revoke=True)
        for answer in ("accept", "invalid"):
            request = RequestFactory().post("/building/invitations/", {"answer": answer})
            request.user = self.account2
            request.session = {}
            with patch("evennia_building.views.web_character", return_value=guest):
                response = invitation_answer(request, invitation.pk)
            self.assertEqual(response.status_code, 400)
            self.assertIn(b"Invitation could not be answered", response.content)

    def test_web_action_forms_submit_edit_and_property_invitation(self):
        from . import views

        request = RequestFactory().post(
            "/building/",
            {
                "action": "description",
                "version": self.project.version,
                "room": self.entry.pk,
                "value": "Web-authored room",
            },
        )
        # attach advanced the persisted version, not this retained model instance.
        self.project.refresh_from_db()
        request.POST = request.POST.copy()
        request.POST["version"] = self.project.version
        request.user = self.account2
        request.session = {}
        with patch("evennia_building.views.web_character", return_value=self.char2):
            response = views.project_detail(request, self.project.pk)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.entry.room.db.desc, "Web-authored room")
        property = self.approve()
        guest = create_object("evennia.objects.objects.DefaultCharacter", key="Invited through web")
        request.POST = request.POST.copy()
        request.POST.update({"action": "invite", "target": guest.pk, "entry": "on"})
        with patch("evennia_building.views.web_character", return_value=self.char2):
            response = views.property_detail(request, property.pk)
        self.assertEqual(response.status_code, 302)
        invitation = property.invitations.get(character=guest)
        self.assertTrue(invitation.entry)
        self.assertFalse(invitation.maps)

    def test_commands_edit_live_rooms_through_audited_service(self):
        from .commands import CmdProperty

        property = self.approve()
        self.char2.location = self.entry.room
        self.call(
            CmdProperty(),
            "/desc New live description",
            caller=self.char2,
        )
        self.assertEqual(self.entry.room.db.desc, "New live description")
        self.assertTrue(BuildAudit.objects.filter(property=property, action="room_edited").exists())
        self.assertFalse(self.char2.check_permstring("Builder"))
        invitation = services.invite(self.char2, property, self.char1)
        pending = self.call(CmdProperty(), "/invitations", caller=self.char1)
        self.assertIn(f"Invitation {invitation.pk}", pending)
        summary = self.call(CmdProperty(), str(property.pk), caller=self.char2)
        self.assertIn("room_edited", summary)

    def test_failed_room_edit_restores_cached_name_and_version(self):
        self.project.refresh_from_db()
        version = self.project.version
        original = self.entry.room.key
        with self.assertRaises(ValidationError):
            services.edit_project(
                self.char2,
                self.project,
                room=self.entry,
                name="Temporary name",
                description="",
                expected_version=version,
            )
        self.project.refresh_from_db()
        self.assertEqual(self.project.version, version)
        self.assertEqual(self.entry.room.key, original)
        with self.assertRaisesMessage(ValidationError, "reserves"):
            services.dig(self.char2, self.project, self.entry, "Unusable room", door="outside", x=1)
        self.assertEqual(self.project.rooms.count(), 1)

    def test_partial_discard_failure_restores_rooms_and_loose_contents(self):
        upper = self.extra()
        loose = create_object(
            "evennia.objects.objects.DefaultObject",
            key="Retained keepsake",
            location=self.entry.room,
        )
        room_id = self.entry.room_id
        with (
            override_settings(BUILDING_SAFE_ROOM=self.room1.pk),
            patch.object(upper.room, "delete", return_value=False),
            self.assertRaisesMessage(ValidationError, "cleanup rolled back"),
        ):
            services.discard(
                self.char2, self.project, services.discard_token(self.char2, self.project)
            )
        self.assertEqual(self.entry.room.pk, room_id)
        self.assertEqual(loose.location, self.entry.room)
        self.assertIn(loose, self.entry.room.contents)
        self.assertTrue(ObjectDB.objects.filter(pk=room_id).exists())
        self.project.refresh_from_db()
        self.assertEqual(self.project.state, "draft")
