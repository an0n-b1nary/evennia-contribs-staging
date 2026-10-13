"""All authoring and lifecycle mutations run here, under transaction locks.

Version compare-and-swap writes also protect backends without row locking.
Evennia Attributes and partner writes participate in the same DB transaction.
"""

import hashlib
import json

from django.apps import apps
from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_object

from evennia_links.runtime import get
from evennia_links.transactions import atomic_objects

from . import signals
from .access import is_staff, ownership, require_revealed
from .models import (
    BuildAudit,
    BuildProject,
    BuildReview,
    BuildSubmission,
    DraftDoor,
    DraftRoom,
    EnvironmentApproval,
    GuestInvitation,
    Property,
    Resident,
    RoomOverride,
    RoomOwnership,
)
from .policy import primary_region, resolve_policy


def audit(actor, action, *, project=None, property=None, frontier=None, **data):
    return BuildAudit.objects.create(
        actor=actor,
        actor_name=getattr(actor, "key", "Unknown"),
        action=action,
        project=project,
        property=property,
        frontier=frontier,
        data={"actor_id": getattr(actor, "pk", None), **data},
    )


def _text(value, maximum=255):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValidationError(f"Enter between 1 and {maximum} characters.")
    return value.strip()


def _character(character):
    if (
        not character
        or not character.pk
        or not character.is_typeclass("evennia.objects.objects.DefaultCharacter", exact=False)
        or not ObjectDB.objects.filter(pk=character.pk).exists()
    ):
        raise ValidationError("Choose an existing character.")
    return character


def _read_attr(room, key, default=None):
    from evennia.utils.dbserialize import from_pickle

    row = (
        room.db_attributes.filter(db_key=key, db_category__isnull=True)
        .values_list("db_value", flat=True)
        .first()
    )
    return from_pickle(row) if row is not None else default


def _project(project, actor, *, editable=False, expected_version=None, author=False):
    BuildProject.objects.filter(pk=project.pk).update(version=F("version"))
    require_revealed(actor)
    project = BuildProject.objects.select_for_update().get(pk=project.pk)
    from .collaboration import can_author

    if not project.owner_id or not (
        can_author(actor, project) if author else project.owner_id == actor.pk
    ):
        raise PermissionDenied("Only the project owner may change this draft.")
    if editable and project.state != "draft":
        raise ValidationError("Withdraw the submitted draft before editing it.")
    if expected_version is not None and project.version != expected_version:
        raise ValidationError("This project has changed; reload it first.")
    return project


def _touch(project):
    if not BuildProject.objects.filter(pk=project.pk, version=project.version).update(
        version=F("version") + 1
    ):
        raise ValidationError("This project has changed; reload it first.")
    project.version += 1
    project.agreements.filter(state="accepted").update(state="invalidated")
    for consent in project.consents.filter(state__in=["requested", "granted"]):
        consent.state = "invalidated"
        consent.save(update_fields=["state"])
        audit(project.owner, "consent_invalidated", project=project, consent=consent.pk)


def _quota(owner, *, project=False):
    if not owner or not owner.pk:
        raise PermissionDenied("An owning character is required.")
    # The first write serializes all quota-changing operations by one character.
    ObjectDB.objects.filter(pk=owner.pk).update(db_key=F("db_key"))
    ObjectDB.objects.select_for_update().get(pk=owner.pk)
    pending = BuildProject.objects.filter(owner=owner, state__in=["draft", "submitted"])
    if project and pending.count() >= get("BUILDING_PROJECT_LIMIT"):
        raise ValidationError("You have reached the open-project limit.")
    if DraftRoom.objects.filter(project__in=pending).count() >= get("BUILDING_ROOM_LIMIT"):
        raise ValidationError("You have reached the draft-room limit.")


def _flags(room, draft, *, frontier=False):
    room.attributes.add("room_type", "ooc" if draft else "ic")
    room.attributes.add(
        "allow_teleport", "secret" if draft else "public" if frontier else "private"
    )
    room.attributes.add("hangout_type", None)
    room.locks.add("control:false();edit:false();delete:false();teleport:building_entry()")


def _make_room(project, *, name, parent=None, floor=0, x=0, y=0, part=None):
    room = create_object(
        getattr(settings, "BASE_ROOM_TYPECLASS", "evennia.objects.objects.DefaultRoom"),
        key=_text(name),
    )
    _flags(room, True)
    record = DraftRoom.objects.create(
        project=project,
        room=room,
        object_id=room.pk,
        parent=parent,
        floor=floor,
        x=x,
        y=y,
        entry=parent is None,
        part=part,
        space=part.pk if part else 0,
    )
    if apps.is_installed("evennia_maps"):
        from evennia_maps.models import RoomTile
        from evennia_maps.placement import create_private_stack, place_tile, resolve_stacked_plane

        if parent is None or (part and not part.entry_id):
            create_private_stack(
                room,
                f"{part.name[:50]} (project {project.pk}, interior {part.pk})"
                if part
                else f"{project.name[:65]} (interior {project.pk})",
                actor=project.owner,
            )
        else:
            entry = (
                project.rooms.get(room_id=part.entry_id) if part else project.rooms.get(entry=True)
            )
            tile = RoomTile.objects.get(room=entry.room)
            plane = resolve_stacked_plane(tile.plane, floor - tile.plane.elevation)
            place_tile(room, plane, x, y, actor=project.owner)
    if part and not part.entry_id:
        part.entry = room
        part.save(update_fields=["entry"])
    return record


