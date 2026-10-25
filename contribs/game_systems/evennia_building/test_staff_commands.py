# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Staff journeys with real services, signed confirmations and optional partners."""

import re
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import override_settings
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTestMixin, EvenniaTest

from . import attachments, collaboration, frontier, services
from .commands import CmdBuild, CmdBuildAdmin, CmdPassage
from .models import BuildAudit, BuildReview, Frontier, PassageChange, Property
from .request_form import FORM, FORM_KEY
from .staff_commands import DRAFT_KEY


@override_settings(
    BUILDING_REVEALED=True,
    BUILDING_REUSE_ACKNOWLEDGEMENT="This game's content reuse terms.",
    JOBS_REQUEST_FORMS={FORM_KEY: FORM},
    LINKS_ROOM_PERMISSION="evennia_building.access.room_permission",
    LINKS_ROOM_OWNER="evennia_building.access.owner_of",
    LINKS_ROOM_TRAVEL="evennia_building.access.can_teleport",
    ROOT_URLCONF="evennia_building.tests",
)
class StaffCommandTests(EvenniaCommandTestMixin, EvenniaTest):
    """Exercise the entire adapter without mocking authorization or domain writes."""

    def setUp(self):
        super().setUp()
        self.room1.db.room_type = "ic"
        self.room1.db.allow_teleport = "public"
        self.room1.key = "Market Street"
        self.recipient = create_object(
            self.character_typeclass, key="New Owner", location=self.room1
        )
        self.project = services.new_project(self.char2, "The Bakery")
        self.entry = self.project.rooms.get(entry=True)
        services.attach(self.char2, self.project, self.room1, "The Bakery")

    def command(self, args="", actor=None, cls=CmdBuildAdmin):
        with self.captureOnCommitCallbacks(execute=True):
            return self.call(cls(), args, caller=actor or self.char1)

    def confirmation(self, args, actor=None, cls=CmdBuildAdmin):
        output = self.command(args, actor, cls)
        match = re.search(r"Confirm within 15 minutes: (\+\S+) (.*)", output)
        self.assertIsNotNone(match, output)
        return match.group(1).removeprefix(cls.key) + " " + match.group(2)

    def confirm(self, args, actor=None, cls=CmdBuildAdmin):
        return self.command(self.confirmation(args, actor, cls), actor, cls)

    def submit(self, project=None, actor=None):
        project, actor = project or self.project, actor or self.char2
        project.refresh_from_db()
        return services.submit(
            actor,
            project,
            expected_version=project.version,
            acknowledgement=collaboration.wording("contributor"),
        )

    def approve(self, project=None, actor=None):
        submission = self.submit(project, actor)
        self.confirm(f"/approve {submission.pk} # Ready to open.")
        return Property.objects.get(promotion=submission)

    def apartment(self, parent):
        project = services.new_project(self.recipient, "Independent apartment")
        services.attach(self.recipient, project, parent.rooms.get().room, "Apartment")
        project.refresh_from_db()
        consent = attachments.request_consent(
            self.recipient, project, expected_version=project.version
        )
        attachments.answer_consent(
            self.char2, consent, action="grant", acknowledgement=consent.wording
        )
        return self.approve(project, self.recipient)

    def public_frontier(self, *, anchor=None, name="New trail"):
        anchor = anchor or self.room1
        if apps.is_installed("evennia_maps") and not hasattr(self, "plane"):
            from evennia_maps.models import MapPlane, RoomTile
            from evennia_maps.placement import place_tile

            RoomTile.objects.filter(room=self.room1).delete()
            self.plane = MapPlane.objects.create(name="Shared world", zstack="staff-test")
            place_tile(self.room1, self.plane, 0, 0, actor=self.char1)
        # The default fixture's portal must not claim an east/west grid port.
        project = services.new_project(self.char2, name, kind="frontier")
        services.attach(self.char2, project, anchor, "east")
        submission = self.submit(project)
        if not apps.is_installed("evennia_maps"):
            self.confirm(f"/geometry {submission.pk} # Checked all compass connections.")
        self.confirm(f"/approve {submission.pk} # Public route checked.")
        return Frontier.objects.get(promotion=submission)

    def test_staff_authorization_precedes_target_and_draft_lookup(self):
        self.char2.permissions.clear()
        self.char2.account.permissions.clear()
        self.char2.account.is_superuser = False
        self.char2.account.save()
        for args in ("", "/approve 999 # secret", "/draft", "/transfer 999=999", "/quiet"):
            self.assertIn("staff", self.command(args, self.char2).lower())
        self.assertFalse(self.char2.attributes.has(DRAFT_KEY))
        command = CmdBuildAdmin()
        self.assertFalse(command.access(self.char2, "cmd"))
        self.assertTrue(command.access(self.char1, "cmd"))
        with override_settings(BUILDING_REVEALED=False):
            self.assertIn("No Building submissions", self.command())
        self.char2.permissions.add("Builder")
        self.char2.account.permissions.add("Builder")
        self.assertTrue(command.access(self.char2, "cmd"))
        with override_settings(BUILDING_STAFF_LOCK="perm(Admin)"):
            self.assertFalse(command.access(self.char2, "cmd"))
            self.assertIn("staff", self.command("/draft", self.char2).lower())

    def test_queue_frozen_show_and_copyable_approval_confirmation(self):
        submission = self.submit()
        self.assertIn(f"{submission.pk}: The Bakery", self.command())
        self.assertIn("No description", self.command(str(submission.pk)))
        before = BuildAudit.objects.count()
        reason = "Reviewed; x=y | ~ : and # retained"
        apply = self.confirmation(f"/APPROVE {submission.pk} # {reason}")
        self.assertTrue(apply.endswith(f" # {reason}"), apply)
        self.assertFalse(Property.objects.exists())
        self.assertEqual(BuildAudit.objects.count(), before)
        self.assertIn("approve recorded", self.command(apply))
        self.assertEqual(BuildReview.objects.get(submission=submission).reason, reason)
        self.assertIn("No Building submissions", self.command())

    def test_review_token_refuses_reason_action_actor_candidate_and_expiry_changes(self):
        submission = self.submit()
        apply = self.confirmation(f"/approve {submission.pk} # Checked")
        for altered in (apply.replace("Checked", "Other"), apply.replace("/approve", "/decline")):
            self.assertIn("changed", self.command(altered))
        self.recipient.permissions.add("Builder")
        self.assertIn("changed", self.command(apply, self.recipient))
        with patch("django.core.signing.time.time", return_value=9999999999):
            self.assertIn("expired", self.command(apply))
        self.entry.room.db.desc = "Changed directly after review preview"
        self.assertIn("changed", self.command(apply))
        self.assertFalse(BuildReview.objects.exists())
        self.assertFalse(Property.objects.exists())

    def test_new_revision_invalidates_review_and_changes_and_decline_remain_distinct(self):
        submission = self.submit()
        stale = self.confirmation(f"/approve {submission.pk} # Checked")
        self.confirm(f"/changes {submission.pk} # Please describe the room.")
        self.project.refresh_from_db()
        services.edit_project(
            self.char2, self.project, room=self.entry, description="A warm bakery."
        )
        revised = self.submit()
        self.assertIn("current", self.command(stale))
        self.confirm(f"/decline {revised.pk} # Unsuitable location.")
        self.assertEqual(
            list(BuildReview.objects.order_by("pk").values_list("outcome", flat=True)),
            ["changes_requested", "declined"],
        )
        self.assertFalse(Property.objects.exists())

    def test_environment_requires_its_own_explicit_confirmation(self):
        self.project.refresh_from_db()
        services.request_environment(self.char2, self.project, {"terrain": ["urban"]})
        submission = self.submit()
        self.assertIn("explicitly approve", self.confirm(f"/approve {submission.pk} # Checked"))
        apply = self.confirmation(f"/environment {submission.pk} # Urban setting checked")
        self.assertFalse(hasattr(submission, "environment_approval"))
        self.command(apply)
        self.confirm(f"/approve {submission.pk} # Checked")
        self.assertEqual(set(self.entry.room.db.terrain_tags), {"urban"})

    def test_transfer_draft_persists_and_previews_then_clears_grants(self):
        property = self.approve()
        services.set_resident(self.char2, property, self.recipient, can_install=True)
        self.command(f"/transfer {property.pk}=#{self.recipient.pk} # Owner left; keys handed over")
        self.char1.attributes.reset_cache()
        self.assertIn("Grants: clear", self.command("/draft"))
        self.assertIn("existing staff draft", self.command(f"/archive {property.pk}"))
        apply = self.confirmation("/finish")
        property.refresh_from_db()
        self.assertEqual(property.owner_id, self.char2.pk)
        self.command(apply)
        property.refresh_from_db()
        self.assertEqual(property.owner_id, self.recipient.pk)
        self.assertFalse(property.residents.exists())
        self.assertFalse(self.char1.attributes.has(DRAFT_KEY))
        self.assertEqual(
            property.audit.get(action="transferred").data["reason"], "Owner left; keys handed over"
        )

    def test_transfer_confirmation_binds_rights_owner_and_draft_edits(self):
        property = self.approve()
        self.command(f"/transfer {property.pk}=#{self.recipient.pk} # Reassign")
        apply = self.confirmation("/finish")
        self.command("/grants retain")
        self.command("/grants clear")
        self.assertIn("changed", self.command(apply))
        apply = self.confirmation("/finish")
        services.set_resident(self.char2, property, self.recipient)
        self.assertIn("changed", self.command(apply))
        self.command("/grants RETAIN")
        apply = self.confirmation("/finish")
        self.command("/cancel")
        self.command(f"/transfer {property.pk}=#{self.recipient.pk} # Reassign")
        self.command("/grants retain")
        self.assertIn("changed", self.command(apply))
        services.transfer(
            self.char1, property, self.recipient, expected_owner=self.char2.pk, reason="Other staff"
        )
        self.assertIn("owner changed", self.command("/finish"))
        self.assertTrue(self.char1.attributes.has(DRAFT_KEY))

    def test_failed_transfer_rolls_back_and_keeps_private_draft(self):
        from .signals import property_transferring

        property = self.approve()
        self.command(f"/transfer {property.pk}=#{self.recipient.pk} # Reassign")
        apply = self.confirmation("/finish")

        def refuse(sender, **kwargs):
            raise ValidationError("Partner refused transfer.")

        property_transferring.connect(refuse, weak=False)
        try:
            self.assertIn("Partner refused", self.command(apply))
        finally:
            property_transferring.disconnect(refuse)
        property.refresh_from_db()
        self.assertEqual(property.owner_id, self.char2.pk)
        self.assertTrue(self.char1.attributes.has(DRAFT_KEY))
        self.assertFalse(property.audit.filter(action="transferred").exists())
        self.command(apply)
        property.refresh_from_db()
        self.assertEqual(property.owner_id, self.recipient.pk)

    def test_archive_requires_explicit_apartments_and_restores_parent_first(self):
        parent = self.approve()
        child = self.apartment(parent)
        self.recipient.location = child.rooms.get().room
        keepsake = create_object(
            "evennia.objects.objects.DefaultObject",
            key="Keepsake",
            location=self.recipient.location,
        )
        self.command(f"/archive {parent.pk} # Temporary retirement")
        self.assertIn("children yes", self.command("/finish"))
        self.command("/children YES")
        apply = self.confirmation("/finish")
        preview = self.command("/draft")
        self.assertIn(f"Property {child.pk}", preview)
        self.assertIn(f"owner {self.recipient.key}", preview)
        self.command(apply)
        for item in (parent, child):
            item.refresh_from_db()
            self.assertEqual(item.state, "archived")
        self.assertEqual(keepsake.location, child.rooms.get().room)
        self.assertNotEqual(self.recipient.location, child.rooms.get().room)
        self.assertIn("parent", self.confirm(f"/restore {child.pk} # Return home").lower())
        self.confirm(f"/restore {parent.pk} # Reopen the parent")
        self.confirm(f"/restore {child.pk} # Return home")
        child.refresh_from_db()
        self.assertEqual(child.state, "live")

    def test_new_apartment_invalidates_an_existing_group_confirmation(self):
        parent = self.approve()
        self.command(f"/archive {parent.pk} # Temporary retirement")
        self.command("/children yes")
        apply = self.confirmation("/finish")
        child = self.apartment(parent)
        self.assertIn("changed", self.command(apply))
        self.assertEqual(
            Property.objects.filter(pk__in=[parent.pk, child.pk], state="live").count(), 2
        )

    def test_passage_staff_cannot_replace_either_owners_acceptance(self):
        parent = self.approve()
        child = self.apartment(parent)
        agreement = child.attachment
        route = agreement.route["rooms"]
        self.command(
            f"/passage {agreement.pk}="
            + ",".join(f"#{pk}" for pk in route)
            + " # Reaffirm this passage"
        )
        self.confirm("/finish")
        change = PassageChange.objects.get()
        self.assertIn("Both current owners", self.command(f"/apply {change.pk}"))
        self.assertIn("owner", self.command(f"/accept {change.pk}", cls=CmdPassage).lower())
        for owner in (self.char2, self.recipient):
            self.confirm(f"/accept {change.pk}", owner, CmdPassage)
        apply = self.confirmation(f"/apply {change.pk}")
        self.command(apply)
        change.refresh_from_db()
        self.assertEqual(change.state, "applied")

    def test_draft_messages_match_their_effect(self):
        self.assertIn("no staff draft", self.command("/cancel"))
        self.assertIn("live frontier", self.command(f"/steward #{self.room1.pk}=none # Not public"))
        self.assertFalse(self.char1.attributes.has(DRAFT_KEY))
        parent = self.approve()
        child = self.apartment(parent)
        agreement = child.attachment
        self.command(
            f"/passage {agreement.pk}="
            + ",".join(f"#{pk}" for pk in agreement.route["rooms"])
            + " # Reaffirm this passage"
        )
        output = self.confirm("/finish")
        self.assertIn("proposed", output)
        self.assertNotIn("applied", output)
        self.command(f"/archive {parent.pk} # Temporary retirement")
        self.command("/children yes")
        self.assertIn("; 1 room.", self.command("/draft"))

    def test_steward_assignment_binds_current_steward_and_preview_is_pure(self):
        area = self.public_frontier()
        record = area.rooms.get()
        self.command(f"/steward #{record.object_id}=#{self.recipient.pk} # New caretaker")
        apply = self.confirmation("/finish")
        record.refresh_from_db()
        self.assertEqual(record.steward_id, self.char2.pk)
        frontier.set_steward(
            self.char1, record, None, expected_steward=self.char2.pk, reason="Departed"
        )
        self.assertIn("steward changed", self.command(apply))
        self.command("/cancel")
        self.command(f"/steward #{record.object_id}=#{self.recipient.pk} # New caretaker")
        self.confirm("/finish")
        record.refresh_from_db()
        self.assertEqual(record.steward_id, self.recipient.pk)

    def test_retire_requires_explicit_child_frontier_and_restores_entire_group(self):
        parent = self.public_frontier()
        child = self.public_frontier(anchor=parent.rooms.get().room, name="Far trail")
        self.command(f"/retire {parent.pk} # Route review")
        self.assertIn("strand", self.command("/finish"))
        self.command(f"/frontiers {child.pk}")
        before = (ObjectDB.objects.count(), BuildAudit.objects.count())
        apply = self.confirmation("/finish")
        self.assertEqual((ObjectDB.objects.count(), BuildAudit.objects.count()), before)
        self.command(apply)
        self.assertEqual(Frontier.objects.filter(state="archived").count(), 2)
        preview = self.command(f"/frontierrestore {child.pk} # Reopen")
        self.assertIn(parent.name, preview)
        self.confirm(f"/frontierrestore {child.pk} # Reopen")
        self.assertEqual(Frontier.objects.filter(state="live").count(), 2)

    def test_retire_lists_required_homes_and_keeps_their_restore_separate(self):
        area = self.public_frontier()
        home_project = services.new_project(self.recipient, "Trail home")
        services.attach(self.recipient, home_project, area.rooms.get().room, "Trail home")
        home = self.approve(home_project, self.recipient)
        self.command(f"/retire {area.pk} # Route review")
        self.assertIn("/properties", self.command("/finish"))
        self.command(f"/properties {home.pk}")
        self.confirm("/finish")
        home.refresh_from_db()
        self.assertEqual(home.state, "archived")
        self.confirm(f"/frontierrestore {area.pk} # Reopen streets")
        home.refresh_from_db()
        self.assertEqual(home.state, "archived")
        self.confirm(f"/restore {home.pk} # Reopen home")
        home.refresh_from_db()
        self.assertEqual(home.state, "live")

    def test_policy_reasons_and_quiet_never_reassign_rights(self):
        self.command(f"/policy #{self.room1.pk}=CLOSED # Closed; x=y | ~ : # literal")
        self.assertTrue(self.room1.tags.has("closed", category="build_policy"))
        self.assertEqual(
            BuildAudit.objects.get(action="policy_set").data["reason"],
            "Closed; x=y | ~ : # literal",
        )
        self.command(f"/policy #{self.room1.pk}=RESET")
        self.assertFalse(self.room1.tags.get(category="build_policy"))
        property = self.approve()
        self.command("/quiet")
        property.refresh_from_db()
        self.assertEqual((property.state, property.owner_id), ("live", self.char2.pk))
        if not apps.is_installed("evennia_regions"):
            self.assertIn("unavailable", self.command("/region 1=closed"))

    def test_old_staff_forms_and_stacked_or_ambiguous_switches_are_refused(self):
        before = BuildAudit.objects.count()
        for args in (
            "/approve/approve 1 # bad",
            "/ar 1",
            "/unknown 1",
            "/policy 1 2=closed",
            "/transfer 1 2 3=reason",
        ):
            self.command(args)
        for args in (
            "/review 1 1 approved=reason",
            "/archive/children 1=reason",
            "/policy 1=closed",
            "/quiet",
        ):
            self.command(args, cls=CmdBuild)
        self.assertEqual(BuildAudit.objects.count(), before)
        self.assertFalse(self.char1.attributes.has(DRAFT_KEY))
        self.assertIn("No Building submissions", self.command("/LI"))

    def test_queue_excludes_withdrawn_revisions_after_resubmission(self):
        previous = self.submit()
        services.withdraw(
            self.char2, previous, expected_revision=previous.revision, reason="Correct it"
        )
        current = self.submit()
        self.assertEqual(self.command(), f"{current.pk}: The Bakery; revision {current.revision}")
        self.assertNotEqual(previous.pk, current.pk)

    def test_jobs_review_permission_remains_authoritative(self):
        if not apps.is_installed("evennia_jobs"):
            self.skipTest("Jobs intentionally absent")
        from evennia_jobs.models import RequestDecision, RequestSubmission

        submission = self.submit()
        self.assertTrue(RequestSubmission.objects.filter(pk=submission.jobs_submission_id).exists())
        self.account2.permissions.add("Builder")
        apply = self.confirmation(f"/approve {submission.pk} # Ready", self.char2)
        with override_settings(JOBS_STAFF_LOCK="cmd:perm(Admin)"):
            self.assertIn("Jobs staff", self.command(apply, self.char2))
        self.assertFalse(RequestDecision.objects.exists())
        self.assertFalse(BuildReview.objects.exists())
        self.assertFalse(Property.objects.exists())
        self.command(apply, self.char2)
        self.assertTrue(
            RequestDecision.objects.filter(
                submission_id=submission.jobs_submission_id, outcome="approved"
            ).exists()
        )
        self.assertTrue(Property.objects.exists())

    @override_settings(RP_ECONOMY_REVEALED=True)
    def test_shop_transfer_requires_explicit_stock_and_rechecks_reserved_merchandise(self):
        if not apps.is_installed("evennia_economy"):
            self.skipTest("Economy intentionally absent")
        from evennia_economy import stalls
        from evennia_economy.models import Storefront

        self.project.refresh_from_db()
        services.edit_project(self.char2, self.project, purpose="shop")
        property = self.approve()
        store = Storefront.objects.get(property_id=property.pk)
        self.char2.location = store.room
        self.obj1.location = self.char2
        with self.captureOnCommitCallbacks(execute=True):
            listing = stalls.list_stock(
                self.char2,
                store.pk,
                [{"kind": "item", "key": str(self.obj1.pk), "quantity": 1}],
                10,
            )
        self.command(f"/transfer {property.pk}=#{self.recipient.pk} # Shop handover")
        self.assertIn("/stock", self.command("/finish"))
        self.assertIn("Shop handover", self.command("/draft"))
        self.command("/stock RETURN")
        apply = self.confirmation("/finish")
        listing.price = 12
        listing.save(update_fields=["price"])
        self.assertIn("changed", self.command(apply))
        self.confirm("/finish")
        property.refresh_from_db()
        store.refresh_from_db()
        listing.refresh_from_db()
        self.assertEqual(
            (property.owner_id, store.owner_id), (self.recipient.pk, self.recipient.pk)
        )
        self.assertEqual(listing.status, "returned")
        self.assertEqual(self.obj1.location, self.char2)

    @override_settings(RP_ECONOMY_REVEALED=True)
    def test_stock_transfer_retains_active_listing_under_the_new_owner(self):
        if not apps.is_installed("evennia_economy"):
            self.skipTest("Economy intentionally absent")
        from evennia_economy import stalls
        from evennia_economy.models import Storefront

        self.project.refresh_from_db()
        services.edit_project(self.char2, self.project, purpose="shop")
        property = self.approve()
        store = Storefront.objects.get(property_id=property.pk)
        self.char2.location = store.room
        self.obj1.location = self.char2
        with self.captureOnCommitCallbacks(execute=True):
            listing = stalls.list_stock(
                self.char2,
                store.pk,
                [{"kind": "item", "key": str(self.obj1.pk), "quantity": 1}],
                10,
            )
        self.command(f"/transfer {property.pk}=#{self.recipient.pk} # Shop handover")
        self.command("/stock transfer")
        self.confirm("/finish")
        listing.refresh_from_db()
        store.refresh_from_db()
        self.assertEqual((store.owner_id, listing.status), (self.recipient.pk, "active"))
        self.assertEqual(self.obj1.location, store.holding)

    def test_replacement_retirement_preview_has_no_exit_or_signal_side_effects(self):
        from . import signals

        area = self.public_frontier()
        destination = self.room2
        destination.db.room_type = "ic"
        destination.db.allow_teleport = "public"
        if apps.is_installed("evennia_maps"):
            from evennia_maps.models import RoomTile
            from evennia_maps.placement import place_tile

            RoomTile.objects.filter(room=destination).delete()
            place_tile(destination, self.plane, 1, 1, actor=self.char1)
        street = area.rooms.get().room
        # A second public root linked through this frontier must stay connected.
        services._exit(street, destination, outward=True, aliases=["north", "n"])
        services._exit(destination, street, outward=True, aliases=["south", "s"])
        self.command(f"/retire {area.pk} # Reviewed bypass")
        self.assertIn("strand", self.command("/finish"))
        self.command(f"/replacement #{self.room1.pk}/northeast=#{destination.pk}")
        self.command(f"/unreplace #{self.room1.pk}/ne")
        self.assertIn("strand", self.command("/finish"))
        self.command(f"/replacement #{self.room1.pk}/ne=#{destination.pk}")
        before = (ObjectDB.objects.count(), BuildAudit.objects.count())
        with patch.object(
            signals.frontier_changed, "send_robust", wraps=signals.frontier_changed.send_robust
        ) as sent:
            apply = self.confirmation("/finish")
            sent.assert_not_called()
        self.assertEqual((ObjectDB.objects.count(), BuildAudit.objects.count()), before)
        self.command(apply)
        area.refresh_from_db()
        self.assertEqual(area.state, "archived")
        self.assertEqual(area.connections.filter(replacement=True).count(), 2)
        self.assertTrue(
            ObjectDB.objects.filter(db_location=self.room1, db_destination=destination).exists()
        )

    def test_region_policy_uses_the_real_optional_partner(self):
        if not apps.is_installed("evennia_regions"):
            self.skipTest("Regions intentionally absent")
        from evennia_regions.models import Region

        from .models import RegionBuildPolicy

        region = Region.objects.create(name="Staff District")
        self.command(f"/region {region.pk}=COMMERCIAL # Shop district")
        self.assertEqual(RegionBuildPolicy.objects.get(region_id=region.pk).policy, "commercial")
        self.command(f"/region {region.pk}=reset")
        self.assertFalse(RegionBuildPolicy.objects.exists())
