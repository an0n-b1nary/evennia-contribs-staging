# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Player journeys through room context, exact-state tokens and destination doors."""

import re
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import override_settings
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTestMixin, EvenniaTest

from . import attachments, collaboration, doors, lifecycle, services
from .commands import CmdBuild, CmdCollab, CmdConsent, CmdFrontier, CmdPassage, CmdProperty
from .models import AttachmentAgreement, BuildProject, BuildSubmission, GuestInvitation, Property
from .request_form import FORM, FORM_KEY


@override_settings(
    BUILDING_REVEALED=True,
    BUILDING_REUSE_ACKNOWLEDGEMENT="This game's content reuse terms.",
    JOBS_REQUEST_FORMS={FORM_KEY: FORM},
    LINKS_ROOM_TRAVEL="evennia_building.access.can_teleport",
    LINKS_ROOM_VISIBILITY="evennia_building.visibility.room_visibility",
    ROOT_URLCONF="evennia_building.tests",
)
class PlayerCommandTests(EvenniaCommandTestMixin, EvenniaTest):
    """Use real services and objects; no parser or authorization mocks."""

    def setUp(self):
        super().setUp()
        self.room1.db.room_type = "ic"
        self.room1.db.allow_teleport = "public"
        self.room1.key = "Market Street"
        self.project = services.new_project(self.char2, "The Bakery")
        self.entry = self.project.rooms.get(entry=True)
        services.attach(self.char2, self.project, self.room1, "The Bakery")
        self.project.refresh_from_db()
        services.enter(self.char2, self.project)

    def command(self, cls, args="", actor=None):
        return self.call(cls(), args, caller=actor or self.char2)

    def token(self, cls, args, actor=None):
        output = self.command(cls, args, actor)
        match = re.search(r"[.\w-]+:[\w-]+:[\w-]+", output)
        self.assertIsNotNone(match, output)
        return match.group()

    def approve(self, project=None, actor=None):
        project, actor = project or self.project, actor or self.char2
        project.refresh_from_db()
        submission = services.submit(
            actor,
            project,
            expected_version=project.version,
            acknowledgement=collaboration.wording("contributor"),
        )
        services.review(
            self.char1,
            submission,
            expected_revision=submission.revision,
            outcome="approved",
            reason="Ready to open.",
        )
        return Property.objects.get(promotion=submission)

    def test_dig_uses_current_room_destination_names_and_direction_triggers(self):
        shown = self.command(CmdBuild, "/dig north=Kitchen")
        kitchen = self.project.rooms.get(room__db_key="Kitchen")
        self.assertEqual((kitchen.x, kitchen.y, kitchen.floor), (0, 1, 0))
        door = self.project.doors.get(source=self.entry, target=kitchen).exit
        back = self.project.doors.get(source=kitchen, target=self.entry).exit
        self.assertEqual(door.key, "Kitchen")
        self.assertEqual(set(door.aliases.all()), {"n", "north"})
        self.assertEqual(back.key, "The Bakery")
        self.assertEqual(set(back.aliases.all()), {"s", "south"})
        self.assertTrue(door.attributes.get(doors.FOLLOW))
        self.assertIn("triggered by Kitchen", shown)
        self.command(CmdBuild, f"/room #{kitchen.object_id}")
        self.command(CmdBuild, "/desc A flour-dusted workroom.")
        self.assertEqual(kitchen.room.db.desc, "A flour-dusted workroom.")
        self.assertIsNone(self.entry.room.db.desc)
        self.command(CmdBuild, "/name Cookhouse")
        self.assertEqual(door.key, "Cookhouse")

    def test_room_plan_persists_and_custom_names_do_not_follow(self):
        self.command(CmdBuild, "/dig Quiet Study")
        self.char2.attributes.reset_cache()
        self.command(CmdBuild, "/x 3")
        self.command(CmdBuild, "/y 2")
        self.command(CmdBuild, "/floor 1")
        self.command(CmdBuild, "/doorname a narrow staircase")
        self.command(CmdBuild, "/back the landing")
        self.command(CmdBuild, "/finish")
        study = self.project.rooms.get(room__db_key="Quiet Study")
        self.assertEqual((study.x, study.y, study.floor), (3, 2, 1))
        door = self.project.doors.get(target=study).exit
        study.room.key = "A New Study Name"
        self.assertEqual(door.key, "a narrow staircase")
        report = services.check_project(self.project)
        self.assertTrue(any("non-neighbouring" in line for line in report["warnings"]))

    def test_stale_room_plan_and_occupied_cell_do_not_partially_create(self):
        self.command(CmdBuild, "/dig Kitchen")
        self.command(CmdBuild, "/direction east")
        self.command(CmdBuild, "/title A renamed project")
        self.assertIn("project changed", self.command(CmdBuild, "/finish"))
        self.assertEqual(self.project.rooms.count(), 1)
        self.command(CmdBuild, "/cancel")
        self.command(CmdBuild, "/dig Kitchen")
        self.assertIn("occupied", self.command(CmdBuild, "/finish"))
        self.assertEqual(self.project.rooms.count(), 1)

    def test_legacy_stacked_positional_json_and_bad_switches_cannot_mutate(self):
        version = BuildProject.objects.get(pk=self.project.pk).version
        for args in (
            f"/resident/add 1 {self.char1.pk}",
            "/name/desc Changed",
            "/desc/desc Changed",
            f"/dig {self.project.pk} {self.entry.pk} 0 1 0=Kitchen,inside,out",
            f'/environment {self.project.pk}={{"terrain":["urban"]}}',
            "/new interior=Another home",
            "/unknown Changed",
            "/d Changed",
            "/desc =Leading equals",
            "/doorname unknown=field",
        ):
            with self.subTest(args=args):
                self.command(CmdBuild, args)
        self.assertEqual(self.project.rooms.count(), 1)
        self.assertEqual(BuildProject.objects.get(pk=self.project.pk).version, version)
        self.assertIsNone(self.entry.room.db.desc)
        self.command(CmdBuild, "/des A unique switch prefix works.")
        self.assertEqual(self.entry.room.db.desc, "A unique switch prefix works.")

    def test_context_never_allows_editing_someone_elses_draft(self):
        self.char1.permissions.clear()
        self.char1.account.permissions.clear()
        self.char1.account.is_superuser = False
        self.char1.account.save()
        self.char1.location = self.entry.room
        shown = self.command(CmdBuild, "/desc An unauthorized edit", self.char1)
        self.assertIn("Stand in your project", shown)
        self.assertIsNone(self.entry.room.db.desc)
        self.char2.location = self.room1
        self.assertIn("Stand in your project", self.command(CmdBuild, "/desc Wrong place"))

    def test_submission_token_binds_actor_candidate_terms_and_expiry(self):
        token = self.token(CmdBuild, "/submit")
        self.assertFalse(BuildSubmission.objects.filter(project=self.project).exists())
        self.command(CmdBuild, "/desc Added after preview")
        self.assertIn("changed", self.command(CmdBuild, f"/submit {token}"))
        token = self.token(CmdBuild, "/submit")
        with override_settings(BUILDING_REUSE_ACKNOWLEDGEMENT="Revised terms."):
            self.assertIn("changed", self.command(CmdBuild, f"/submit {token}"))
        with patch("django.core.signing.time.time", return_value=9999999999):
            self.assertIn("expired", self.command(CmdBuild, f"/submit {token}"))
        self.command(CmdBuild, f"/submit {token}")
        self.project.refresh_from_db()
        self.assertEqual(self.project.state, "submitted")
        self.assertIn("Withdraw", self.command(CmdBuild, "/desc Cannot edit a frozen room"))

    def test_withdraw_and_discard_tokens_keep_safety_and_audit(self):
        token = self.token(CmdBuild, "/submit")
        self.command(CmdBuild, f"/submit {token}")
        token = self.token(CmdBuild, "/withdraw # Correct the entrance")
        self.command(CmdBuild, f"/withdraw {token} # Correct the entrance")
        self.project.refresh_from_db()
        self.assertEqual(self.project.state, "draft")
        self.assertEqual(
            self.project.audit.get(action="withdrawn").data["reason"], "Correct the entrance"
        )
        token = self.token(CmdBuild, "/discard")
        item = create_object(
            "evennia.objects.objects.DefaultObject", key="A keepsake", location=self.entry.room
        )
        self.command(CmdBuild, f"/discard {token}")
        self.project.refresh_from_db()
        self.assertEqual(self.project.state, "discarded")
        self.assertEqual(self.char2.location, self.room1)
        self.assertEqual(item.location, self.room1)

    def test_collaboration_requires_each_actors_exact_candidate_agreement(self):
        guest = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Draft Author", location=self.room1
        )
        self.command(CmdCollab, f"/add #{guest.pk}")
        invitation = self.project.contributors.get()
        self.command(CmdCollab, f"/accept {invitation.pk}", guest)
        services.enter(guest, self.project)
        self.command(CmdBuild, "/desc Written by the collaborator", guest)
        token = self.token(CmdCollab, f"/contributor {self.project.pk}", guest)
        self.assertFalse(self.project.agreements.exists())
        self.assertIn(
            "does not request", self.command(CmdCollab, f"/contributor {self.project.pk}={token}")
        )
        self.command(CmdCollab, f"/contributor {self.project.pk}={token}", guest)
        self.assertTrue(self.project.agreements.filter(actor=guest, state="accepted").exists())
        self.command(CmdCollab, f"/remove #{guest.pk}")
        self.project.refresh_from_db()
        self.assertIn((guest.pk, "contributor"), collaboration.required(self.project))
        self.assertIn(
            "changed", self.command(CmdCollab, f"/contributor {self.project.pk}={token}", guest)
        )

    def test_environment_fields_merge_and_inherit_independently(self):
        self.command(CmdBuild, "/terrain urban, garden")
        if apps.is_installed("evennia_regions"):
            self.command(CmdBuild, "/region none")
            self.command(CmdBuild, "/inherit terrain")
            self.project.refresh_from_db()
            self.assertEqual(self.project.requested_environment, {"region": None})
        else:
            self.assertIn("not installed", self.command(CmdBuild, "/region none"))
            self.project.refresh_from_db()
            self.assertEqual(self.project.requested_environment, {"terrain": ["garden", "urban"]})

    def test_property_rights_use_current_property_and_explicit_guest_acceptance(self):
        property = self.approve()
        self.command(CmdProperty, "/name The Front Room")
        self.command(CmdProperty, "/desc An open bakery.")
        self.assertEqual(self.entry.room.key, "The Front Room")
        self.assertEqual(self.entry.room.db.desc, "An open bakery.")
        guest = create_object(
            "evennia.objects.objects.DefaultCharacter", key="A Guest", location=self.room1
        )
        self.command(CmdProperty, "/lock")
        self.command(CmdProperty, f"/entry #{guest.pk}")
        invitation = GuestInvitation.objects.get(property=property, character=guest)
        self.assertTrue(invitation.entry)
        self.assertFalse(invitation.maps)
        from .access import can_enter

        self.assertFalse(can_enter(guest, self.entry.room))
        self.assertIn(
            f"Invitation {invitation.pk}", self.command(CmdProperty, "/invitations", guest)
        )
        self.command(CmdProperty, f"/accept {invitation.pk}", guest)
        self.assertTrue(can_enter(guest, self.entry.room))
        self.command(CmdProperty, f"/installer #{guest.pk}")
        self.assertTrue(property.residents.get(character=guest).can_install)
        self.command(CmdProperty, f"/resident #{guest.pk}")
        self.assertFalse(property.residents.get(character=guest).can_install)
        self.command(CmdProperty, "/override")
        self.assertFalse(can_enter(guest, self.entry.room))
        self.command(CmdProperty, "/reset")
        self.assertTrue(can_enter(guest, self.entry.room))

    def test_approval_departure_and_internal_defaults_follow_destination_renames(self):
        self.command(CmdBuild, "/dig north=Kitchen")
        kitchen = self.project.rooms.get(room__db_key="Kitchen")
        door = self.project.doors.get(target=kitchen).exit
        property = self.approve()
        self.assertEqual(property.departure.key, "Market Street")
        self.assertEqual(set(property.departure.aliases.all()), {"out", "o", "outside"})
        self.assertIn("in", property.entrance.aliases.all())
        self.room1.key = "Market Square"
        self.assertEqual(property.departure.key, "Market Square")
        self.char2.location = kitchen.room
        self.command(CmdProperty, "/name The Cookhouse")
        self.assertEqual(door.key, "The Cookhouse")
        lifecycle.archive(self.char1, property, reason="Repairs")
        self.room1.key = "Old Market Square"
        lifecycle.restore(self.char1, property, reason="Reopen")
        self.assertEqual(property.departure.key, "Old Market Square")

    def test_reserved_departure_triggers_and_tagged_names_are_refused(self):
        for name in ("outside", "out", "o", "Market Street", "<N> Kitchen"):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                services.dig(self.char2, self.project, self.entry, "A Room", door=name, x=1)
        self.assertEqual(self.project.rooms.count(), 1)
        self.command(CmdBuild, "/dig north=Kitchen")
        shown = self.command(CmdBuild, "/aliases Kitchen=outside")
        self.assertIn("reserves", shown)

    def test_rename_clashes_keep_old_name_and_get_review_warning(self):
        self.command(CmdBuild, "/dig north=Kitchen")
        self.command(CmdBuild, "/dig east=Study")
        kitchen = self.project.rooms.get(room__db_key="Kitchen")
        door = self.project.doors.get(target=kitchen).exit
        kitchen.room.key = "Study"
        self.assertEqual(door.key, "Kitchen")
        self.assertEqual(door.attributes.get(doors.CLASH), "Study")
        self.assertIn("clashes", self.command(CmdBuild, "/check"))

    def test_declared_direction_mismatch_warns_and_aliases_are_unique(self):
        self.command(CmdBuild, "/dig north=Kitchen")
        self.command(CmdBuild, "/aliases Kitchen=east")
        self.assertIn("disagrees", self.command(CmdBuild, "/check"))
        self.assertIn("already in use", self.command(CmdBuild, "/dig east=Study"))
        self.assertEqual(self.project.rooms.count(), 2)

    def test_consent_and_passage_tokens_survive_cosmetic_parent_door_renames(self):
        self.command(CmdBuild, "/dig north=Hall")
        hall = self.project.rooms.get(room__db_key="Hall")
        self.approve()
        tenant = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Apartment Owner", location=self.room1
        )
        project = services.new_project(tenant, "The Apartment")
        services.attach(tenant, project, hall.room, "Apartment")
        services.enter(tenant, project)
        self.command(CmdConsent, "/request", tenant)
        consent = project.consents.get()
        token = self.token(CmdConsent, f"/grant {consent.pk}")
        self.room1.key = "Market Square"
        self.command(CmdConsent, f"/grant {consent.pk}={token}")
        child = self.approve(project, tenant)
        agreement = AttachmentAgreement.objects.get(child=child)
        self.assertTrue(attachments.route_valid(agreement))
        self.char2.location = hall.room
        self.command(CmdProperty, "/name A Renamed Hall")
        self.assertTrue(attachments.route_valid(agreement))
        change = attachments.propose_passage(
            self.char1, agreement, agreement.route["rooms"], reason="Confirm this route"
        )
        for actor in (self.char2, tenant):
            token = self.token(CmdPassage, f"/accept {change.pk}", actor)
            self.command(CmdPassage, f"/accept {change.pk}={token}", actor)
        attachments.apply_passage(self.char1, change)
        lifecycle.archive(self.char1, child, reason="Pause")
        self.entry.room.key = "The Front Room"
        lifecycle.restore(self.char1, child, reason="Resume")
        self.assertTrue(attachments.route_valid(agreement))

    def test_hidden_world_rooms_cannot_be_selected_by_guessing_an_id(self):
        self.room2.db.allow_teleport = "secret"
        shown = self.command(CmdBuild, f"/attach #{self.room2.pk}=Hidden door")
        self.assertIn("accessible", shown)
        self.project.refresh_from_db()
        self.assertEqual(self.project.anchor_id, self.room1.pk)

    def test_second_home_can_share_an_anchor_without_stealing_a_named_entrance(self):
        self.approve()
        second = services.new_project(self.char2, "A second home")
        services.attach(self.char2, second, self.room1, "The second home")
        property = self.approve(second)
        self.assertIn("in", property.entrance.aliases.all())

    def test_canonical_receipts_keep_room_names_custom_names_aliases_and_ids(self):
        room = {"id": 1, "name": "A room"}
        self.assertNotEqual(
            services.fingerprint(room), services.fingerprint({**room, "name": "Changed"})
        )
        exit = {"id": 2, "name": "A room", "source": 1, "target": 3, "follows": 3, "aliases": ["n"]}
        self.assertEqual(
            services.fingerprint(exit), services.fingerprint({**exit, "name": "Changed"})
        )
        self.assertNotEqual(
            services.fingerprint(exit), services.fingerprint({**exit, "aliases": ["s"]})
        )
        self.assertNotEqual(services.fingerprint(exit), services.fingerprint({**exit, "id": 4}))

    def test_description_text_preserves_equals_semicolons_and_other_literal_punctuation(self):
        text = "A sign reads x = y; {literal}: a | b ~ c # a note."
        self.command(CmdBuild, "/desc " + text)
        self.assertEqual(self.entry.room.db.desc, text)
        self.approve()
        self.command(CmdProperty, "/desc " + text)
        self.assertEqual(self.entry.room.db.desc, text)

    def test_frontier_mixed_interior_ownership_and_steward_journey(self):
        from . import frontier
        from .models import Frontier

        if apps.is_installed("evennia_maps"):
            from evennia_maps.models import MapPlane, RoomTile
            from evennia_maps.placement import place_tile

            RoomTile.objects.filter(room=self.room1).delete()
            plane = MapPlane.objects.create(name="Player Command World", zstack="command-world")
            place_tile(self.room1, plane, 0, 0, actor=self.char1)
        self.command(CmdFrontier, "/new New Village")
        project = BuildProject.objects.get(owner=self.char2, name="New Village")
        self.command(CmdBuild, f"/enter {project.pk}")
        entry = project.rooms.get(entry=True)
        self.command(CmdBuild, f"/attach #{self.room1.pk}=north")
        self.command(CmdBuild, "/interior The Teahouse")
        part = project.parts.get()
        recipient = create_object(
            "evennia.objects.objects.DefaultCharacter", key="Teahouse Owner", location=self.room1
        )
        self.command(CmdBuild, f"/room #{part.entry_id}")
        self.command(CmdBuild, f"/owner #{recipient.pk}")
        self.command(CmdBuild, "/title The Quiet Teahouse")
        self.command(CmdBuild, "/entrance the teahouse door")
        part.refresh_from_db()
        self.assertEqual(part.owner_id, recipient.pk)
        self.assertEqual(part.name, "The Quiet Teahouse")
        token = self.token(CmdCollab, f"/ownership {project.pk}", recipient)
        self.command(CmdCollab, f"/ownership {project.pk}={token}", recipient)
        self.command(CmdBuild, f"/room #{entry.object_id}")
        token = self.token(CmdBuild, "/submit")
        self.command(CmdBuild, f"/submit {token}")
        submission = project.submissions.get()
        if not apps.is_installed("evennia_maps"):
            frontier.approve_geometry(
                self.char1, submission, expected_revision=submission.revision, reason="Reviewed"
            )
        services.review(
            self.char1,
            submission,
            expected_revision=submission.revision,
            outcome="approved",
            reason="Approved",
        )
        result = Frontier.objects.get(promotion=submission)
        property = Property.objects.get(part=part)
        self.assertEqual(property.owner_id, recipient.pk)
        self.assertEqual(property.departure.key, entry.room.key)
        self.command(CmdFrontier, "/desc A well-kept village street.")
        self.assertEqual(entry.room.db.desc, "A well-kept village street.")
        token = self.token(CmdFrontier, "/relinquish # Handing back to staff")
        self.command(CmdFrontier, f"/relinquish {token} # Handing back to staff")
        self.assertIsNone(result.rooms.get(room=entry.room).steward_id)