def _exit(source, target, name, *, outward=False):
    name = _text(name, 100)
    exits = ObjectDB.objects.filter(db_location=source, db_destination__isnull=False)
    if any(
        name.casefold()
        in {data["name"].casefold(), *(alias.casefold() for alias in data["aliases"])}
        for exit in exits
        for data in [_exit_data(exit)]
    ):
        raise ValidationError("That door name is already in use.")
    return create_object(
        getattr(settings, "BASE_EXIT_TYPECLASS", "evennia.objects.objects.DefaultExit"),
        key=name,
        location=source,
        destination=target,
        locks="traverse:all()" if outward else "traverse:building_entry()",
    )


def _exit_data(exit):
    actual = (
        ObjectDB.objects.filter(pk=exit.pk)
        .values("db_key", "db_location_id", "db_destination_id", "db_lock_storage")
        .get()
    )
    return {
        "id": exit.pk,
        "name": actual["db_key"],
        "source": actual["db_location_id"],
        "target": actual["db_destination_id"],
        "locks": actual["db_lock_storage"],
        "aliases": sorted(exit.db_tags.filter(db_tagtype="alias").values_list("db_key", flat=True)),
    }


def _door(project, source, target, name, *, outward=False):
    if (
        source.project_id != project.pk
        or target.project_id != project.pk
        or source.part_id != target.part_id
    ):
        raise ValidationError("Internal doors must stay inside one draft space.")
    if source.entry and _text(name, 100).casefold() == "outside":
        raise ValidationError("The entrance room reserves 'outside' for departure after approval.")
    exit = _exit(source.room, target.room, name, outward=outward)
    return DraftDoor.objects.create(
        project=project, source=source, target=target, exit=exit, object_id=exit.pk, outward=outward
    )


@atomic_objects
def new_project(actor, name, *, kind="interior", purpose="home"):
    _quota(actor, project=True)
    require_revealed(actor)
    if kind not in {"interior", "frontier"}:
        raise ValidationError("Choose interior or frontier.")
    if kind == "frontier":
        purpose = "public"
    if purpose not in {"home", "shop", "public"} or (purpose == "public" and kind != "frontier"):
        raise ValidationError("Choose home or shop.")
    project = BuildProject.objects.create(
        owner=actor, owner_name=actor.key, name=_text(name), purpose=purpose, kind=kind
    )
    _make_room(project, name=name)
    audit(actor, "created", project=project)
    return project


@atomic_objects
def dig(
    actor,
    project,
    source,
    name,
    *,
    door="inside",
    back="out",
    floor=0,
    x=0,
    y=0,
    expected_version=None,
):
    project = _project(
        project, actor, editable=True, expected_version=expected_version, author=True
    )
    _quota(project.owner)
    source = project.rooms.get(pk=source.pk)
    if not source.room_id:
        raise ValidationError("A draft room is missing; ask staff to repair it.")
    if project.rooms.filter(part=source.part, floor=floor, x=x, y=y).exists():
        raise ValidationError("That draft map cell is occupied.")
    _touch(project)
    room = _make_room(
        project, name=name, parent=source, floor=int(floor), x=int(x), y=int(y), part=source.part
    )
    _door(project, source, room, door)
    _door(project, room, source, back, outward=True)
    audit(actor, "dug", project=project, room=room.object_id)
    from .collaboration import note_contribution

    note_contribution(actor, project)
    return room


@atomic_objects
def add_door(actor, project, source, target, name, *, expected_version=None):
    project = _project(
        project, actor, editable=True, expected_version=expected_version, author=True
    )
    source = project.rooms.get(pk=source.pk)
    target = project.rooms.get(pk=target.pk)
    if source == target or not source.room_id or not target.room_id:
        raise ValidationError("Choose two existing rooms in this draft.")
    _touch(project)
    result = _door(project, source, target, name)
    audit(actor, "door", project=project, door=result.object_id)
    from .collaboration import note_contribution

    note_contribution(actor, project)
    return result


@atomic_objects
def edit_project(
    actor, project, *, name=None, purpose=None, room=None, description=None, expected_version=None
):
    project = _project(
        project, actor, editable=True, expected_version=expected_version, author=room is not None
    )
    _touch(project)
    if room is not None:
        record = project.rooms.get(pk=room.pk)
        if not record.room_id:
            raise ValidationError("That draft room is missing.")
        if name is not None:
            record.room.key = _text(name)
        if description is not None:
            record.room.db.desc = _text(description, 50000)
    else:
        if name is not None:
            project.name = _text(name)
        if purpose is not None:
            if purpose not in {"home", "shop"}:
                raise ValidationError("Choose home or shop.")
            project.purpose = purpose
        project.save(update_fields=["name", "purpose"])
    audit(
        actor,
        "edited",
        project=project,
        room=getattr(room, "object_id", None),
        name=name,
        description=description,
        purpose=purpose,
    )
    from .collaboration import note_contribution

    note_contribution(actor, project)
    return project


