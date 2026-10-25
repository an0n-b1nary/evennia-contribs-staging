# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Current domain state bound into staff confirmation tokens, without preview writes."""

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db.models import Q
from evennia.objects.models import ObjectDB

from . import attachments, frontier_lifecycle, services
from .models import (
    AttachmentAgreement,
    Frontier,
    FrontierRoom,
    Property,
    RegionBuildPolicy,
    RoomOverride,
)


def rows(query, *fields):
    """Read deterministic primitive rows for exact-state comparison."""
    return list(query.order_by("pk").values(*fields))


def room_state(room):
    """Read physical identity and host-controlled room conditions from SQL."""
    data = (
        ObjectDB.objects.filter(pk=room.pk)
        .values(
            "id",
            "db_key",
            "db_location_id",
            "db_destination_id",
            "db_lock_storage",
        )
        .get()
    )
    data["description"] = services._read_attr(room, "desc", "")
    data["room_type"] = services._read_attr(room, "room_type", "ic")
    data["teleport"] = services._read_attr(room, "allow_teleport")
    data["terrain"] = sorted(services._read_attr(room, "terrain_tags", []) or [])
    data["policy"] = sorted(
        room.db_tags.filter(
            db_category="build_policy",
            db_tagtype__isnull=True,
        ).values_list("db_key", flat=True)
    )
    data["exits"] = [
        services._exit_data(exit)
        for exit in ObjectDB.objects.filter(
            db_location=room,
            db_destination__isnull=False,
        ).order_by("pk")
    ]
    if apps.is_installed("evennia_maps"):
        data["tiles"] = rows(
            apps.get_model("evennia_maps", "RoomTile").objects.filter(room=room),
            "id",
            "plane_id",
            "x",
            "y",
            "pinned",
            "plane__is_archived",
            "plane__zstack",
            "plane__elevation",
        )
    if apps.is_installed("evennia_regions"):
        data["regions"] = rows(
            apps.get_model("evennia_regions", "RegionMembership").objects.filter(room=room),
            "id",
            "region_id",
            "is_primary",
            "region__is_archived",
        )
        data["regional_policies"] = rows(
            RegionBuildPolicy.objects.filter(
                region_id__in=[row["region_id"] for row in data["regions"]]
            ),
            "region_id",
            "policy",
        )
    return data


def property_state(property, *, occupants=False):
    """Bind ownership, boundaries, rights, passage, stock and preserved identities."""
    data = (
        Property.objects.filter(pk=property.pk)
        .values(
            "id",
            "name",
            "owner_id",
            "state",
            "locked",
            "anchor_id",
            "entrance_id",
            "departure_id",
            "promotion_id",
            "part_id",
            "provenance",
            "archive_data",
        )
        .get()
    )
    data["rooms"] = rows(property.rooms.all(), "id", "object_id", "room_id", "owner_id")
    data["room_state"] = [
        room_state(row.room)
        for row in property.rooms.select_related("room").order_by("pk")
        if row.room
    ]
    data["boundaries"] = [
        services._exit_data(exit) for exit in (property.entrance, property.departure) if exit
    ]
    data["anchor"] = room_state(property.anchor) if property.anchor else None
    data["residents"] = rows(property.residents.all(), "id", "character_id", "can_install")
    data["invitations"] = rows(
        property.invitations.all(), "id", "character_id", "state", "entry", "maps"
    )
    data["overrides"] = rows(
        RoomOverride.objects.filter(ownership__property=property),
        "id",
        "ownership_id",
        "allowed_character_ids",
    )
    data["agreements"] = rows(
        AttachmentAgreement.objects.filter(Q(parent=property) | Q(child=property)),
        "id",
        "parent_id",
        "child_id",
        "route",
        "parent__owner_id",
        "child__owner_id",
        "parent__state",
        "child__state",
    )
    data["last_audit"] = property.audit.order_by("-pk").values_list("pk", flat=True).first()
    if occupants:
        data["contents"] = rows(
            ObjectDB.objects.filter(db_location_id__in=property.rooms.values("object_id")),
            "id",
            "db_key",
            "db_location_id",
            "db_typeclass_path",
        )
    if apps.is_installed("evennia_economy"):
        Store = apps.get_model("evennia_economy", "Storefront")
        stores = Store.objects.filter(property_id=property.pk)
        data["shops"] = rows(stores, "id", "owner_id", "room_id", "holding_id", "status")
        data["stock"] = rows(
            apps.get_model("evennia_economy", "Listing").objects.filter(storefront__in=stores),
            "id",
            "storefront_id",
            "assets",
            "price",
            "status",
            "buyer_id",
        )
    return data


def archive_group(property, *, include_children):
    """Identify the complete property group and refuse implicit apartment archival."""
    ids = {property.pk}
    children = set(
        Property.objects.filter(
            anchor_id__in=property.rooms.values("object_id"),
            state="live",
        )
        .exclude(pk=property.pk)
        .values_list("pk", flat=True)
    )
    if children and not include_children:
        raise ValidationError(
            "Active apartments are affected. Explicitly set +buildadmin/children yes, or arrange replacement passage."
        )
    ids |= children if include_children else set()
    attachments.lock_properties(ids)
    group = list(Property.objects.filter(pk__in=ids).order_by("pk"))
    if any(row.state != "live" for row in group):
        raise ValidationError("Choose live properties for archival.")
    child_rooms = Property.objects.filter(pk__in=children).values_list(
        "rooms__object_id", flat=True
    )
    if (
        Property.objects.filter(anchor_id__in=child_rooms, state="live")
        .exclude(pk__in=ids)
        .exists()
    ):
        raise ValidationError("Archive deeper legacy properties separately first.")
    return group


