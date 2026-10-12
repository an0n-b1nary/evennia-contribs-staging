"""Explicit public-grid proposals, mixed settlements and individual stewardship."""

from collections import Counter

from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from evennia.objects.models import ObjectDB

from evennia_links.runtime import get
from evennia_links.transactions import atomic_objects

from .access import is_staff, ownership, require_revealed
from .attachments import begin_write
from .models import (
    BuildPart,
    DraftRoom,
    Frontier,
    FrontierConnection,
    FrontierRoom,
    GeometryApproval,
    Property,
    RoomOwnership,
    StewardQuietFlag,
)
from .policy import resolve_policy


def offsets():
    if apps.is_installed("evennia_maps"):
        from evennia_maps.direction import get_offsets

        return get_offsets()
    result = {}
    for name, short, value in (
        ("north", "n", (0, 1, 0, "planar")),
        ("south", "s", (0, -1, 0, "planar")),
        ("east", "e", (1, 0, 0, "planar")),
        ("west", "w", (-1, 0, 0, "planar")),
        ("northeast", "ne", (1, 1, 0, "planar")),
        ("northwest", "nw", (-1, 1, 0, "planar")),
        ("southeast", "se", (1, -1, 0, "planar")),
        ("southwest", "sw", (-1, -1, 0, "planar")),
        ("up", "u", (0, 0, 1, "vertical")),
        ("down", "d", (0, 0, -1, "vertical")),
    ):
        result[name] = result[short] = value
    return result


def direction(name, *, planar=False):
    value = offsets().get(name.strip().lower()) if isinstance(name, str) else None
    if not value or (planar and (value[2] or value[3] != "planar")):
        raise ValidationError(
            "Choose a compass direction" + (" on the same floor." if planar else ".")
        )
    return value


def reverse(name):
    value = direction(name)
    candidates = [
        key
        for key, offset in offsets().items()
        if tuple(offset[:3]) == tuple(-v for v in value[:3])
    ]
    if not candidates:
        raise ValidationError("This direction has no configured reverse.")
    return max(sorted(candidates), key=len)


def public_room(room):
    from .services import _read_attr

    if (
        not room
        or not ObjectDB.objects.filter(
            pk=room.pk, db_location__isnull=True, db_destination__isnull=True
        ).exists()
        or not room.is_typeclass("evennia.objects.objects.DefaultRoom", exact=False)
        or ownership(room)
        or _read_attr(room, "room_type", "ic") != "ic"
        or _read_attr(room, "allow_teleport") in {"private", "secret"}
        or DraftRoom.objects.filter(
            room=room, project__state__in=["draft", "submitted", "discarded"]
        ).exists()
        or FrontierRoom.objects.filter(room=room).exclude(frontier__state="live").exists()
    ):
        raise ValidationError("Grid connections require an available public world room.")
    if resolve_policy(room) == "closed":
        raise ValidationError("The current grid attachment policy is closed.")
    return room


def _free(room, name):
    from .services import _exit_data

    wanted = direction(name)
    for exit in ObjectDB.objects.filter(db_location=room, db_destination__isnull=False):
        data = _exit_data(exit)
        if any(
            offsets().get(value.casefold()) == wanted for value in [data["name"], *data["aliases"]]
        ):
            raise ValidationError(f"The {name} direction at room #{room.pk} is occupied.")


def attach_frontier(actor, project, anchor, name):
    from .services import _text, _touch, audit

    public_room(anchor)
    direction(name, planar=True)
    project.anchor = anchor
    project.entrance_name = _text(name, 100).lower()
    project.passage = []
    _touch(project)
    project.save(update_fields=["anchor", "entrance_name", "passage"])
    audit(actor, "frontier_attached", project=project, anchor=anchor.pk, direction=name)
    return project