def _anchor(project):
    if not project.anchor_id:
        raise ValidationError("Choose a live attachment room first.")
    anchor = ObjectDB.objects.select_for_update().filter(pk=project.anchor_id).first()
    if (
        anchor is None
        or anchor.location
        or anchor.destination
        or not anchor.is_typeclass("evennia.objects.objects.DefaultRoom", exact=False)
    ):
        raise ValidationError("The attachment must be a live room.")
    draft = DraftRoom.objects.filter(object_id=anchor.pk).first()
    owner = ownership(anchor)
    from .models import FrontierRoom

    if (
        draft
        and not owner
        and not FrontierRoom.objects.filter(room=anchor, frontier__state="live").exists()
    ):
        raise ValidationError("A draft cannot be an attachment room.")
    if owner:
        if owner.property.state != "live" or not owner.owner_id:
            raise ValidationError("The attachment property is unavailable.")
        from .attachments import parent_for

        parent_for(project)
    if (
        _read_attr(anchor, "room_type", "ic") != "ic"
        or _read_attr(anchor, "allow_teleport") == "secret"
    ):
        raise ValidationError("This room is not available for player building.")
    # A shared attachment row is written before counting/naming doors, including on SQLite.
    ObjectDB.objects.filter(pk=anchor.pk).update(db_key=F("db_key"))
    return anchor


@atomic_objects
def attach(actor, project, anchor, entrance_name, *, expected_version=None, passage=None):
    project = _project(project, actor, editable=True, expected_version=expected_version)
    if project.kind == "frontier":
        from .frontier import attach_frontier

        return attach_frontier(actor, project, anchor, entrance_name)
    _touch(project)
    name = _text(entrance_name, 100)
    if name.casefold() in {
        "n",
        "s",
        "e",
        "w",
        "u",
        "d",
        "north",
        "south",
        "east",
        "west",
        "up",
        "down",
        "ne",
        "nw",
        "se",
        "sw",
        "northeast",
        "northwest",
        "southeast",
        "southwest",
    }:
        raise ValidationError("Choose a named, non-compass entrance.")
    project.anchor = anchor
    project.entrance_name = name
    _anchor(project)
    from .attachments import attachment_snapshot, default_route, parent_for, require_route_selection

    parent = parent_for(project)
    project.passage = (
        default_route(parent, anchor) if parent and passage is None else (passage or [])
    )
    attachment_snapshot(project)
    if parent:
        require_route_selection(actor, project.passage)
    project.save(update_fields=["anchor", "entrance_name", "passage"])
    audit(actor, "attached", project=project, anchor=anchor.pk, entrance=name)
    return project


def _environment(requested):
    if not isinstance(requested, dict) or set(requested) - {"terrain", "region"}:
        raise ValidationError("Request terrain and/or a primary region.")
    result = {}
    if "terrain" in requested:
        tags = requested["terrain"]
        if not isinstance(tags, list) or any(
            not isinstance(tag, str) or not tag.strip() or len(tag) > 100 for tag in tags
        ):
            raise ValidationError("Terrain must be a list of tag names.")
        result["terrain"] = sorted({tag.strip() for tag in tags})
    if "region" in requested:
        region_id = requested["region"]
        if not apps.is_installed("evennia_regions"):
            raise ValidationError("Requested regions are unavailable without Regions.")
        from evennia_regions.models import Region

        if region_id is not None and (
            type(region_id) is not int
            or not Region.objects.filter(pk=region_id, is_archived=False).exists()
        ):
            raise ValidationError("Choose an active region or explicitly request no region.")
        result["region"] = region_id
    return result


@atomic_objects
def request_environment(actor, project, requested, *, expected_version=None):
    project = _project(project, actor, editable=True, expected_version=expected_version)
    project.requested_environment = _environment(requested)
    _touch(project)
    project.save(update_fields=["requested_environment"])
    audit(actor, "environment_requested", project=project, requested=project.requested_environment)
    return project


@atomic_objects
def approve_environment(actor, submission, *, expected_revision, reason):
    require_revealed(actor)
    if not is_staff(actor):
        raise PermissionDenied("Only staff can approve an environment request.")
    project, submission = _current(submission)
    if submission.revision != expected_revision:
        raise ValidationError("The review revision has changed.")
    _environment(submission.snapshot["requested_environment"])
    approval, created = EnvironmentApproval.objects.get_or_create(
        submission=submission,
        defaults={
            "actor": actor,
            "actor_name": actor.key,
            "fingerprint": submission.fingerprint,
            "reason": _text(reason, 10000),
        },
    )
    if created:
        audit(
            actor, "environment_approved", project=project, submission=submission.pk, reason=reason
        )
    return approval


