# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Read-only cross-plane translation and atomic application for trusted callers.

This module grants no building rights and creates no exits. A project service
must authorize its actor and freeze the submitted room set before using it.
Plans preserve relative x/y/elevation, never rotate or reflow a draft, and
include only the explicit room set (interiors can remain on their own stack).
"""

from dataclasses import dataclass
from hashlib import sha256

from django.core.exceptions import ValidationError
from django.db import transaction
from evennia.objects.models import ObjectDB

from evennia_maps import direction, placement
from evennia_maps.models import MapPlane, RoomTile


@dataclass(frozen=True)
class TransplantMove:
    room: object
    plane: object
    x: int
    y: int


@dataclass(frozen=True)
class Adjacency:
    room_id: int
    neighbor_room_id: int


@dataclass(frozen=True)
class TransplantPlan:
    room_ids: tuple
    entry_id: int
    anchor_id: int
    direction: str
    moves: tuple
    conflicts: tuple
    adjacency: tuple
    fingerprint: str


def plan_transplant(rooms, *, entry_room, anchor_room, direction_name):
    """Translate entry one compass step from anchor; make no database writes.

    Missing tiles, pins, occupied cells/directions, unrelated source stacks,
    inconsistent internal compass exits and archived planes block application.
    Neighbouring existing rooms without an exit are warnings, not blockers.
    Floors translate to the matching target-stack elevation; a standalone
    target cannot accept multiple floors. Missing target floors stay pending.
    """
    room_ids = tuple(sorted({room.pk for room in rooms}))
    offset = direction.get_offsets().get(direction_name.strip().lower())
    if not offset or offset[3] != "planar" or offset[2] != 0 or offset[:2] == (0, 0):
        raise ValidationError("Choose a compass direction for the attachment.")
    if entry_room.pk not in room_ids or anchor_room.pk in room_ids:
        raise ValidationError("The draft must contain its entry and exclude its anchor.")
    tiles = list(
        RoomTile.objects.filter(room_id__in=(*room_ids, anchor_room.pk))
        .select_related("room", "plane")
        .order_by("room_id")
    )
    by_id = {t.room_id: t for t in tiles}
    if len(tiles) != len(room_ids) + 1:
        raise ValidationError("Every draft room and the attachment room must be mapped.")
    entry, anchor = by_id[entry_room.pk], by_id[anchor_room.pk]
    source, target = entry.plane, anchor.plane
    source_planes = (
        list(MapPlane.all_objects.filter(zstack=source.zstack).order_by("pk"))
        if source.zstack
        else [source]
    )
    target_planes = (
        list(MapPlane.all_objects.filter(zstack=target.zstack).order_by("pk"))
        if target.zstack
        else [target]
    )
    if {p.pk for p in source_planes} & {p.pk for p in target_planes}:
        raise ValidationError("Source and destination must be separate coordinate spaces.")
    conflicts = []
    moves = []
    for room_id in room_ids:
        tile = by_id[room_id]
        if tile.plane_id not in {p.pk for p in source_planes}:
            conflicts.append(f"Room #{room_id} is outside the source stack.")
        if tile.pinned:
            conflicts.append(f"Room #{room_id} is pinned.")
        if tile.plane.is_archived:
            conflicts.append(f"Room #{room_id} is on an archived plane.")
        elevation_delta = tile.plane.elevation - source.elevation
        if elevation_delta and not target.zstack:
            conflicts.append("A standalone target cannot accept multiple floors.")
            dest_plane = target
        elif elevation_delta:
            dest_plane = placement.resolve_stacked_plane(target, elevation_delta, create=False)
        else:
            dest_plane = target
        if getattr(dest_plane, "is_archived", False):
            conflicts.append(f"Target floor for room #{room_id} is archived.")
        moves.append(
            TransplantMove(
                tile.room,
                dest_plane,
                anchor.x + offset[0] + tile.x - entry.x,
                anchor.y + offset[1] + tile.y - entry.y,
            )
        )
    if target.is_archived:
        conflicts.append("The attachment plane is archived.")
    target_tiles = list(
        RoomTile.objects.filter(plane__in=target_planes)
        .select_related("room", "plane")
        .order_by("room_id")
    )
    occupied = {(placement.plane_key(t.plane), t.x, t.y): t for t in target_tiles}
    for move in moves:
        holder = occupied.get((placement.plane_key(move.plane), move.x, move.y))
        if holder:
            conflicts.append(f"Room #{move.room.pk} collides with room #{holder.room_id}.")
    # Include aliases through direction.resolve: matching an abbreviation
    # must block an occupied attachment just like matching its full name.
    exits = list(
        ObjectDB.objects.filter(
            db_location_id__in=(*room_ids, *(t.room_id for t in target_tiles)),
            db_destination__isnull=False,
        ).order_by("pk")
    )
    exit_state = tuple((e.pk, e.location.pk, e.destination.pk, direction.resolve(e)) for e in exits)
    connections = {frozenset((src, dst)) for _, src, dst, _ in exit_state}
    for _, src, dst, resolved in exit_state:
        if src == anchor.room_id and resolved == offset:
            conflicts.append("The attachment direction already has an exit.")
        if src in room_ids and dst in room_ids and resolved:
            a, b = by_id[src], by_id[dst]
            expected = (a.x + resolved[0], a.y + resolved[1], a.plane.elevation + resolved[2])
            if (b.x, b.y, b.plane.elevation) != expected:
                conflicts.append(f"The exit from #{src} to #{dst} disagrees with the draft map.")
    adjacency = set()
    neighbour_offsets = {tuple(offset) for offset in direction.get_offsets().values()}
    for move in moves:
        for other in target_tiles:
            delta = (
                other.x - move.x,
                other.y - move.y,
                other.plane.elevation - move.plane.elevation,
            )
            adjacent = any(delta == o[:3] for o in neighbour_offsets)
            pair = frozenset((move.room.pk, other.room_id))
            if (
                adjacent
                and pair != frozenset((entry.room_id, anchor.room_id))
                and pair not in connections
            ):
                adjacency.add((move.room.pk, other.room_id))

    def tile_state(t):
        return (t.pk, t.room_id, t.plane_id, t.x, t.y, t.pinned, t.terrain, t.room_name)

    plane_state = tuple(
        (p.pk, p.zstack, p.elevation, p.is_archived, p.visibility_room_id)
        for p in (*source_planes, *target_planes)
    )
    move_state = tuple((m.room.pk, placement.plane_key(m.plane), m.x, m.y) for m in moves)
    snapshot = (
        tuple(map(tile_state, tiles)),
        tuple(map(tile_state, target_tiles)),
        plane_state,
        exit_state,
        move_state,
        tuple(conflicts),
        tuple(sorted(adjacency)),
    )
    return TransplantPlan(
        room_ids,
        entry.room_id,
        anchor.room_id,
        direction_name,
        tuple(moves),
        tuple(conflicts),
        tuple(Adjacency(*a) for a in sorted(adjacency)),
        sha256(repr(snapshot).encode()).hexdigest(),
    )


@transaction.atomic
def apply_transplant(plan, *, actor=None):
    """Revalidate and move every tile, or raise ValidationError and write none.

    Target plane locks serialize cooperating writers on databases supporting
    row locks; database uniqueness constraints protect concurrent cell claims
    on every backend. Callers should also handle IntegrityError and retry a
    fresh preview. Existing tile identities survive the transplant.
    """
    objects = ObjectDB.objects.in_bulk((*plan.room_ids, plan.anchor_id))
    if len(objects) != len(plan.room_ids) + 1:
        raise ValidationError("The draft changed. Request a fresh preview.")
    tile_rows = list(
        RoomTile.objects.select_for_update().filter(room_id__in=(*plan.room_ids, plan.anchor_id))
    )
    plane_ids = {t.plane_id for t in tile_rows}
    stack_names = list(
        MapPlane.all_objects.filter(pk__in=plane_ids)
        .exclude(zstack="")
        .values_list("zstack", flat=True)
    )
    from django.db.models import Q

    list(
        MapPlane.all_objects.select_for_update()
        .filter(Q(pk__in=plane_ids) | Q(zstack__in=stack_names))
        .order_by("pk")
    )
    current = plan_transplant(
        [objects[pk] for pk in plan.room_ids],
        entry_room=objects[plan.entry_id],
        anchor_room=objects[plan.anchor_id],
        direction_name=plan.direction,
    )
    if current.fingerprint != plan.fingerprint:
        raise ValidationError("The map changed. Request a fresh preview.")
    if current.conflicts:
        raise ValidationError(list(current.conflicts))
    for move in current.moves:
        plane = placement.materialise_plane(move.plane)
        result = placement.move_tile(
            move.room, move.x, move.y, plane=plane, actor=actor, notify=False
        )
        if result is None or isinstance(result, placement.Conflict):
            raise ValidationError("The map changed. Request a fresh preview.")
        from evennia_maps.signals import tile_placed

        transaction.on_commit(
            lambda t=result: tile_placed.send(sender=RoomTile, tile=t, actor=actor, created=False)
        )
    return len(current.moves)