@atomic_objects
def propose_connection(
    actor, project, source, target, name, *, expected_version=None, remove=False
):
    from .services import _project, _touch, audit

    begin_write()
    project = _project(project, actor, editable=True, expected_version=expected_version)
    if project.kind != "frontier":
        raise ValidationError("Additional grid connections belong to frontier projects.")
    source = project.rooms.get(pk=source.pk, part__isnull=True)
    value = direction(name)
    if not remove:
        public_room(target)
    rows = [
        row
        for row in project.connections
        if not (row["source"] == source.object_id and direction(row["direction"]) == value)
    ]
    if not remove:
        rows.append(
            {"source": source.object_id, "target": target.pk, "direction": name.strip().lower()}
        )
    project.connections = sorted(rows, key=lambda row: (row["source"], row["direction"]))
    _touch(project)
    project.save(update_fields=["connections"])
    audit(actor, "grid_connection_proposed", project=project, connections=project.connections)
    return project


@atomic_objects
def add_interior(
    actor, project, anchor, name, *, owner, entrance_name, purpose="home", expected_version=None
):
    from .services import _character, _make_room, _project, _quota, _text, _touch, audit

    begin_write()
    project = _project(project, actor, editable=True, expected_version=expected_version)
    if project.kind != "frontier" or purpose not in {"home", "shop"}:
        raise ValidationError("Mixed-project interiors attach to this project's frontier streets.")
    anchor = project.rooms.get(pk=anchor.pk, part__isnull=True)
    _character(owner)
    _quota(project.owner)
    entrance_name = _text(entrance_name, 100)
    if entrance_name.casefold() in offsets() or entrance_name.casefold() == "outside":
        raise ValidationError("Choose a named, non-compass interior entrance.")
    part = BuildPart.objects.create(
        project=project,
        anchor=anchor,
        name=_text(name),
        owner=owner,
        owner_name=owner.key,
        entrance_name=entrance_name,
        purpose=purpose,
    )
    _make_room(project, name=name, parent=anchor, part=part)
    _touch(project)
    audit(actor, "interior_added", project=project, part=part.pk, owner=owner.pk)
    return part


@atomic_objects
def assign_owner(actor, project, owner, *, part=None, expected_version=None):
    from .services import _character, _project, _touch, audit

    begin_write()
    project = _project(project, actor, editable=True, expected_version=expected_version)
    _character(owner)
    if part is None:
        if project.kind != "interior":
            raise ValidationError("Frontier rooms have stewards; select an interior boundary.")
        project.proposed_owner = owner
        project.save(update_fields=["proposed_owner"])
    else:
        part = project.parts.get(pk=part.pk)
        part.owner, part.owner_name = owner, owner.key
        part.save(update_fields=["owner", "owner_name"])
    _touch(project)
    audit(
        actor, "ownership_proposed", project=project, part=part.pk if part else None, owner=owner.pk
    )
    return project


def transplant(project):
    if not apps.is_installed("evennia_maps"):
        return None
    from evennia_maps.transplant import plan_transplant

    return plan_transplant(
        [row.room for row in project.rooms.filter(part__isnull=True).select_related("room")],
        entry_room=project.rooms.get(entry=True).room,
        anchor_room=project.anchor,
        direction_name=project.entrance_name,
    )


