"""Public growth, shared authorship and retirement under real optional partners."""

from datetime import timedelta
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.test import Client, RequestFactory, override_settings
from django.utils import timezone
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTestMixin, EvenniaTest

from . import attachments, collaboration, frontier, frontier_lifecycle, lifecycle, services
from .access import can_enter, owner_of, room_permission
from .models import (
    BuildingClock,
    BuildProject,
    BuildReview,
    DraftRoom,
    Frontier,
    Property,
    StewardQuietFlag,
)
from .request_form import FORM, FORM_KEY
from .visibility import room_visibility

ACK = "My submitted content may be reused."


@override_settings(
    ROOT_URLCONF="evennia_building.tests",
    BUILDING_REVEALED=True,
    BUILDING_REUSE_ACKNOWLEDGEMENT=ACK,
    JOBS_REQUEST_FORMS={FORM_KEY: FORM},
    LINKS_ROOM_PERMISSION="evennia_building.access.room_permission",
    LINKS_ROOM_OWNER="evennia_building.access.owner_of",
)
class TestFrontier(EvenniaCommandTestMixin, EvenniaTest):
    character_typeclass = "evennia.objects.objects.DefaultCharacter"
    room_typeclass = "evennia.objects.objects.DefaultRoom"

    def setUp(self):
        super().setUp()
        self.collaborator = create_object(
            self.character_typeclass, key="Draft Author", location=self.room1
        )
        self.recipient = create_object(
            self.character_typeclass, key="Home Recipient", location=self.room1
        )
        self.outsider = create_object(
            self.character_typeclass, key="Other Character", location=self.room1
        )
        self.actors = {
            row.pk: row
            for row in (self.char1, self.char2, self.collaborator, self.recipient, self.outsider)
        }
        for room in (self.room1, self.room2):
            room.db.room_type = "ic"
            room.db.allow_teleport = "public"
        for exit in ObjectDB.objects.filter(
            db_location__in=[self.room1, self.room2], db_destination__isnull=False
        ):
            exit.delete()
        if apps.is_installed("evennia_maps"):
            from evennia_maps.models import MapPlane, RoomTile
            from evennia_maps.placement import place_tile

            RoomTile.objects.filter(room__in=[self.room1, self.room2]).delete()
            self.plane = MapPlane.objects.create(name="Shared world", zstack="frontier-test")
            place_tile(self.room1, self.plane, 0, 0, actor=self.char1)
            place_tile(self.room2, self.plane, 3, 0, actor=self.char1)
        self.project = services.new_project(self.char2, "New trail", kind="frontier")
        self.entry = self.project.rooms.get(entry=True)
        services.attach(self.char2, self.project, self.room1, "east")
        self.project.refresh_from_db()

    def acknowledge_all(self, project=None):
        project = project or self.project
        project.refresh_from_db()
        digest = services.fingerprint(services.snapshot(project))
        for actor_id, role in sorted(collaboration.required(project)):
            collaboration.acknowledge(
                self.actors[actor_id],
                project,
                role=role,
                expected_version=project.version,
                expected_fingerprint=digest,
                acknowledgement=collaboration.wording(role),
            )

    def submit(self, project=None):
        project = project or self.project
        project.refresh_from_db()
        return services.submit(
            project.owner, project, expected_version=project.version, acknowledgement=ACK
        )

    def approve(self, project=None, submission=None):
        project = project or self.project
        submission = submission or self.submit(project)
        if project.kind == "frontier" and not apps.is_installed("evennia_maps"):
            frontier.approve_geometry(
                self.char1,
                submission,
                expected_revision=submission.revision,
                reason="Manually checked all compass connections.",
            )
        services.review(
            self.char1,
            submission,
            expected_revision=submission.revision,
            outcome="approved",
            reason="Reviewed the whole proposal.",
        )
        return (
            Frontier.objects.get(promotion=submission)
            if project.kind == "frontier"
            else Property.objects.get(promotion=submission)
        )

    def collaborate(self):
        invitation = collaboration.invite(self.char2, self.project, self.collaborator)
        collaboration.answer(self.collaborator, invitation, accept=True)
        self.project.refresh_from_db()
        return invitation

    def street(self):
        return services.dig(
            self.char2, self.project, self.entry, "Trail end", door="east", back="west", x=1
        )

    def interior(self):
        return frontier.add_interior(
            self.char2,
            self.project,
            self.entry,
            "Small home",
            owner=self.recipient,
            entrance_name="small home",
        )

    def test_public_frontier_has_stewards_and_no_property_rights(self):
        result = self.approve()
        self.assertEqual(result.rooms.count(), 1)
        self.assertFalse(Property.objects.filter(promotion=result.promotion).exists())
        self.assertIsNone(owner_of(self.entry.room))
        self.assertTrue(can_enter(self.outsider, self.entry.room))
        self.assertTrue(room_visibility(self.entry.room))
        self.assertTrue(room_permission(self.char2, self.entry.room, "describe"))
        for action in ("configure", "lock", "admit", "install", "transfer"):
            self.assertFalse(room_permission(self.char2, self.entry.room, action))
        self.assertEqual(self.entry.room.db.allow_teleport, "public")
        if apps.is_installed("evennia_maps"):
            from evennia_maps.models import RoomTile

            tile = RoomTile.objects.get(room=self.entry.room)
            self.assertEqual((tile.plane_id, tile.x, tile.y), (self.plane.pk, 1, 0))
        self.assertEqual(services.promote(result.promotion, self.char1), result)

    def test_steward_mood_matches_social_normalisation_and_stays_steward_only(self):
        self.approve()
        room = self.entry.room
        frontier.edit_room(self.char2, room, mood="  Quiet \n  footsteps.  ")
        self.assertEqual(room.attributes.get("room_mood"), "Quiet footsteps.")
        self.assertEqual(room.attributes.get("room_mood_setter"), self.char2.key)
        for text in ("   ", "x" * 201):
            with self.assertRaises(ValidationError):
                frontier.edit_room(self.char2, room, mood=text)
        with self.assertRaises(PermissionDenied):
            frontier.edit_room(self.outsider, room, mood="Uninvited weather.")
        self.assertEqual(room.attributes.get("room_mood"), "Quiet footsteps.")

    def test_invitation_acceptance_and_individual_authoring_scope(self):
        invitation = collaboration.invite(self.char2, self.project, self.collaborator)
        self.assertFalse(can_enter(self.collaborator, self.entry.room))
        with self.assertRaises(PermissionDenied):
            collaboration.answer(self.outsider, invitation)
        collaboration.answer(self.collaborator, invitation)
        self.assertTrue(can_enter(self.collaborator, self.entry.room))
        services.edit_project(
            self.collaborator, self.project, room=self.entry, description="A jointly written trail."
        )
        self.assertTrue(self.project.contributors.get(character=self.collaborator).contributed)
        with self.assertRaises(PermissionDenied):
            services.edit_project(self.collaborator, self.project, name="Take over")
        with self.assertRaises(PermissionDenied):
            services.attach(self.collaborator, self.project, self.room2, "west")
        with self.assertRaises(PermissionDenied):
            collaboration.invite(self.collaborator, self.project, self.outsider)
        with self.assertRaises(PermissionDenied):
            services.discard_token(self.collaborator, self.project)
        with self.assertRaises(PermissionDenied):
            self.submit_as_collaborator()

    def submit_as_collaborator(self):
        self.project.refresh_from_db()
        return services.submit(
            self.collaborator,
            self.project,
            expected_version=self.project.version,
            acknowledgement=ACK,
        )

    def test_collaborator_dig_uses_lead_quota(self):
        self.collaborate()
        with override_settings(BUILDING_ROOM_LIMIT=2):
            services.dig(
                self.collaborator,
                self.project,
                self.entry,
                "Shared trail",
                door="east",
                back="west",
                x=1,
            )
            with self.assertRaisesMessage(ValidationError, "draft-room"):
                services.dig(
                    self.collaborator,
                    self.project,
                    self.entry,
                    "Another",
                    door="north",
                    back="south",
                    y=1,
                )
        self.assertEqual(DraftRoom.objects.filter(project__owner=self.char2).count(), 2)
        self.assertFalse(BuildProject.objects.filter(owner=self.collaborator).exists())

    def test_removed_contributor_cannot_be_used_to_bypass_acknowledgement(self):
        self.collaborate()
        services.edit_project(
            self.collaborator, self.project, room=self.entry, description="Retained contribution."
        )
        collaboration.invite(self.char2, self.project, self.collaborator, remove=True)
        self.assertFalse(can_enter(self.collaborator, self.entry.room))
        with self.assertRaises(PermissionDenied):
            services.edit_project(
                self.collaborator, self.project, room=self.entry, description="No longer an author"
            )
        with self.assertRaisesMessage(ValidationError, "acknowledge"):
            self.submit()
        self.acknowledge_all()
        result = self.approve()
        self.assertEqual(result.rooms.get().steward_id, self.char2.pk)

    def test_candidate_changes_invalidate_contributor_and_recipient_receipts(self):
        self.collaborate()
        self.interior()
        self.acknowledge_all()
        self.assertEqual(self.project.agreements.filter(state="accepted").count(), 2)
        services.edit_project(
            self.char2, self.project, room=self.entry, description="A changed trail."
        )
        self.assertFalse(self.project.agreements.filter(state="accepted").exists())
        with self.assertRaisesMessage(ValidationError, "acknowledge"):
            self.submit()
        self.acknowledge_all()
        self.approve()

    def test_exact_fingerprint_and_wording_required_for_agreement(self):
        self.collaborate()
        self.project.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "exact candidate"):
            collaboration.acknowledge(
                self.collaborator,
                self.project,
                role="contributor",
                expected_version=self.project.version,
                expected_fingerprint="old",
                acknowledgement=ACK,
            )
        with self.assertRaises(PermissionDenied):
            collaboration.acknowledge(
                self.outsider,
                self.project,
                role="contributor",
                expected_version=self.project.version,
                expected_fingerprint=services.fingerprint(services.snapshot(self.project)),
                acknowledgement=ACK,
            )

    def test_revoked_submitted_agreement_rolls_back_jobs_review(self):
        self.collaborate()
        self.acknowledge_all()
        receipt = self.project.agreements.get(state="accepted")
        submission = self.submit()
        collaboration.revoke(self.collaborator, receipt)
        with self.assertRaisesMessage(ValidationError, "acknowledge"):
            self.approve(submission=submission)
        self.assertFalse(BuildReview.objects.filter(submission=submission).exists())
        self.assertFalse(Frontier.objects.exists())
        self.project.refresh_from_db()
        self.assertEqual(self.project.state, "submitted")

    def test_mixed_settlement_has_independent_private_ownership(self):
        self.collaborate()
        part = self.interior()
        entry = part.rooms.get(room=part.entry)
        services.dig(
            self.collaborator,
            self.project,
            entry,
            "Private bedroom",
            door="bedroom",
            back="hall",
            x=1,
        )
        self.assertTrue(collaboration.can_inspect(self.recipient, self.project))
        with self.assertRaises(PermissionDenied):
            services.enter(self.recipient, self.project)
        self.acknowledge_all()
        result = self.approve()
        home = Property.objects.get(part=part)
        self.assertEqual(home.owner_id, self.recipient.pk)
        self.assertEqual(home.rooms.count(), 2)
        self.assertEqual(result.rooms.count(), 1)
        self.assertFalse(room_permission(self.char2, part.entry, "describe"))
        self.assertTrue(room_permission(self.recipient, part.entry, "describe"))
        self.assertFalse(room_visibility(part.entry, self.outsider))
        self.assertTrue(can_enter(self.outsider, self.entry.room))
        services.set_locked(self.recipient, home, True)
        self.assertFalse(can_enter(self.char2, part.entry))

    def test_multiple_homes_in_one_revision_have_distinct_properties(self):
        first = self.interior()
        second = frontier.add_interior(
            self.char2,
            self.project,
            self.entry,
            "Other home",
            owner=self.collaborator,
            entrance_name="other home",
        )
        self.acknowledge_all()
        result = self.approve()
        self.assertEqual(result.promotion.properties.count(), 2)
        self.assertNotEqual(
            Property.objects.get(part=first).owner_id, Property.objects.get(part=second).owner_id
        )

    def test_mixed_promotion_failure_rolls_back_all_parts_and_map_moves(self):
        self.interior()
        self.acknowledge_all()
        submission = self.submit()
        with (
            patch(
                "evennia_building.signals.property_promoted.send",
                side_effect=RuntimeError("partner failed"),
            ),
            self.assertRaisesMessage(RuntimeError, "partner failed"),
        ):
            self.approve(submission=submission)
        self.assertFalse(Frontier.objects.exists())
        self.assertFalse(Property.objects.exists())
        self.assertFalse(BuildReview.objects.filter(submission=submission).exists())
        self.project.refresh_from_db()
        self.assertEqual(self.project.state, "submitted")
        self.assertEqual(self.entry.room.db.room_type, "ooc")
        if apps.is_installed("evennia_maps"):
            from evennia_maps.models import RoomTile

            self.assertNotEqual(RoomTile.objects.get(room=self.entry.room).plane_id, self.plane.pk)

    def test_additional_connection_is_explicit_and_frozen(self):
        street = self.street()
        report = services.check_project(self.project)
        self.assertEqual(len(report["connections"]), 1)
        frontier.propose_connection(self.char2, self.project, street, self.room2, "east")
        self.project.refresh_from_db()
        submission = self.submit()
        self.assertEqual(len(submission.snapshot["report"]["connections"]), 2)
        with self.assertRaisesMessage(ValidationError, "Withdraw"):
            frontier.propose_connection(
                self.char2, self.project, street, self.room2, "east", remove=True
            )
        result = self.approve(submission=submission)
        self.assertEqual(result.connections.count(), 4)
        self.assertTrue(
            ObjectDB.objects.filter(
                db_location=street.room, db_destination=self.room2, db_key="east"
            ).exists()
        )

    def test_unconnected_adjacency_never_creates_exits(self):
        street = self.street()
        result = self.approve()
        self.assertFalse(
            ObjectDB.objects.filter(db_location=street.room, db_destination=self.room2).exists()
        )
        self.assertEqual(result.connections.count(), 2)

    def test_lead_can_remove_closed_or_missing_connection_targets(self):
        from .commands import CmdBuild
        from .frontier_views import collaboration_detail

        street = self.street()
        frontier.propose_connection(self.char2, self.project, street, self.room2, "east")
        self.room2.tags.add("closed", category="build_policy")
        frontier.propose_connection(
            self.char2, self.project, street, self.room2, "east", remove=True
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.connections, [])
        self.room2.tags.remove("closed", category="build_policy")
        frontier.propose_connection(self.char2, self.project, street, self.room2, "east")
        target_id = self.room2.pk
        self.room2.delete()
        self.project.refresh_from_db()
        response = self.web(
            collaboration_detail,
            self.char2,
            {
                "action": "disconnect",
                "version": self.project.version,
                "street": street.pk,
                "target": target_id,
                "direction": "east",
            },
            pk=self.project.pk,
        )
        self.assertEqual(response.status_code, 302)
        self.project.refresh_from_db()
        self.assertEqual(self.project.connections, [])
        self.call(
            CmdBuild(),
            f"/connect/remove {self.project.pk} {street.pk} {target_id}=east",
            caller=self.char2,
        )

    def test_geometry_and_cross_space_escape_are_refused(self):
        wrong = services.dig(
            self.char2, self.project, self.entry, "Misaligned", door="north", back="south", x=1
        )
        with self.assertRaisesMessage(ValidationError, "coordinates"):
            services.check_project(self.project)
        part = self.interior()
        with self.assertRaisesMessage(ValidationError, "one draft space"):
            services.add_door(self.char2, self.project, wrong, part.rooms.get(), "escape")

    def test_nonpublic_grid_target_and_closed_policy_refused(self):
        self.room2.db.allow_teleport = "secret"
        with self.assertRaisesMessage(ValidationError, "public world room"):
            frontier.propose_connection(self.char2, self.project, self.entry, self.room2, "east")
        self.room1.tags.add("closed", category="build_policy")
        with self.assertRaisesMessage(ValidationError, "closed"):
            self.submit()

    def test_manual_geometry_is_explicit_without_maps(self):
        if apps.is_installed("evennia_maps"):
            self.skipTest("Manual geometry is exercised with Maps physically absent.")
        submission = self.submit()
        with self.assertRaisesMessage(ValidationError, "certify geometry"):
            services.review(
                self.char1,
                submission,
                expected_revision=submission.revision,
                outcome="approved",
                reason="Not yet certified.",
            )
        self.approve(submission=submission)

    def test_steward_relinquishment_and_staff_assignment_are_explicit(self):
        result = self.approve()
        record = result.rooms.get()
        with self.assertRaises(PermissionDenied):
            frontier.set_steward(
                self.char2,
                record,
                self.recipient,
                expected_steward=self.char2.pk,
                reason="Cannot assign",
            )
        frontier.set_steward(
            self.char2, record, expected_steward=self.char2.pk, reason="Relinquish"
        )
        record.refresh_from_db()
        self.assertIsNone(record.steward_id)
        self.assertTrue(can_enter(self.outsider, record.room))
        frontier.set_steward(
            self.char1, record, self.recipient, expected_steward=None, reason="New caretaker"
        )
        with self.assertRaisesMessage(ValidationError, "changed"):
            frontier.set_steward(self.char1, record, expected_steward=None, reason="Stale")

    def test_quiet_steward_flags_only_and_active_return_resolves(self):
        result = self.approve()
        now = timezone.now()
        old = now - timedelta(days=40)
        BuildingClock.objects.create(pk=1, revealed_at=old)
        result.rooms.update(assigned_at=old)
        with patch("evennia_building.frontier_lifecycle.activity", return_value=old):
            self.assertEqual(len(frontier_lifecycle.check_quiet(now=now)), 1)
            self.assertEqual(len(frontier_lifecycle.check_quiet(now=now)), 1)
        self.assertEqual(StewardQuietFlag.objects.filter(resolved_at__isnull=True).count(), 1)
        self.assertEqual(result.rooms.get().steward_id, self.char2.pk)
        result.refresh_from_db()
        self.assertEqual(result.state, "live")
        with patch("evennia_building.frontier_lifecycle.activity", return_value=now):
            self.assertEqual(frontier_lifecycle.check_quiet(now=now), [])
        self.assertFalse(StewardQuietFlag.objects.filter(resolved_at__isnull=True).exists())

    def test_reveal_grace_and_runtime_threshold_apply_to_stewards(self):
        result = self.approve()
        now = timezone.now()
        result.rooms.update(assigned_at=now - timedelta(days=50))
        with patch("evennia_building.frontier_lifecycle.activity", return_value=None):
            self.assertEqual(frontier_lifecycle.check_quiet(now=now), [])
            BuildingClock.objects.update(revealed_at=now - timedelta(days=3))
            with override_settings(BUILDING_QUIET_DAYS=2):
                self.assertEqual(len(frontier_lifecycle.check_quiet(now=now)), 1)

    def test_frontier_archive_restore_preserves_geometry_contents_and_stewards(self):
        result = self.approve()
        item = create_object(
            "evennia.objects.objects.DefaultObject", key="Kept belonging", location=self.entry.room
        )
        self.collaborator.location = self.entry.room
        connection_ids = list(result.connections.values_list("object_id", flat=True))
        with override_settings(BUILDING_SAFE_ROOM=self.room1.pk):
            frontier_lifecycle.archive(self.char1, result, reason="Retire temporarily")
        result.refresh_from_db()
        self.assertEqual(result.state, "archived")
        self.assertFalse(can_enter(self.outsider, self.entry.room))
        self.assertFalse(room_visibility(self.entry.room))
        self.assertEqual(item.location, self.entry.room)
        self.assertEqual(self.collaborator.location, self.room1)
        frontier_lifecycle.restore(self.char1, result, reason="Return")
        self.assertTrue(can_enter(self.outsider, self.entry.room))
        self.assertEqual(
            list(result.connections.values_list("object_id", flat=True)), connection_ids
        )
        self.assertEqual(result.rooms.get().steward_id, self.char2.pk)

    def test_retirement_cannot_strand_home_and_group_can_be_restored(self):
        part = self.interior()
        self.acknowledge_all()
        result = self.approve()
        home = Property.objects.get(part=part)
        with self.assertRaisesMessage(ValidationError, "strand active homes"):
            frontier_lifecycle.archive(self.char1, result, reason="Incomplete plan")
        frontier_lifecycle.archive(
            self.char1, result, reason="Coordinated", affected_properties=[home]
        )
        home.refresh_from_db()
        self.assertEqual(home.state, "archived")
        frontier_lifecycle.restore(self.char1, result, reason="Restore street")
        lifecycle.restore(self.char1, home, reason="Restore home")
        self.assertTrue(can_enter(self.recipient, part.entry))

    def test_retirement_cannot_split_preexisting_public_places(self):
        street = self.street()
        frontier.propose_connection(self.char2, self.project, street, self.room2, "east")
        result = self.approve()
        with self.assertRaisesMessage(ValidationError, "strand active streets"):
            frontier_lifecycle.archive(self.char1, result, reason="Would sever the only road")
        result.refresh_from_db()
        self.assertEqual(result.state, "live")

    def test_plain_interior_snapshot_retains_release_02_shape(self):
        home = services.new_project(self.collaborator, "Ordinary home")
        services.attach(self.collaborator, home, self.room1, "ordinary home")
        home.refresh_from_db()
        candidate = services.snapshot(home)
        self.assertNotIn("kind", candidate)
        self.assertNotIn("collaboration", candidate)
        self.assertNotIn("part", candidate["rooms"][0])

    def web(self, view, actor, data=None, *, pk=None):
        from evennia_links.web import WebCharacterMiddleware

        self.account2.characters.add(actor)
        request = (
            RequestFactory().post("/", data) if data is not None else RequestFactory().get("/")
        )
        request.user = self.account2
        request.session = {"puppet": actor.pk}
        return WebCharacterMiddleware(
            lambda req: view(req, pk=pk) if pk is not None else view(req)
        )(request)

    def test_recipient_web_review_does_not_grant_authoring_or_entry(self):
        from . import frontier_views, views

        self.interior()
        response = self.web(frontier_views.collaboration_detail, self.recipient, pk=self.project.pk)
        self.assertContains(response, "Small home")
        self.assertContains(response, "Accept my proposed ownership")
        self.assertFalse(can_enter(self.recipient, self.entry.room))
        with self.assertRaises(PermissionDenied):
            self.web(
                views.project_detail, self.recipient, {"action": "description"}, pk=self.project.pk
            )
        with self.assertRaises(Http404):
            self.web(frontier_views.collaboration_detail, self.outsider, pk=self.project.pk)

    def test_web_acknowledgement_is_bound_to_candidate_and_selected_character(self):
        from .frontier_views import collaboration_detail

        self.interior()
        self.project.refresh_from_db()
        data = {
            "action": "ack_ownership",
            "version": self.project.version,
            "fingerprint": services.fingerprint(services.snapshot(self.project)),
            "acknowledgement": collaboration.wording("ownership"),
        }
        with self.assertRaises(Http404):
            self.web(collaboration_detail, self.outsider, data, pk=self.project.pk)
        services.edit_project(
            self.char2, self.project, room=self.entry, description="Changed candidate"
        )
        response = self.web(collaboration_detail, self.recipient, data, pk=self.project.pk)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.project.agreements.exists())
        self.project.refresh_from_db()
        data.update(
            version=self.project.version,
            fingerprint=services.fingerprint(services.snapshot(self.project)),
        )
        response = self.web(collaboration_detail, self.recipient, data, pk=self.project.pk)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.project.agreements.get().actor_id, self.recipient.pk)

    def test_web_invitation_requires_named_character_valid_answer_and_csrf(self):
        from .frontier_views import collaboration_answer

        row = collaboration.invite(self.char2, self.project, self.collaborator)
        with self.assertRaises(Http404):
            self.web(collaboration_answer, self.outsider, {"answer": "accept"}, pk=row.pk)
        self.assertEqual(
            self.web(
                collaboration_answer, self.collaborator, {"answer": "invalid"}, pk=row.pk
            ).status_code,
            400,
        )
        self.assertEqual(
            self.web(
                collaboration_answer, self.collaborator, {"answer": "accept"}, pk=row.pk
            ).status_code,
            302,
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.account2)
        self.assertEqual(
            client.post(
                f"/building/collaboration/{row.pk}/answer/", {"answer": "leave"}
            ).status_code,
            403,
        )

    def test_collaborator_web_edit_and_lead_only_controls(self):
        from . import frontier_views, views

        self.collaborate()
        self.project.refresh_from_db()
        response = self.web(
            views.project_detail,
            self.collaborator,
            {
                "action": "description",
                "version": self.project.version,
                "room": self.entry.pk,
                "value": "Shared description",
            },
            pk=self.project.pk,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(services._read_attr(self.entry.room, "desc"), "Shared description")
        response = self.web(
            frontier_views.collaboration_detail,
            self.collaborator,
            {"action": "invite", "character": self.outsider.pk, "version": self.project.version},
            pk=self.project.pk,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.project.contributors.filter(character=self.outsider).exists())

    def test_public_growth_pages_api_and_steward_controls_preserve_private_boundaries(self):
        from . import frontier_views
        from .api.views import frontiers

        part = self.interior()
        self.acknowledge_all()
        result = self.approve()
        for response in (
            self.web(frontier_views.frontier_index, self.outsider),
            self.web(frontier_views.frontier_detail, self.outsider, pk=result.pk),
        ):
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, part.name)
        response = self.web(frontiers, self.outsider)
        self.assertEqual([row["id"] for row in response.data[0]["rooms"]], [self.entry.room_id])
        response = self.web(
            frontier_views.frontier_detail,
            self.char2,
            {"action": "description", "room": result.rooms.get().pk, "text": "Maintained trail"},
            pk=result.pk,
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(room_permission(self.char2, self.entry.room, "configure"))
        with self.assertRaises(PermissionDenied):
            self.web(
                frontier_views.frontier_detail,
                self.outsider,
                {"action": "description"},
                pk=result.pk,
            )

    def test_apartment_in_mixed_home_uses_that_home_entry_and_preserves_other_spaces(self):
        part = self.interior()
        self.acknowledge_all()
        self.approve()
        home = Property.objects.get(part=part)
        self.assertEqual(attachments.default_route(home, part.entry), [part.entry_id])
        project = services.new_project(self.collaborator, "Independent apartment")
        services.attach(self.collaborator, project, part.entry, "apartment")
        project.refresh_from_db()
        receipt = attachments.request_consent(
            self.collaborator, project, expected_version=project.version
        )
        attachments.answer_consent(
            self.recipient, receipt, action="grant", acknowledgement=receipt.wording
        )
        child = self.approve(project)
        self.assertEqual(child.attachment.route["rooms"], [part.entry_id])
        self.assertTrue(can_enter(self.collaborator, part.entry))
        self.assertIsNone(owner_of(self.entry.room))

    def test_frontier_part_entrances_obey_hard_door_limit(self):
        self.street()
        self.interior()
        with (
            override_settings(BUILDING_DOOR_LIMIT=2, BUILDING_DOOR_LIMIT_HARD=True),
            self.assertRaisesMessage(ValidationError, "hard door limit"),
        ):
            self.submit()

    def test_leaving_after_promotion_preserves_independent_home_and_consumed_receipts(self):
        invitation = self.collaborate()
        part = frontier.add_interior(
            self.char2,
            self.project,
            self.entry,
            "Author home",
            owner=self.collaborator,
            entrance_name="author home",
        )
        self.acknowledge_all()
        result = self.approve()
        before = result.promotion.fingerprint
        collaboration.answer(self.collaborator, invitation, leave=True)
        self.assertEqual(Property.objects.get(part=part).owner_id, self.collaborator.pk)
        self.assertTrue(can_enter(self.collaborator, part.entry))
        self.assertEqual(result.promotion.fingerprint, before)
        self.assertTrue(self.project.agreements.filter(state="consumed").exists())

    def test_restore_refuses_occupied_external_direction(self):
        result = self.approve()
        frontier_lifecycle.archive(self.char1, result, reason="Temporarily retire")
        create_object(
            "evennia.objects.objects.DefaultExit",
            key="east",
            location=self.room1,
            destination=self.room2,
        )
        with self.assertRaises(ValidationError):
            frontier_lifecycle.restore(self.char1, result, reason="Occupied")
        result.refresh_from_db()
        self.assertEqual(result.state, "archived")

    def test_locked_bypass_cannot_justify_retiring_public_passage(self):
        street = self.street()
        frontier.propose_connection(self.char2, self.project, street, self.room2, "east")
        result = self.approve()
        for source, target in ((self.room1, self.room2), (self.room2, self.room1)):
            create_object(
                "evennia.objects.objects.DefaultExit",
                key="staff gate",
                location=source,
                destination=target,
                locks="traverse:false()",
            )
        with self.assertRaisesMessage(ValidationError, "strand active streets"):
            frontier_lifecycle.archive(
                self.char1, result, reason="Locked gates are not public passage"
            )

    def test_restore_rechecks_hard_door_limit(self):
        result = self.approve()
        frontier_lifecycle.archive(self.char1, result, reason="Temporarily retire")
        for name in ("extra one", "extra two"):
            create_object(
                "evennia.objects.objects.DefaultExit",
                key=name,
                location=self.room1,
                destination=self.room2,
            )
        with (
            override_settings(BUILDING_DOOR_LIMIT=2, BUILDING_DOOR_LIMIT_HARD=True),
            self.assertRaisesMessage(ValidationError, "hard door limit"),
        ):
            frontier_lifecycle.restore(self.char1, result, reason="Now too crowded")

    def test_restore_refuses_aligned_coordinates_on_unrelated_stack(self):
        if not apps.is_installed("evennia_maps"):
            self.skipTest("Map stacks require Maps.")
        from evennia_maps.models import MapPlane, RoomTile

        result = self.approve()
        frontier_lifecycle.archive(self.char1, result, reason="Temporarily retire")
        other = MapPlane.objects.create(name="Unrelated surface", zstack="unrelated")
        RoomTile.objects.filter(room=self.entry.room).update(plane=other)
        with self.assertRaisesMessage(ValidationError, "map stack"):
            frontier_lifecycle.restore(
                self.char1, result, reason="Same coordinates are not the same world"
            )

    def test_child_frontier_requires_coordinated_retirement(self):
        parent = self.approve()
        project = services.new_project(self.collaborator, "Dependent trail", kind="frontier")
        services.attach(self.collaborator, project, self.entry.room, "north")
        child = self.approve(project)
        with self.assertRaisesMessage(ValidationError, "strand active streets"):
            frontier_lifecycle.archive(self.char1, parent, reason="Missing child")
        frontier_lifecycle.archive(
            self.char1, parent, reason="Together", affected_frontiers=[child]
        )
        frontier_lifecycle.restore(self.char1, parent, reason="Restore together")
        child.refresh_from_db()
        self.assertEqual(child.state, "live")

    def test_reviewed_replacement_connection_preserves_public_access_during_retirement(self):
        if apps.is_installed("evennia_maps"):
            from evennia_maps.models import RoomTile

            RoomTile.objects.filter(room=self.room2).update(x=1, y=1)
        frontier.propose_connection(self.char2, self.project, self.entry, self.room2, "north")
        result = self.approve()
        frontier_lifecycle.archive(
            self.char1,
            result,
            reason="Reviewed diagonal bypass",
            replacements=[
                {"source": self.room1.pk, "target": self.room2.pk, "direction": "northeast"}
            ],
        )
        self.assertEqual(result.connections.filter(replacement=True).count(), 2)
        self.assertTrue(
            ObjectDB.objects.filter(
                db_location=self.room1, db_destination=self.room2, db_key="northeast"
            ).exists()
        )
        frontier_lifecycle.restore(self.char1, result, reason="Restore original road too")
        self.assertTrue(can_enter(self.outsider, self.entry.room))

    def test_command_collaboration_candidate_and_steward_adapters(self):
        from .commands import CmdBuild

        self.call(
            CmdBuild(),
            f"/collaborator/add {self.project.pk} {self.collaborator.pk}",
            caller=self.char2,
        )
        invitation = self.project.contributors.get()
        self.call(CmdBuild(), f"/collaborator/accept {invitation.pk}", caller=self.collaborator)
        self.project.refresh_from_db()
        shown = self.call(CmdBuild(), f"/ack/show {self.project.pk}", caller=self.collaborator)
        self.assertIn(services.fingerprint(services.snapshot(self.project)), shown)
        self.acknowledge_all()
        result = self.approve()
        self.call(
            CmdBuild(),
            f"/frontier/desc {self.entry.room_id}=Maintained through commands.",
            caller=self.char2,
        )
        self.assertEqual(
            services._read_attr(self.entry.room, "desc"), "Maintained through commands."
        )
        self.call(
            CmdBuild(),
            f"/frontier/steward {self.entry.room_id} {self.char2.pk} 0=Relinquished",
            caller=self.char2,
        )
        self.assertIsNone(result.rooms.get().steward_id)