@atomic_objects
def check_project(project):
    anchor = _anchor(project)
    if set(_read_attr(anchor, "terrain_tags", []) or []) & set(
        getattr(settings, "BUILDING_STAFF_ONLY_TERRAINS", ())
    ):
        raise ValidationError(
            "This attachment has staff-only terrain; player interiors are unavailable here."
        )
    policy = resolve_policy(anchor)
    if policy == "closed":
        raise ValidationError("The current attachment policy is closed.")
    exits = list(ObjectDB.objects.filter(db_location=anchor, db_destination__isnull=False))
    if any(
        project.entrance_name.casefold()
        in {data["name"].casefold(), *(alias.casefold() for alias in data["aliases"])}
        for exit in exits
        for data in [_exit_data(exit)]
    ):
        raise ValidationError("The entrance name is already in use.")
    warnings = []
    if len(exits) + 1 > get("BUILDING_DOOR_LIMIT"):
        if get("BUILDING_DOOR_LIMIT_HARD"):
            raise ValidationError("The attachment room has reached its hard door limit.")
        warnings.append("The attachment exceeds the recommended door count.")
    if (policy == "residential" and project.purpose == "shop") or (
        policy == "commercial" and project.purpose == "home"
    ):
        warnings.append("The purpose differs from this room's preferred use.")
    if not project.owner_id:
        raise ValidationError("The proposed owner is missing.")
    rooms = list(project.rooms.select_related("room"))
    if (
        not rooms
        or sum(room.entry for room in rooms) != 1
        or any(not room.room_id for room in rooms)
    ):
        raise ValidationError("The generated room set is incomplete.")
    ids = {room.room_id for room in rooms}
    if (
        ObjectDB.objects.filter(pk__in=ids)
        .exclude(db_location__isnull=True, db_destination__isnull=True)
        .exists()
    ):
        raise ValidationError(
            "A draft room was moved or made into an exit; ask staff to repair it."
        )
    doors = list(project.doors.select_related("exit"))
    generated = {door.object_id for door in doors}
    entry_id = next(room.room_id for room in rooms if room.entry)
    if any(
        data["source"] == entry_id
        and "outside" in {data["name"].casefold(), *(alias.casefold() for alias in data["aliases"])}
        for door in doors
        if door.exit_id
        for data in [_exit_data(door.exit)]
    ):
        raise ValidationError("The entrance room's 'outside' door name is reserved for departure.")
    # Staff-created or redirected exits cannot escape the reviewed object set.
    if (
        set(
            ObjectDB.objects.filter(
                db_location_id__in=ids, db_destination__isnull=False
            ).values_list("pk", flat=True)
        )
        != generated
    ):
        raise ValidationError(
            "Draft exits differ from the generated set; ask staff to repair them."
        )
    for door in doors:
        actual = _exit_data(door.exit) if door.exit_id else {}
        if (
            not door.exit_id
            or actual["source"] != door.source.room_id
            or actual["target"] != door.target.room_id
        ):
            raise ValidationError("A generated door was removed or redirected.")
    for room in rooms:
        part_entry = bool(room.part_id and room.room_id == room.part.entry_id)
        if (
            not room.entry
            and not part_entry
            and (
                not room.parent_id
                or not any(
                    door.source_id == room.pk and door.target_id == room.parent_id and door.outward
                    for door in doors
                )
            )
        ):
            raise ValidationError("Every inner room needs a safe outward door.")
        route = set()
        current = room
        by_id = {record.pk: record for record in rooms}
        while not current.entry:
            if current.pk in route or current.parent_id not in by_id:
                raise ValidationError("The outward route must reach the entrance without cycles.")
            route.add(current.pk)
            current = by_id[current.parent_id]
    report = {"policy": policy, "doors": len(exits) + 1, "warnings": warnings}
    if project.kind == "frontier":
        from .frontier import check_frontier

        report.update(check_frontier(project))
        report["warnings"].extend(report.pop("frontier_warnings"))
    return report


@atomic_objects
def snapshot(project):
    report = check_project(project)
    anchor = project.anchor
    region = primary_region(anchor)
    rooms = []
    for record in project.rooms.select_related("room").order_by("pk"):
        room = record.room
        actual = ObjectDB.objects.filter(pk=room.pk).values("db_key", "db_lock_storage").get()
        data = {
            "id": room.pk,
            "name": actual["db_key"],
            "description": _read_attr(room, "desc", ""),
            "mood": _read_attr(room, "room_mood", ""),
            "mood_setter": _read_attr(room, "room_mood_setter"),
            "hangout": _read_attr(room, "hangout_type"),
            "aliases": sorted(
                room.db_tags.filter(db_tagtype="alias").values_list("db_key", flat=True)
            ),
            "floor": record.floor,
            "x": record.x,
            "y": record.y,
            "parent": record.parent_id,
            "entry": record.entry,
            "room_type": _read_attr(room, "room_type"),
            "teleport": _read_attr(room, "allow_teleport"),
            "locks": actual["db_lock_storage"],
        }
        if apps.is_installed("evennia_maps"):
            from evennia_maps.models import RoomTile

            tile = (
                RoomTile.objects.filter(room=room)
                .values(
                    "plane_id",
                    "plane__zstack",
                    "plane__name",
                    "plane__elevation",
                    "plane__visibility_room_id",
                    "x",
                    "y",
                )
                .first()
            )
            data["map"] = tile
        rooms.append(data)
    doors = [
        {
            **_exit_data(door.exit),
            "outward": door.outward,
        }
        for door in project.doors.select_related("exit").order_by("pk")
    ]
    candidate = {
        "project": project.pk,
        "version": project.version,
        "name": project.name,
        "purpose": project.purpose,
        "owner": project.owner_id,
        "anchor": project.anchor_id,
        "anchor_owner": getattr(ownership(anchor), "owner_id", None),
        "entrance": project.entrance_name,
        "terrain": sorted(_read_attr(anchor, "terrain_tags", []) or []),
        "region": region.pk if region else None,
        "requested_environment": _environment(project.requested_environment),
        "rooms": rooms,
        "doors": doors,
        "report": report,
    }
    from .attachments import attachment_snapshot

    attachment = attachment_snapshot(project)
    if attachment:
        candidate["attachment"] = attachment
    if project.kind == "frontier":
        from .frontier import extend_snapshot

        extend_snapshot(project, candidate)
    from .collaboration import extend_snapshot as collaboration_snapshot

    collaboration_snapshot(project, candidate)
    if project.proposed_owner_id:
        candidate["lead"] = project.owner_id
        candidate["owner"] = project.proposed_owner_id
    return candidate