def check_frontier(project):
    from .services import _exit_data

    targets = {project.anchor_id, *(row["target"] for row in project.connections)}
    list(ObjectDB.objects.select_for_update().filter(pk__in=targets).order_by("pk"))
    public_room(project.anchor)
    direction(project.entrance_name, planar=True)
    rows = {row.object_id: row for row in project.rooms.filter(part__isnull=True)}
    for door in project.doors.select_related("source", "target", "exit"):
        if door.source.part_id != door.target.part_id:
            raise ValidationError("A draft door crosses independent spaces.")
        if not door.source.part_id:
            offset = direction(_exit_data(door.exit)["name"])
            if (door.target.x, door.target.y, door.target.floor) != (
                door.source.x + offset[0],
                door.source.y + offset[1],
                door.source.floor + offset[2],
            ):
                raise ValidationError("A frontier compass exit disagrees with draft coordinates.")
    plan = transplant(project)
    if plan and plan.conflicts:
        raise ValidationError(list(plan.conflicts))
    entry = project.rooms.get(entry=True)
    connections = [
        {
            "source": entry.object_id,
            "target": project.anchor_id,
            "direction": reverse(project.entrance_name),
        },
        *project.connections,
    ]
    claimed = set()
    moves = {move.room.pk: move for move in plan.moves} if plan else {}
    for connection in connections:
        source = rows.get(connection["source"])
        if source is None:
            raise ValidationError("A grid connection escaped the proposed frontier room set.")
        target = public_room(ObjectDB.objects.filter(pk=connection["target"]).first())
        name = connection["direction"]
        offset = direction(name)
        _free(source.room, name)
        _free(target, reverse(name))
        for port in (
            (source.object_id, tuple(offset)),
            (target.pk, tuple(direction(reverse(name)))),
        ):
            if port in claimed:
                raise ValidationError("Two proposed connections claim the same direction.")
            claimed.add(port)
        if plan:
            from evennia_maps.models import RoomTile
            from evennia_maps.placement import plane_key

            tile = RoomTile.objects.select_related("plane").filter(room=target).first()
            move = moves[source.object_id]
            if not tile or (tile.x, tile.y, tile.plane.elevation) != (
                move.x + offset[0],
                move.y + offset[1],
                move.plane.elevation + offset[2],
            ):
                raise ValidationError("An explicit grid connection does not align with its target.")
            if plane_key(tile.plane) != plane_key(move.plane) and not (
                tile.plane.zstack and tile.plane.zstack == move.plane.zstack
            ):
                raise ValidationError("Grid connections cannot jump between unrelated map stacks.")
    part_ports = set()
    for part in project.parts.select_related("anchor", "entry", "owner"):
        if (
            not part.owner_id
            or not part.entry_id
            or part.anchor.part_id
            or part.anchor.project_id != project.pk
        ):
            raise ValidationError("An interior boundary has lost its owner, entrance or street.")
        key = (part.anchor.room_id, part.entrance_name.casefold())
        if key in part_ports or part.entrance_name.casefold() in offsets():
            raise ValidationError("Interior entrance names must be distinct and non-compass.")
        part_ports.add(key)
        for exit in ObjectDB.objects.filter(
            db_location_id=part.anchor.room_id, db_destination__isnull=False
        ):
            data = _exit_data(exit)
            if part.entrance_name.casefold() in {
                data["name"].casefold(),
                *(name.casefold() for name in data["aliases"]),
            }:
                raise ValidationError("An interior entrance name is occupied.")
        if (
            part.rooms.filter(parent__part=part).exists()
            and not part.rooms.filter(room=part.entry).exists()
        ):
            raise ValidationError("An interior entry escaped its boundary.")
    additions = Counter()
    for connection in connections:
        additions.update((connection["source"], connection["target"]))
    for part in project.parts.all():
        additions.update((part.anchor.room_id, part.entry_id))
    warnings = []
    for room_id, added in sorted(additions.items()):
        count = (
            ObjectDB.objects.filter(db_location_id=room_id, db_destination__isnull=False).count()
            + added
        )
        if count > get("BUILDING_DOOR_LIMIT"):
            if get("BUILDING_DOOR_LIMIT_HARD"):
                raise ValidationError("A proposed frontier connection exceeds the hard door limit.")
            warnings.append(f"Room #{room_id} would exceed the recommended door count ({count}).")
    return {
        "geometry": plan.fingerprint if plan else "manual_staff_review_required",
        "adjacency": [[row.room_id, row.neighbor_room_id] for row in plan.adjacency]
        if plan
        else [],
        "connections": connections,
        "frontier_warnings": warnings,
    }


