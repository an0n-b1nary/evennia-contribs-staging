"""Staff retirement plans and review-only character inactivity notices."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from evennia.objects.models import ObjectDB

from evennia_links.runtime import get
from evennia_links.transactions import atomic_objects

from .attachments import begin_write
from .lifecycle import _staff, activity
from .models import (
    BuildingClock,
    DraftRoom,
    Frontier,
    FrontierConnection,
    FrontierRoom,
    Property,
    RoomOwnership,
    StewardQuietFlag,
)


def _reachable(nodes, roots, edges):
    forward, backward = defaultdict(set), defaultdict(set)
    for source, target in edges:
        if source in nodes and target in nodes:
            forward[source].add(target)
            backward[target].add(source)

    def walk(graph):
        seen, pending = set(roots) & nodes, list(set(roots) & nodes)
        while pending:
            for target in graph[pending.pop()] - seen:
                seen.add(target)
                pending.append(target)
        return seen

    return walk(forward) & walk(backward)


def _world():
    from .services import _read_attr

    private = set(RoomOwnership.objects.values_list("object_id", flat=True))
    inactive = set(
        DraftRoom.objects.exclude(project__state="promoted").values_list("object_id", flat=True)
    )
    inactive |= set(
        FrontierRoom.objects.exclude(frontier__state="live").values_list("object_id", flat=True)
    )
    nodes = {
        room.pk
        for room in ObjectDB.objects.filter(
            db_location__isnull=True, db_destination__isnull=True
        ).exclude(pk__in=private | inactive)
        if room.is_typeclass("evennia.objects.objects.DefaultRoom", exact=False)
        and _read_attr(room, "room_type", "ic") == "ic"
        and _read_attr(room, "allow_teleport") not in {"private", "secret"}
    }
    frontier_ids = set(FrontierRoom.objects.values_list("object_id", flat=True))
    return nodes, nodes - frontier_ids


def _edges():
    # Unknown conditional locks cannot promise enduring public passage.
    return [
        (source, target)
        for source, target, storage in ObjectDB.objects.filter(
            db_location__isnull=False, db_destination__isnull=False
        ).values_list("db_location_id", "db_destination_id", "db_lock_storage")
        if next(
            (
                part.strip().casefold()
                for part in storage.split(";")
                if part.strip().casefold().startswith("traverse:")
            ),
            "",
        )
        == "traverse:all()"
    ]


def _preserves_connections(nodes, remaining, before, after):
    """No surviving public places lose a formerly usable two-way connection."""
    pending = set(remaining)
    while pending:
        seed = next(iter(pending))
        expected = _reachable(nodes, {seed}, before) & remaining
        if not expected <= _reachable(remaining, {seed}, after):
            return False
        pending -= expected
    return True


def _replacement(actor, frontier, proposal, removed):
    from .frontier import _free, direction, public_room, reverse
    from .services import _exit, _exit_data

    if not isinstance(proposal, dict) or set(proposal) != {"source", "target", "direction"}:
        raise ValidationError("Each replacement needs source, target and direction.")
    source = public_room(ObjectDB.objects.filter(pk=proposal["source"]).first())
    target = public_room(ObjectDB.objects.filter(pk=proposal["target"]).first())
    if source.pk in removed or target.pk in removed or source.pk == target.pk:
        raise ValidationError("Replacement routes must bypass the retiring rooms.")
    name = proposal["direction"]
    offset = direction(name)
    _free(source, name)
    _free(target, reverse(name))
    if apps.is_installed("evennia_maps"):
        from evennia_maps.models import RoomTile

        a, b = (
            RoomTile.objects.select_related("plane").filter(room=room).first()
            for room in (source, target)
        )
        if (
            not a
            or not b
            or (b.x, b.y, b.plane.elevation)
            != (a.x + offset[0], a.y + offset[1], a.plane.elevation + offset[2])
        ):
            raise ValidationError("A replacement connection must align with existing grid cells.")
        if a.plane_id != b.plane_id and not (a.plane.zstack and a.plane.zstack == b.plane.zstack):
            raise ValidationError("A replacement cannot jump between unrelated stacks.")
    for start, end, label in ((source, target, name), (target, source, reverse(name))):
        exit = _exit(start, end, label, outward=True)
        FrontierConnection.objects.create(
            frontier=frontier, exit=exit, object_id=exit.pk, data=_exit_data(exit), replacement=True
        )


@atomic_objects
def archive(
    actor, frontier, *, reason, affected_frontiers=(), affected_properties=(), replacements=()
):
    from . import lifecycle, signals
    from .services import _exit_data, _read_attr, _safe_room, _text, audit

    begin_write()
    _staff(actor)
    reason = _text(reason, 10000)
    group_ids = {frontier.pk, *(row.pk for row in affected_frontiers)}
    group = list(Frontier.objects.select_for_update().filter(pk__in=group_ids).order_by("pk"))
    frontier = next(row for row in group if row.pk == frontier.pk)
    if frontier.state == "archived":
        return frontier
    if len(group) != len(group_ids) or any(row.state != "live" for row in group):
        raise ValidationError("Select live frontier areas for coordinated retirement.")
    records = list(FrontierRoom.objects.filter(frontier_id__in=group_ids).select_related("room"))
    removed = {row.object_id for row in records}
    list(ObjectDB.objects.select_for_update().filter(pk__in=removed).order_by("pk"))
    if not removed or any(not row.room_id for row in records):
        raise ValidationError("The frontier room set needs repair.")
    property_ids = {row.pk for row in affected_properties}
    dependent = Property.objects.filter(state="live", anchor_id__in=removed)
    if dependent.exclude(pk__in=property_ids).exists():
        raise ValidationError(
            "Retirement would strand active homes; include them in a coordinated plan."
        )
    nodes, roots = _world()
    old_edges = _edges()
    before = _reachable(nodes, roots, old_edges)
    for proposal in replacements:
        _replacement(actor, frontier, proposal, removed)
    remaining = nodes - removed
    after = _reachable(remaining, roots, _edges())
    protected = set(
        FrontierRoom.objects.filter(frontier__state="live")
        .exclude(frontier_id__in=group_ids)
        .values_list("object_id", flat=True)
    )
    protected |= set(
        Property.objects.filter(state="live")
        .exclude(pk__in=property_ids)
        .values_list("anchor_id", flat=True)
    )
    if (protected & before) - after or not _preserves_connections(
        nodes, remaining, old_edges, _edges()
    ):
        raise ValidationError(
            "Retirement would strand active streets or homes; supply replacement passage or a coordinated plan."
        )
    for property in Property.objects.filter(pk__in=property_ids).order_by("pk"):
        lifecycle.archive(actor, property, reason=reason, include_children=True)
    boundary_ids = set(Property.objects.values_list("entrance_id", flat=True)) | set(
        Property.objects.values_list("departure_id", flat=True)
    )
    exits = list(
        ObjectDB.objects.filter(
            Q(db_location_id__in=removed) | Q(db_destination_id__in=removed),
            db_destination__isnull=False,
        )
        .exclude(pk__in=boundary_ids)
        .order_by("pk")
    )
    saved_exits = [_exit_data(exit) for exit in exits]
    returned = []
    for obj in ObjectDB.objects.filter(db_location_id__in=removed):
        if obj.is_typeclass("evennia.objects.objects.DefaultCharacter", exact=False):
            obj.location = _safe_room(obj, removed)
            returned.append(obj.pk)
    room_data = {
        row.object_id: {
            "room_type": _read_attr(row.room, "room_type"),
            "teleport": _read_attr(row.room, "allow_teleport"),
        }
        for row in records
    }
    for exit in exits:
        exit.location = None
    for row in records:
        row.room.attributes.add("room_type", "ooc")
        row.room.attributes.add("allow_teleport", "secret")
    for item in group:
        item.archive_data = {
            "exits": saved_exits,
            "rooms": room_data,
            "frontiers": sorted(group_ids),
            "properties": sorted(property_ids),
            "replacements": list(replacements),
        }
        item.state = "archived"
        item.save(update_fields=["state", "archive_data"])
        audit(
            actor,
            "frontier_archived",
            frontier=item,
            reason=reason,
            group=sorted(group_ids),
            properties=sorted(property_ids),
            replacements=list(replacements),
            returned=returned,
        )
        transaction_frontier_changed(item, actor, signals)
    StewardQuietFlag.objects.filter(
        room__frontier_id__in=group_ids, resolved_at__isnull=True
    ).update(resolved_at=timezone.now())
    return frontier


def transaction_frontier_changed(frontier, actor, signals):
    from django.db import transaction

    transaction.on_commit(
        lambda: signals.frontier_changed.send_robust(
            sender=Frontier, frontier=frontier, actor=actor
        )
    )


@atomic_objects
def restore(actor, frontier, *, reason):
    from . import signals
    from .frontier import _free, direction, offsets, public_room
    from .services import _exit_data, _text, audit

    begin_write()
    _staff(actor)
    reason = _text(reason, 10000)
    frontier = Frontier.objects.select_for_update().get(pk=frontier.pk)
    if frontier.state == "live":
        return frontier
    group_ids = frontier.archive_data.get("frontiers", [])
    group = list(Frontier.objects.select_for_update().filter(pk__in=group_ids).order_by("pk"))
    if not group or any(
        row.state != "archived" or row.archive_data != frontier.archive_data for row in group
    ):
        raise ValidationError("Restore the complete preserved retirement group together.")
    saved = frontier.archive_data
    endpoints = {pk for data in saved["exits"] for pk in (data["source"], data["target"])}
    list(ObjectDB.objects.select_for_update().filter(pk__in=endpoints).order_by("pk"))
    records = list(FrontierRoom.objects.filter(frontier_id__in=group_ids).select_related("room"))
    room_ids = {row.object_id for row in records}
    if not records or any(not row.room_id for row in records):
        raise ValidationError("A preserved frontier room is missing.")
    exits = []
    additions = Counter(data["source"] for data in saved["exits"])
    if get("BUILDING_DOOR_LIMIT_HARD") and any(
        ObjectDB.objects.filter(db_location_id=pk, db_destination__isnull=False).count() + count
        > get("BUILDING_DOOR_LIMIT")
        for pk, count in additions.items()
    ):
        raise ValidationError("Restoring the frontier would exceed the hard door limit.")
    for data in saved["exits"]:
        exit = ObjectDB.objects.filter(pk=data["id"]).first()
        if not exit or _exit_data(exit) != {**data, "source": None}:
            raise ValidationError("A preserved route changed; staff repair is required.")
        for endpoint in (data["source"], data["target"]):
            if endpoint not in room_ids:
                public_room(ObjectDB.objects.filter(pk=endpoint).first())
        source = ObjectDB.objects.get(pk=data["source"])
        if data["name"].casefold() in offsets():
            _free(source, data["name"])
            if apps.is_installed("evennia_maps"):
                from evennia_maps.models import RoomTile

                a, b = (
                    RoomTile.objects.select_related("plane").filter(room_id=pk).first()
                    for pk in (data["source"], data["target"])
                )
                offset = direction(data["name"])
                if (
                    not a
                    or not b
                    or a.plane.is_archived
                    or b.plane.is_archived
                    or (b.x, b.y, b.plane.elevation)
                    != (a.x + offset[0], a.y + offset[1], a.plane.elevation + offset[2])
                ):
                    raise ValidationError("The preserved frontier no longer aligns with the grid.")
                if a.plane_id != b.plane_id and not (
                    a.plane.zstack and a.plane.zstack == b.plane.zstack
                ):
                    raise ValidationError("The preserved frontier no longer shares a map stack.")
        exits.append((exit, source))
    for exit, source in exits:
        exit.location = source
    for row in records:
        data = saved["rooms"][str(row.object_id)]
        row.room.attributes.add("room_type", data["room_type"])
        row.room.attributes.add("allow_teleport", data["teleport"])
    for item in group:
        item.state = "live"
        item.save(update_fields=["state"])
        audit(actor, "frontier_restored", frontier=item, reason=reason, group=group_ids)
        transaction_frontier_changed(item, actor, signals)
    return frontier


@atomic_objects
def check_quiet(*, now=None):
    """Staff reviews inactivity; no ownership, stewardship or access is changed."""
    begin_write()
    now = now or timezone.now()
    if not get("BUILDING_REVEALED"):
        return []
    clock, _ = BuildingClock.objects.get_or_create(pk=1, defaults={"revealed_at": now})
    cutoff = now - timedelta(days=get("BUILDING_QUIET_DAYS"))
    flagged = []
    for row in (
        FrontierRoom.objects.select_for_update()
        .filter(frontier__state="live")
        .select_related("steward", "frontier")
    ):
        pending = StewardQuietFlag.objects.filter(room=row, resolved_at__isnull=True)
        seen = activity(row.steward) if row.steward else None
        active = max(clock.revealed_at, row.assigned_at, seen or datetime.min.replace(tzinfo=UTC))
        if not row.steward_id or row.steward.sessions.count() or active > cutoff:
            pending.update(resolved_at=now)
            continue
        pending.exclude(steward_object_id=row.steward_id).update(resolved_at=now)
        flag, _ = StewardQuietFlag.objects.get_or_create(
            room=row,
            resolved_at__isnull=True,
            defaults={"steward_object_id": row.steward_id, "last_played": seen},
        )
        flagged.append(flag)
    return flagged


def quiet_list(actor):
    _staff(actor)
    return StewardQuietFlag.objects.filter(resolved_at__isnull=True).select_related(
        "room__frontier", "room__room"
    )