def fingerprint(candidate):
    return hashlib.sha256(
        json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@atomic_objects
def submit(actor, project, *, expected_version, acknowledgement):
    project = _project(project, actor, editable=True, expected_version=expected_version)
    wording = getattr(
        settings,
        "BUILDING_REUSE_ACKNOWLEDGEMENT",
        "I acknowledge that this submitted content may be reused by this game.",
    )
    if acknowledgement != wording:
        raise ValidationError(
            "Read and acknowledge the current content reuse wording before submitting."
        )
    candidate = snapshot(project)
    from .collaboration import validate as validate_agreements

    agreement_ids = validate_agreements(project, candidate)
    from .attachments import validate_consent

    consent = validate_consent(project, candidate)
    if consent:
        candidate["consent"] = consent.pk
    if agreement_ids:
        candidate["project_agreements"] = agreement_ids
    candidate["acknowledgement"] = {
        "wording": wording,
        "version": getattr(settings, "BUILDING_REUSE_VERSION", "1"),
        "actor": actor.pk,
    }
    latest = project.submissions.order_by("-revision").first()
    submission = BuildSubmission.objects.create(
        project=project,
        revision=(latest.revision + 1 if latest else 1),
        snapshot=candidate,
        fingerprint=fingerprint(candidate),
    )
    # A state CAS prevents two current submissions even without row locks.
    if not BuildProject.objects.filter(
        pk=project.pk, state="draft", version=expected_version
    ).update(state="submitted"):
        raise ValidationError("This project has changed; reload it first.")
    if apps.is_installed("evennia_jobs"):
        from .jobs import create_request

        create_request(submission, actor, latest)
    audit(
        actor,
        "submitted",
        project=project,
        submission=submission.pk,
        fingerprint=submission.fingerprint,
    )
    return submission


def _current(submission):
    BuildProject.objects.filter(pk=submission.project_id).update(version=F("version"))
    project = BuildProject.objects.select_for_update().get(pk=submission.project_id)
    submission = BuildSubmission.objects.select_for_update().get(pk=submission.pk)
    if (
        project.submissions.order_by("-revision").first().pk != submission.pk
        or project.state != "submitted"
    ):
        raise ValidationError("This submission is no longer current. Review the latest proposal.")
    return project, submission


@atomic_objects
def withdraw(actor, submission, *, expected_revision, reason=""):
    BuildProject.objects.filter(pk=submission.project_id).update(version=F("version"))
    require_revealed(actor)
    submission = BuildSubmission.objects.get(pk=submission.pk)
    if submission.revision != expected_revision or submission.project.owner_id != actor.pk:
        raise PermissionDenied("Only the owner may withdraw this exact revision.")
    if apps.is_installed("evennia_jobs") and submission.jobs_submission_id:
        from evennia_jobs.models import RequestSubmission
        from evennia_jobs.review import withdraw_request

        linked = RequestSubmission.objects.filter(pk=submission.jobs_submission_id).first()
        if linked:
            return withdraw_request(
                job=linked.job, author=actor, expected_revision=linked.revision, reason=reason
            )
    return _record_review(submission, actor, "withdrawn", reason)


def _record_review(submission, actor, outcome, reason):
    previous = BuildReview.objects.filter(submission=submission).first()
    if previous:
        if previous.outcome == outcome:
            return previous
        raise ValidationError("This revision already has a different outcome.")
    project, submission = _current(submission)
    if outcome == "approved":
        promote(submission, actor)
    else:
        if not BuildProject.objects.filter(
            pk=project.pk, state="submitted", version=project.version
        ).update(state="draft"):
            raise ValidationError("This submission has changed.")
    result = BuildReview.objects.create(
        submission=submission, actor=actor, actor_name=actor.key, outcome=outcome, reason=reason
    )
    audit(actor, outcome, project=project, submission=submission.pk, reason=reason)
    return result


@atomic_objects
def review(actor, submission, *, expected_revision, outcome, reason):
    BuildProject.objects.filter(pk=submission.project_id).update(version=F("version"))
    require_revealed(actor)
    if not is_staff(actor):
        raise PermissionDenied("Only Building staff can review proposals.")
    if outcome not in {"approved", "changes_requested", "declined"}:
        raise ValidationError("Choose approved, changes_requested or declined.")
    reason = _text(reason, 10000)
    submission = BuildSubmission.objects.get(pk=submission.pk)
    if submission.revision != expected_revision:
        raise ValidationError("The review revision has changed.")
    if apps.is_installed("evennia_jobs") and submission.jobs_submission_id:
        from evennia_jobs.models import RequestSubmission
        from evennia_jobs.review import review_request

        linked = RequestSubmission.objects.filter(pk=submission.jobs_submission_id).first()
        if linked:
            return review_request(
                job=linked.job,
                reviewer=actor,
                outcome=outcome,
                reason=reason,
                expected_revision=linked.revision,
            )
    return _record_review(submission, actor, outcome, reason)


@atomic_objects
def promote(submission, actor):
    BuildProject.objects.filter(pk=submission.project_id).update(version=F("version"))
    if not is_staff(actor):
        raise PermissionDenied("Only staff can promote reviewed interiors.")
    from .models import Frontier

    receipt = (
        Frontier.objects.filter(promotion=submission).first()
        or Property.objects.filter(promotion=submission).first()
    )
    if receipt:
        return receipt
    project, submission = _current(submission)
    candidate = snapshot(project)
    from .collaboration import validate as validate_agreements

    agreement_ids = validate_agreements(project, candidate)
    from .attachments import consume, validate_consent

    consent = validate_consent(project, candidate)
    if consent:
        candidate["consent"] = consent.pk
    if agreement_ids:
        candidate["project_agreements"] = agreement_ids
    candidate["acknowledgement"] = submission.snapshot["acknowledgement"]
    if fingerprint(candidate) != submission.fingerprint:
        raise ValidationError(
            "The submitted content or attachment conditions changed. Request changes and submit a fresh revision."
        )
    requested = candidate["requested_environment"]
    if (
        requested
        and not EnvironmentApproval.objects.filter(
            submission=submission, fingerprint=submission.fingerprint
        ).exists()
    ):
        raise ValidationError(
            "Staff must explicitly approve the requested environment before promotion."
        )
    terrain = requested.get("terrain", candidate["terrain"])
    region_id = requested.get("region", candidate["region"])
    if not BuildProject.objects.filter(
        pk=project.pk, state="submitted", version=project.version
    ).update(state="promoted"):
        raise ValidationError("This proposal is no longer awaiting approval.")
    anchor = _anchor(project)
    if project.kind == "frontier":
        from .frontier import promote_frontier

        return promote_frontier(submission, actor, project, candidate, terrain, region_id)
    entry = project.rooms.get(entry=True).room
    entrance = _exit(anchor, entry, project.entrance_name)
    departure = _exit(entry, anchor, "outside", outward=True)
    property = Property.objects.create(
        owner=project.proposed_owner or project.owner,
        owner_name=(project.proposed_owner or project.owner).key,
        name=project.name,
        promotion=submission,
        anchor=anchor,
        entrance=entrance,
        departure=departure,
        provenance={
            "submission": submission.pk,
            "fingerprint": submission.fingerprint,
            "actor": actor.pk,
            "terrain": terrain,
            "region": region_id,
            "requested_environment": requested,
            "purpose": project.purpose,
        },
    )
    for record in project.rooms.select_related("room"):
        room = record.room
        RoomOwnership.objects.create(
            room=room, object_id=room.pk, property=property, owner=property.owner
        )
        _flags(room, False)
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

            RoomTile.objects.filter(room=room).update(
                terrain=resolve_terrain(room), room_name=room.key
            )
    consume(submission, property)
    project.agreements.filter(pk__in=agreement_ids).update(state="consumed")
    audit(actor, "promoted", project=project, property=property, submission=submission.pk)
    signals.property_promoted.send(
        sender=Property, property=property, submission=submission, actor=actor
    )
    transaction.on_commit(
        lambda: signals.property_changed.send_robust(
            sender=Property, property=property, actor=actor
        )
    )
    return property


def _property(property, actor, *, staff=False):
    Property.objects.filter(pk=property.pk).update(locked=F("locked"))
    require_revealed(actor)
    property = Property.objects.select_for_update().get(pk=property.pk)
    if property.state not in ({"live", "archived"} if staff else {"live"}) or not property.owner_id:
        raise ValidationError("This property needs staff repair.")
    if (staff and not is_staff(actor)) or (not staff and property.owner_id != actor.pk):
        raise PermissionDenied("Only the property owner may manage these rights.")
    return property


def _changed(property, actor, action, **data):
    audit(actor, action, property=property, **data)
    transaction.on_commit(
        lambda: signals.property_changed.send_robust(
            sender=Property, property=property, actor=actor
        )
    )


@atomic_objects
def set_locked(actor, property, locked):
    property = _property(property, actor)
    if type(locked) is not bool:
        raise ValidationError("Choose locked or unlocked.")
    property.locked = locked
    property.save(update_fields=["locked"])
    _changed(property, actor, "locked" if locked else "unlocked")
    return property


@atomic_objects
def set_resident(actor, property, character, *, remove=False, can_install=False):
    property = _property(property, actor)
    _character(character)
    if character.pk == property.owner_id:
        raise ValidationError("Choose another character.")
    if remove:
        Resident.objects.filter(property=property, character=character).delete()
    else:
        if type(can_install) is not bool:
            raise ValidationError("Installation permission must be explicit.")
        Resident.objects.update_or_create(
            property=property, character=character, defaults={"can_install": can_install}
        )
    _changed(
        property,
        actor,
        "resident_removed" if remove else "resident_set",
        character=character.pk,
        can_install=can_install,
    )


@atomic_objects
def invite(actor, property, character, *, entry=True, maps=True, revoke=False):
    property = _property(property, actor)
    _character(character)
    if type(entry) is not bool or type(maps) is not bool:
        raise ValidationError("Choose a character and explicit entry/map scopes.")
    invitation, _ = GuestInvitation.objects.update_or_create(
        property=property,
        character=character,
        defaults={"entry": entry, "maps": maps, "state": "revoked" if revoke else "pending"},
    )
    _changed(
        property,
        actor,
        "invitation_revoked" if revoke else "invited",
        character=character.pk,
        entry=entry,
        maps=maps,
    )
    return invitation


@atomic_objects
def answer_invitation(actor, invitation, *, accept):
    require_revealed(actor)
    # Same property lock as revocation/transfer, followed by the invitation row.
    Property.objects.select_for_update().get(pk=invitation.property_id)
    invitation = GuestInvitation.objects.select_for_update().get(pk=invitation.pk)
    if invitation.character_id != actor.pk:
        raise PermissionDenied("Only the invited character can answer.")
    if invitation.state != "pending" or type(accept) is not bool:
        raise ValidationError("This invitation is no longer pending.")
    invitation.state = "accepted" if accept else "declined"
    invitation.save(update_fields=["state"])
    _changed(invitation.property, actor, "invitation_" + invitation.state, invitation=invitation.pk)
    return invitation


@atomic_objects
def set_override(actor, room, allowed_character_ids=None):
    record = ownership(room)
    if not record:
        raise ValidationError("This is not a live Building room.")
    property = _property(record.property, actor)
    if allowed_character_ids is None:
        RoomOverride.objects.filter(ownership=record).delete()
    else:
        if not isinstance(allowed_character_ids, list) or any(
            type(pk) is not int for pk in allowed_character_ids
        ):
            raise ValidationError("Supply character IDs or reset to inherited rights.")
        characters = list(ObjectDB.objects.filter(pk__in=allowed_character_ids))
        if len(characters) != len(set(allowed_character_ids)):
            raise ValidationError("An allowed character no longer exists.")
        for character in characters:
            _character(character)
        RoomOverride.objects.update_or_create(
            ownership=record, defaults={"allowed_character_ids": sorted(set(allowed_character_ids))}
        )
    _changed(property, actor, "room_override", room=room.pk, allowed=allowed_character_ids)


@atomic_objects
def transfer(
    actor,
    property,
    new_owner,
    *,
    expected_owner,
    reason,
    retain_grants=False,
    stock_disposition=None,
):
    property = _property(property, actor, staff=True)
    if property.owner_id != expected_owner:
        raise ValidationError("The property owner changed; reload before transfer.")
    reason = _text(reason, 10000)
    _character(new_owner)
    if type(retain_grants) is not bool:
        raise ValidationError("Choose a new owning character and grant disposition.")
    previous = property.owner_id
    signals.property_transferring.send(
        sender=Property,
        property=property,
        actor=actor,
        new_owner=new_owner,
        stock_disposition=stock_disposition,
    )
    property.owner = new_owner
    property.owner_name = new_owner.key
    property.save(update_fields=["owner", "owner_name"])
    property.rooms.update(owner=new_owner)
    if not retain_grants:
        property.residents.all().delete()
        property.invitations.all().delete()
        RoomOverride.objects.filter(ownership__property=property).delete()
    _changed(
        property,
        actor,
        "transferred",
        old_owner=previous,
        new_owner=new_owner.pk,
        reason=reason,
        retain_grants=retain_grants,
    )
    from django.utils import timezone

    from .models import QuietFlag

    QuietFlag.objects.filter(property=property, resolved_at__isnull=True).update(
        resolved_at=timezone.now()
    )
    for consent in property.consent_requests.filter(state__in=["requested", "granted"]):
        consent.state = "invalidated"
        consent.save(update_fields=["state"])
        audit(
            actor,
            "consent_invalidated",
            project=consent.project,
            consent=consent.pk,
            reason="Parent ownership transferred",
        )
    return property


@atomic_objects
def edit_property_room(actor, room, *, name=None, description=None):
    record = ownership(room)
    if not record:
        raise ValidationError("Choose a property room.")
    property = _property(record.property, actor)
    if name is not None:
        room.key = _text(name)
    if description is not None:
        room.db.desc = _text(description, 50000)
    _changed(property, actor, "room_edited", room=room.pk, name=name, description=description)
    if apps.is_installed("evennia_maps"):
        from evennia_maps.models import RoomTile

        RoomTile.objects.filter(room=room).update(room_name=room.key)


@atomic_objects
def discard_token(actor, project):
    project = _project(project, actor, editable=True)
    return signing.dumps(
        {
            "project": project.pk,
            "version": project.version,
            "rooms": list(project.rooms.order_by("pk").values_list("object_id", flat=True)),
            "owner": actor.pk,
        },
        salt="building-discard",
    )


def _safe_room(actor, room_ids):
    previous = actor.attributes.get("building_return") if actor else None
    safe = getattr(settings, "BUILDING_SAFE_ROOM", getattr(settings, "DEFAULT_HOME", None))
    for value in (previous, safe):
        if isinstance(value, str):
            value = value.removeprefix("#")
        try:
            room = ObjectDB.objects.filter(pk=int(value)).first()
        except (TypeError, ValueError):
            continue
        if (
            room
            and room.pk not in room_ids
            and room.is_typeclass("evennia.objects.objects.DefaultRoom", exact=False)
        ):
            from .access import can_enter

            if can_enter(actor, room):
                return room
    raise ValidationError("No safe return room is available; nothing was removed.")


@atomic_objects
def discard(actor, project, token):
    project = _project(project, actor)
    if project.state == "discarded":
        return project
    if project.state != "draft":
        raise ValidationError("Withdraw before discarding; live property requires staff archival.")
    try:
        confirmed = signing.loads(token, salt="building-discard")
    except signing.BadSignature as exc:
        raise ValidationError("Request a new discard confirmation.") from exc
    expected = {
        "project": project.pk,
        "version": project.version,
        "rooms": list(project.rooms.order_by("pk").values_list("object_id", flat=True)),
        "owner": actor.pk,
    }
    if confirmed != expected:
        raise ValidationError("The draft changed; request a new discard confirmation.")
    records = list(project.rooms.select_related("room"))
    room_ids = {record.object_id for record in records}
    if (
        any(not record.room_id for record in records)
        or RoomOwnership.objects.filter(object_id__in=room_ids).exists()
        or Property.objects.filter(anchor_id__in=room_ids, state="live").exists()
    ):
        raise ValidationError(
            "Draft ownership or geometry needs staff repair; nothing was removed."
        )
    door_ids = set(project.doors.values_list("object_id", flat=True))
    foreign = ObjectDB.objects.filter(db_destination_id__in=room_ids).exclude(pk__in=door_ids)
    if foreign.exists():
        raise ValidationError(
            "An external exit points into this draft; ask staff before discarding."
        )
    contents = list(ObjectDB.objects.filter(db_location_id__in=room_ids).exclude(pk__in=door_ids))
    if any(obj.db_destination_id for obj in contents):
        raise ValidationError("An untracked exit is present; nothing was removed.")
    # Verify every destination before moving anyone or deleting any geometry.
    relocation = [
        (
            obj,
            _safe_room(
                obj
                if obj.is_typeclass("evennia.objects.objects.DefaultCharacter", exact=False)
                else actor,
                room_ids,
            ),
        )
        for obj in contents
    ]
    for obj, destination in relocation:
        obj.location = destination
    for door in project.doors.select_related("exit"):
        if door.exit:
            door.exit.ndb.building_cleanup = True
            try:
                if not door.exit.delete():
                    raise ValidationError("A door could not be removed; cleanup rolled back.")
            finally:
                door.exit.ndb.building_cleanup = None
    if apps.is_installed("evennia_maps"):
        from evennia_maps.models import MapPlane

        MapPlane.all_objects.filter(visibility_room_id__in=room_ids).delete()
    for record in records:
        record.room.ndb.building_cleanup = True
        try:
            if not record.room.delete():
                raise ValidationError("A room could not be removed; cleanup rolled back.")
        finally:
            record.room.ndb.building_cleanup = None
    project.state = "discarded"
    _touch(project)
    project.save(update_fields=["state"])
    project.consents.filter(state__in=["requested", "granted"]).update(state="invalidated")
    audit(
        actor,
        "discarded",
        project=project,
        rooms=sorted(room_ids),
        returned=[obj.pk for obj, _ in relocation],
    )
    return project


@atomic_objects
def enter(actor, project):
    require_revealed(actor)
    project = BuildProject.objects.get(pk=project.pk)
    from .collaboration import can_author

    if project.state not in {"draft", "submitted"} or not (
        can_author(actor, project) or is_staff(actor)
    ):
        raise PermissionDenied("This preview is private.")
    if (
        actor.location
        and not DraftRoom.objects.filter(
            object_id=actor.location.pk, project__state__in=["draft", "submitted"]
        ).exists()
    ):
        actor.db.building_return = actor.location.pk
    destination = project.rooms.get(entry=True).room
    if not destination or not actor.move_to(destination, quiet=True, move_type="teleport"):
        raise ValidationError("Preview entry failed.")


def leave(actor):
    require_revealed(actor)
    if (
        not actor.location
        or not DraftRoom.objects.filter(
            object_id=actor.location.pk, project__state__in=["draft", "submitted"]
        ).exists()
    ):
        raise ValidationError("You are not in a draft preview.")
    ids = set(
        DraftRoom.objects.filter(project__state__in=["draft", "submitted"]).values_list(
            "object_id", flat=True
        )
    )
    destination = _safe_room(actor, ids)
    if not actor.move_to(destination, quiet=True, move_type="teleport"):
        raise ValidationError("Return failed; ask staff.")