def extend_snapshot(project, candidate):
    candidate["kind"] = "frontier"
    candidate["parts"] = [
        {
            "id": part.pk,
            "name": part.name,
            "owner": part.owner_id,
            "anchor": part.anchor.room_id,
            "entry": part.entry_id,
            "entrance": part.entrance_name,
            "purpose": part.purpose,
            "rooms": list(part.rooms.order_by("pk").values_list("object_id", flat=True)),
        }
        for part in project.parts.select_related("anchor").order_by("pk")
    ]
    parts = {row.object_id: row.part_id for row in project.rooms.all()}
    for room in candidate["rooms"]:
        room["part"] = parts[room["id"]]
    candidate["connections"] = project.connections
    candidate["connection_targets"] = []
    from .services import _exit_data, _read_attr

    for pk in sorted({project.anchor_id, *(row["target"] for row in project.connections)}):
        room = ObjectDB.objects.get(pk=pk)
        candidate["connection_targets"].append(
            {
                "id": pk,
                "policy": resolve_policy(room),
                "terrain": sorted(_read_attr(room, "terrain_tags", []) or []),
                "exits": [
                    _exit_data(exit)
                    for exit in ObjectDB.objects.filter(
                        db_location=room, db_destination__isnull=False
                    ).order_by("pk")
                ],
            }
        )


@atomic_objects
def approve_geometry(actor, submission, *, expected_revision, reason):
    from .services import _current, _text, audit

    begin_write()
    require_revealed(actor)
    if not is_staff(actor):
        raise PermissionDenied("Only staff can certify manual geometry review.")
    project, submission = _current(submission)
    if project.kind != "frontier" or submission.revision != expected_revision:
        raise ValidationError("Select the current frontier submission.")
    receipt, _ = GeometryApproval.objects.get_or_create(
        submission=submission,
        defaults={
            "actor": actor,
            "fingerprint": submission.fingerprint,
            "reason": _text(reason, 10000),
        },
    )
    audit(actor, "geometry_reviewed", project=project, submission=submission.pk, reason=reason)
    return receipt


def _finish_room(room, *, actor, terrain, region_id, public=False):
    from .services import _flags

    _flags(room, False, frontier=public)
    room.attributes.add("terrain_tags", set(terrain))
    if apps.is_installed("evennia_regions") and region_id:
        from evennia_regions.models import RegionMembership

        RegionMembership.objects.create(
            region_id=region_id,
            room=room,
            room_name=room.key,
            is_primary=True,
            created_by=actor,
            created_by_name=actor.key,
        )
    if apps.is_installed("evennia_maps"):
        from evennia_maps.models import RoomTile
        from evennia_maps.terrain import resolve_terrain

        RoomTile.objects.filter(room=room).update(terrain=resolve_terrain(room), room_name=room.key)