def frontier_state(frontier, *, occupants=False):
    """Bind a frontier's preserved geometry, stewards and current room state."""
    data = (
        Frontier.objects.filter(pk=frontier.pk).values("id", "name", "state", "archive_data").get()
    )
    data["rooms"] = [
        {
            "id": row.pk,
            "object": row.object_id,
            "steward": row.steward_id,
            "assigned": row.assigned_at.isoformat(),
            "room": room_state(row.room) if row.room else None,
        }
        for row in frontier.rooms.select_related("room").order_by("pk")
    ]
    data["connections"] = [
        services._exit_data(row.exit)
        for row in frontier.connections.select_related("exit").order_by("pk")
        if row.exit
    ]
    data["last_audit"] = frontier.audit.order_by("-pk").values_list("pk", flat=True).first()
    if occupants:
        data["contents"] = rows(
            ObjectDB.objects.filter(db_location_id__in=frontier.rooms.values("object_id")),
            "id",
            "db_key",
            "db_location_id",
            "db_typeclass_path",
        )
    return data


def world_state():
    """Bind the topology whose connectivity a frontier operation must preserve."""
    nodes, roots = frontier_lifecycle._world()
    return {
        "nodes": sorted(nodes),
        "roots": sorted(roots),
        "edges": sorted(frontier_lifecycle._edges()),
        "exits": rows(
            ObjectDB.objects.filter(db_location_id__in=nodes, db_destination__isnull=False),
            "id",
            "db_location_id",
            "db_destination_id",
            "db_lock_storage",
        ),
    }


def retirement_state(plan):
    """Validate a complete retirement proposal using the domain's graph rules."""
    ids = {plan["target"], *plan["frontiers"]}
    group = list(Frontier.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    if len(group) != len(ids) or any(row.state != "live" for row in group):
        raise ValidationError("Select live frontier areas for coordinated retirement.")
    records = list(FrontierRoom.objects.filter(frontier_id__in=ids).select_related("room"))
    removed = {row.object_id for row in records}
    if not removed or any(not row.room_id for row in records):
        raise ValidationError("The frontier room set needs repair.")
    explicit = list(Property.objects.filter(pk__in=plan["properties"]).order_by("pk"))
    if len(explicit) != len(plan["properties"]):
        raise ValidationError("An affected property is no longer available.")
    property_ids = {row.pk for row in explicit}
    if (
        Property.objects.filter(state="live", anchor_id__in=removed)
        .exclude(pk__in=property_ids)
        .exists()
    ):
        raise ValidationError(
            "Retirement would strand active homes. Add them with +buildadmin/properties."
        )
    all_properties = {}
    for property in explicit:
        for row in archive_group(property, include_children=True):
            all_properties[row.pk] = row
    nodes, roots = frontier_lifecycle._world()
    edges = frontier_lifecycle._edges()
    after_edges = list(edges)
    ports = set()
    endpoints = {}
    from .frontier import direction, reverse

    for proposal in plan["replacements"]:
        source, target, name = frontier_lifecycle.replacement_endpoints(proposal, removed)
        endpoints[source.pk] = source
        endpoints[target.pk] = target
        for room, label in ((source, name), (target, reverse(name))):
            port = (room.pk, tuple(direction(label)))
            if port in ports:
                raise ValidationError("Two replacement connections claim the same direction.")
            ports.add(port)
        after_edges.extend([(source.pk, target.pk), (target.pk, source.pk)])
    before = frontier_lifecycle._reachable(nodes, roots, edges)
    remaining = nodes - removed
    after = frontier_lifecycle._reachable(remaining, roots, after_edges)
    protected = set(
        FrontierRoom.objects.filter(frontier__state="live")
        .exclude(frontier_id__in=ids)
        .values_list("object_id", flat=True)
    )
    protected |= set(
        Property.objects.filter(state="live")
        .exclude(pk__in=property_ids)
        .values_list("anchor_id", flat=True)
    )
    if (protected & before) - after or not frontier_lifecycle._preserves_connections(
        nodes, remaining, edges, after_edges
    ):
        raise ValidationError(
            "Retirement would strand public places. Add replacement connections or the complete affected group."
        )
    return {
        "frontiers": [frontier_state(row, occupants=True) for row in group],
        "properties": [
            property_state(all_properties[pk], occupants=True) for pk in sorted(all_properties)
        ],
        "world": world_state(),
        "replacement_rooms": [room_state(endpoints[pk]) for pk in sorted(endpoints)],
    }


def submission_state(submission):
    """Lock and identify the current frozen revision and its optional Jobs binding."""
    project, submission = services._current(submission)
    data = {
        "id": submission.pk,
        "revision": submission.revision,
        "fingerprint": submission.fingerprint,
        "snapshot": submission.snapshot,
        "project": project.pk,
        "version": project.version,
        "owner": project.owner_id,
        "state": project.state,
        "agreements": rows(project.agreements.all(), "id", "state", "fingerprint"),
        "consents": rows(project.consents.all(), "id", "state", "fingerprint", "owner_id"),
    }
    if apps.is_installed("evennia_jobs") and submission.jobs_submission_id:
        model = apps.get_model("evennia_jobs", "RequestSubmission")
        linked = model.objects.filter(pk=submission.jobs_submission_id).first()
        data["jobs"] = (
            None
            if not linked
            else {
                "submission": linked.pk,
                "revision": linked.revision,
                "latest": linked.job.submissions.order_by("-revision")
                .values_list("pk", flat=True)
                .first(),
                "author": linked.job.author_id,
                "answers": linked.answers,
                "schema": linked.schema,
            }
        )
    return project, submission, data
