"""Persistent generic interior demonstrations, safe across sandbox reseeds."""

from django.conf import settings
from django.db import transaction
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object
from evennia_building import attachments, services
from evennia_building.models import BuildProject, Property, RegionBuildPolicy

from evennia_regions.models import Region, RegionMembership

TAG = "building_demo"


def _object(key, typeclass):
    obj = ObjectDB.objects.filter(
        db_key=key, db_tags__db_key=TAG, db_tags__db_category="sandbox"
    ).first()
    return obj or create_object(typeclass, key=key, tags=[(TAG, "sandbox")])


@transaction.atomic
def seed(outer):
    owner = _object("Demo Homeowner", "typeclasses.characters.Character")
    resident = _object("Demo Resident", "typeclasses.characters.Character")
    reviewer = _object("Demo Building Reviewer", "typeclasses.characters.Character")
    reviewer.permissions.add("Builder")
    tenant = _object("Demo Apartment Owner", "typeclasses.characters.Character")
    guest = _object("Demo Apartment Guest", "typeclasses.characters.Character")
    court = _object("Residential Court", "typeclasses.rooms.Room")
    court.db.room_type = "ic"
    court.db.allow_teleport = "public"
    court.db.desc = "Named home entrances line this quiet court. The sample home starts unlocked; its floor plan remains private."
    court.terrain_tags = {"urban"}
    region, _ = Region.objects.get_or_create(name="Residential Demonstration")
    RegionMembership.objects.get_or_create(
        region=region, room=court, defaults={"room_name": court.key, "is_primary": True}
    )
    RegionBuildPolicy.objects.update_or_create(
        region_id=region.pk, defaults={"policy": "residential"}
    )
    for source, target, name in (
        (outer, court, "residential court"),
        (court, outer, "public square"),
    ):
        if not ObjectDB.objects.filter(db_location=source, db_destination=target).exists():
            create_object("typeclasses.exits.Exit", key=name, location=source, destination=target)
    ack = getattr(
        settings,
        "BUILDING_REUSE_ACKNOWLEDGEMENT",
        "I acknowledge that this submitted content may be reused by this game.",
    )
    if not BuildProject.objects.filter(owner=owner, name="Sample Home").exists():
        project = services.new_project(owner, "Sample Home")
        entry = project.rooms.get(entry=True)
        services.edit_project(
            owner,
            project,
            room=entry,
            description="A welcoming common room. The door is unlocked; residents can inspect the common floor.",
        )
        upper = services.dig(owner, project, entry, "Restricted Bedroom", door="upstairs", floor=1)
        services.edit_project(
            owner,
            project,
            room=upper,
            description="An owner-only bedroom on a private upper floor.",
        )
        services.attach(owner, project, court, "sample home")
        project.refresh_from_db()
        submission = services.submit(
            owner, project, expected_version=project.version, acknowledgement=ack
        )
        services.review(
            reviewer,
            submission,
            expected_revision=submission.revision,
            outcome="approved",
            reason="Generic reference home approved.",
        )
        property = submission.property
        services.set_resident(owner, property, resident)
        services.set_override(owner, upper.room, [])
    if not BuildProject.objects.filter(owner=owner, name="Two-floor Draft").exists():
        project = services.new_project(owner, "Two-floor Draft")
        entry = project.rooms.get(entry=True)
        services.dig(owner, project, entry, "Draft Upper Floor", door="stairs", floor=1)
        services.attach(owner, project, court, "proposed studio")
    if not BuildProject.objects.filter(owner=owner, name="Revision Requested").exists():
        project = services.new_project(owner, "Revision Requested")
        services.attach(owner, project, court, "proposed reading room")
        project.refresh_from_db()
        submission = services.submit(
            owner, project, expected_version=project.version, acknowledgement=ack
        )
        services.review(
            reviewer,
            submission,
            expected_revision=1,
            outcome="changes_requested",
            reason="Add a room description before resubmitting.",
        )
    parent = Property.objects.get(promotion__project__owner=owner, name="Sample Home")
    if not BuildProject.objects.filter(owner=tenant, name="Sample Apartment").exists():
        project = services.new_project(tenant, "Sample Apartment")
        entry = project.rooms.get(entry=True)
        services.edit_project(
            tenant,
            project,
            room=entry,
            description="A separately owned apartment. Its owner admits guests through the agreed common room, while the parent's bedroom and floor plan remain private.",
        )
        anchor = parent.promotion.project.rooms.get(entry=True).room
        services.attach(tenant, project, anchor, "sample apartment")
        project.refresh_from_db()
        consent = attachments.request_consent(tenant, project, expected_version=project.version)
        attachments.answer_consent(owner, consent, action="grant", acknowledgement=consent.wording)
        submission = services.submit(
            tenant, project, expected_version=project.version, acknowledgement=ack
        )
        services.review(
            reviewer,
            submission,
            expected_revision=1,
            outcome="approved",
            reason="Separate ownership and exact shared passage approved.",
        )
        invitation = services.invite(tenant, submission.property, guest, entry=True, maps=False)
        services.answer_invitation(guest, invitation, accept=True)
    # Persistent generated demo geometry is seeded content, not hand-dug rooms.
    for project in BuildProject.objects.filter(owner__in=[owner, tenant]):
        for record in project.rooms.select_related("room"):
            if record.room:
                record.room.tags.add(TAG, category="sandbox")
    return {"building_projects": BuildProject.objects.filter(owner__in=[owner, tenant]).count()}