def promote_frontier(submission, actor, project, candidate, terrain, region_id):
    from . import signals
    from .services import _exit, _exit_data, audit

    plan = transplant(project)
    if plan is None:
        if not GeometryApproval.objects.filter(
            submission=submission, fingerprint=submission.fingerprint
        ).exists():
            raise ValidationError(
                "Without Maps, staff must explicitly certify geometry before approval."
            )
    else:
        from evennia_maps.models import MapPlane, RoomTile
        from evennia_maps.transplant import apply_transplant

        if plan.fingerprint != candidate["report"]["geometry"]:
            raise ValidationError("The transplant changed; request a fresh revision.")
        source_planes = set(
            RoomTile.objects.filter(room_id__in=plan.room_ids).values_list("plane_id", flat=True)
        )
        apply_transplant(plan, actor=actor)
        for plane in MapPlane.objects.filter(pk__in=source_planes, visibility_room__isnull=False):
            if not RoomTile.objects.filter(plane=plane).exists():
                plane.archive(editor=actor)
    frontier = Frontier.objects.create(
        promotion=submission,
        name=project.name,
        provenance={
            "actor": actor.pk,
            "reclaimed_by": project.owner_id,
            "fingerprint": submission.fingerprint,
            "terrain": terrain,
            "region": region_id,
        },
    )
    for record in project.rooms.filter(part__isnull=True).select_related("room"):
        FrontierRoom.objects.create(
            frontier=frontier,
            room=record.room,
            object_id=record.object_id,
            steward=project.owner,
            steward_name=project.owner_name,
            assigned_at=timezone.now(),
        )
        _finish_room(record.room, actor=actor, terrain=terrain, region_id=region_id, public=True)
        record.room.attributes.add(
            "building_provenance",
            {
                "reclaimed_by": project.owner_name,
                "approved_by": actor.key,
                "promoted_at": frontier.created_at.isoformat(),
            },
        )
    for door in project.doors.filter(source__part__isnull=True).select_related("exit"):
        door.exit.locks.add("traverse:all()")
    for connection in candidate["report"]["connections"]:
        source = ObjectDB.objects.get(pk=connection["source"])
        target = ObjectDB.objects.get(pk=connection["target"])
        for start, end, name in (
            (source, target, connection["direction"]),
            (target, source, reverse(connection["direction"])),
        ):
            exit = _exit(start, end, name, outward=True)
            FrontierConnection.objects.create(
                frontier=frontier, exit=exit, object_id=exit.pk, data=_exit_data(exit)
            )
    for part in project.parts.select_related("anchor__room", "entry", "owner"):
        anchor = part.anchor.room
        property = Property.objects.create(
            promotion=submission,
            part=part,
            owner=part.owner,
            owner_name=part.owner_name,
            name=part.name,
            anchor=anchor,
            entrance=_exit(anchor, part.entry, part.entrance_name),
            departure=_exit(part.entry, anchor, "outside", outward=True),
            provenance={
                "submission": submission.pk,
                "fingerprint": submission.fingerprint,
                "actor": actor.pk,
                "terrain": terrain,
                "region": region_id,
                "purpose": part.purpose,
            },
        )
        for record in part.rooms.select_related("room"):
            RoomOwnership.objects.create(
                room=record.room, object_id=record.object_id, property=property, owner=part.owner
            )
            _finish_room(record.room, actor=actor, terrain=terrain, region_id=region_id)
        audit(actor, "promoted", project=project, property=property, submission=submission.pk)
        signals.property_promoted.send(
            sender=Property, property=property, submission=submission, actor=actor
        )
    project.agreements.filter(pk__in=candidate.get("project_agreements", [])).update(
        state="consumed"
    )
    audit(actor, "frontier_promoted", project=project, frontier=frontier, submission=submission.pk)
    transaction.on_commit(
        lambda: signals.frontier_changed.send_robust(
            sender=Frontier, frontier=frontier, actor=actor
        )
    )
    return frontier


@atomic_objects
def set_steward(actor, record, steward=None, *, expected_steward, reason):
    from .services import _character, _text, audit

    begin_write()
    require_revealed(actor)
    record = FrontierRoom.objects.select_for_update().get(pk=record.pk)
    if record.steward_id != expected_steward:
        raise ValidationError("The steward changed; reload before acting.")
    if not is_staff(actor) and (actor.pk != record.steward_id or steward is not None):
        raise PermissionDenied(
            "Stewards may relinquish; only staff may assign or record departures."
        )
    if steward is not None:
        _character(steward)
    previous = record.steward_id
    record.steward, record.steward_name, record.assigned_at = (
        steward,
        steward.key if steward else "",
        timezone.now(),
    )
    record.save(update_fields=["steward", "steward_name", "assigned_at"])
    StewardQuietFlag.objects.filter(room=record, resolved_at__isnull=True).update(
        resolved_at=timezone.now()
    )
    audit(
        actor,
        "steward_assigned" if steward else "steward_relinquished",
        frontier=record.frontier,
        room=record.object_id,
        previous=previous,
        steward=getattr(steward, "pk", None),
        reason=_text(reason, 10000),
    )
    return record


@atomic_objects
def edit_room(actor, room, *, description=None, mood=None):
    from .services import _text, audit

    begin_write()
    require_revealed(actor)
    record = FrontierRoom.objects.select_related("frontier").get(room=room)
    if record.frontier.state != "live" or not (is_staff(actor) or actor.pk == record.steward_id):
        raise PermissionDenied("Only the steward or staff may maintain this public room.")
    if description is not None:
        room.db.desc = _text(description, 50000)
    if mood is not None:
        room.attributes.add("room_mood", _text(mood, 200))
        room.attributes.add("room_mood_setter", actor.key)
    audit(
        actor,
        "frontier_room_edited",
        frontier=record.frontier,
        room=room.pk,
        description=description,
        mood=mood,
    )
    return record
