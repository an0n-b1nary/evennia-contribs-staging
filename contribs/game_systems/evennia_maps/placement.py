# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tile placement core for evennia_maps.

The single write path for RoomTile create/move/unplace/pin, shared by the
exit-creation signal listener (listeners.py) and the +map command
(commands.py). Every successful write fires tile_placed; every rejected
write (target cell already held by another room) fires tile_conflicted
instead of silently overwriting — that's the whole point of the
unique_together constraints on RoomTile.
"""

from dataclasses import dataclass

from django.db import transaction

from evennia_maps import direction, signals
from evennia_maps.models import MapPlane, RoomTile
from evennia_maps.terrain import resolve_terrain


@dataclass(frozen=True)
class Conflict:
    """A placement rejected because the target cell is already held."""

    plane: MapPlane
    x: int
    y: int
    room: object  # ObjectDB the placement was attempted for
    holder: RoomTile  # the tile already occupying (plane, x, y)


def _room_label(room):
    return getattr(room, "key", None) or f"#{room.id}"


@dataclass(frozen=True)
class PendingPlane:
    """
    A stacked plane a read path wants to use that does not exist yet.

    resolve_stacked_plane(create=False) returns one of these instead of
    scaffolding a real MapPlane row. A dry run or a plan that is never
    applied must not leave an empty plane behind — see the docstring on
    resolve_stacked_plane for why that matters more once dry-run and
    apply share one planning pass (layout.plan()).

    `name` deliberately reproduces the string resolve_stacked_plane()
    passes as its get_or_create default, so +map output reads
    identically whether the plane already existed or is about to be
    created.
    """

    zstack: str
    elevation: int

    @property
    def name(self):
        return f"{self.zstack} ({self.elevation})"


def plane_key_for_id(plane_id):
    """
    plane_key() for a plane known only by pk — e.g. rows from values_list.

    Exists so callers that never load the MapPlane object still produce
    keys plane_key() agrees with. Both spellings of a real plane's key
    are built here, in one place: if they ever drift, cell lookups
    silently stop matching and every block goes unreported, which no
    test would obviously localise back to a key format.
    """
    return ("plane", plane_id)


def plane_key(plane):
    """
    Stable identity for a MapPlane or PendingPlane, usable as a dict key.

    A PendingPlane has no pk, so cell bookkeeping that keys on plane_id
    alone would collide two different not-yet-created planes on None.
    """
    if isinstance(plane, PendingPlane):
        return ("pending", plane.zstack, plane.elevation)
    return plane_key_for_id(plane.pk)


def materialise_plane(plane):
    """Turn a PendingPlane into a real, saved MapPlane; pass real ones through."""
    if not isinstance(plane, PendingPlane):
        return plane
    obj, _ = MapPlane.all_objects.get_or_create(
        zstack=plane.zstack,
        elevation=plane.elevation,
        defaults={"name": plane.name},
    )
    return obj


def resolve_stacked_plane(source_plane, d_elevation, *, create=True):
    """
    Find (or scaffold) the plane one vertical step from source_plane.

    Shared by place_relative() and the layout engine so the archived-plane
    handling below lives in exactly one place.

    Looked up through MapPlane.all_objects, NOT MapPlane.objects: the
    default manager is an ArchivedManager that hides archived rows, but
    the evennia_maps_one_plane_per_elevation constraint is enforced by the
    DB regardless of archive state. Going through .objects would miss an
    archived plane, try to create a duplicate, and raise IntegrityError
    — which the exit-creation listener swallows (so `dig up` silently
    stops mapping) and +map/reflow does not (traceback to the builder).
    Placing onto an archived plane doesn't unarchive it; the tile simply
    stays hidden until someone unarchives deliberately.

    Args:
        source_plane (MapPlane): the plane being moved from.
        d_elevation (int): +1 for up, -1 for down.
        create (bool): True (the default, for write paths like
            place_relative) creates the plane if it doesn't exist yet.
            False (read paths — layout.walk/plan) returns a PendingPlane
            instead, so a dry run or an unapplied plan leaves no row
            behind.

    Returns:
        MapPlane: the adjacent-elevation plane if it already exists, or
            (create=True only) after creating it.
        PendingPlane: create=False and the plane doesn't exist yet.
        None: source_plane is standalone (blank zstack), so there is no
            stack to move within.
    """
    if not source_plane.zstack:
        return None
    target_elevation = source_plane.elevation + d_elevation
    if not create:
        existing = MapPlane.all_objects.filter(
            zstack=source_plane.zstack, elevation=target_elevation
        ).first()
        return existing or PendingPlane(source_plane.zstack, target_elevation)
    plane, _ = MapPlane.all_objects.get_or_create(
        zstack=source_plane.zstack,
        elevation=target_elevation,
        defaults={"name": f"{source_plane.zstack} ({target_elevation})"},
    )
    return plane


def place_tile(room, plane, x, y, *, pinned=None, actor=None):
    """
    Create or move the tile for `room` to (plane, x, y).

    Idempotent: calling with the room's current (plane, x, y) still
    refreshes the denormalized room_name/terrain snapshot but doesn't
    fire a spurious move.

    Moving a pinned tile is allowed here — this is the explicit write
    path, and honouring the pin is the *caller's* job. +map/reflow is
    the only caller that checks (it skips pinned tiles in both dry-run
    and apply). The exit-creation listener never needs to: place_relative
    only ever writes a destination that has no tile at all, so an
    existing pinned tile is never a candidate for it to move.

    Args:
        room: ObjectDB/Room to place.
        plane (MapPlane): destination plane.
        x, y (int): destination coordinates.
        pinned (bool or None): if given, set the tile's pinned flag.
        actor: ObjectDB/Character responsible for the write, for signal
            payloads (may be None for signal-driven auto-placement).

    Returns:
        RoomTile: the placed/updated tile, or
        Conflict: (plane, x, y) is already held by a different room.
    """
    existing_here = RoomTile.objects.filter(plane=plane, x=x, y=y).exclude(room=room).first()
    if existing_here:
        conflict = Conflict(plane=plane, x=x, y=y, room=room, holder=existing_here)
        signals.tile_conflicted.send(sender=RoomTile, conflict=conflict, actor=actor)
        return conflict

    tile, created = RoomTile.objects.get_or_create(
        room=room,
        defaults={
            "plane": plane,
            "x": x,
            "y": y,
            "room_name": _room_label(room),
            "terrain": resolve_terrain(room),
            "pinned": bool(pinned),
        },
    )
    if not created:
        tile.plane = plane
        tile.x = x
        tile.y = y
        tile.room_name = _room_label(room)
        tile.terrain = resolve_terrain(room)
        if pinned is not None:
            tile.pinned = pinned
        tile.save()

    signals.tile_placed.send(sender=RoomTile, tile=tile, actor=actor, created=created)
    return tile


def place_relative(source_room, exit_obj, *, actor=None):
    """
    Auto-place an exit's destination room relative to its mapped source.

    Resolves the exit's direction via direction.resolve(); returns None
    (the exit doesn't participate in layout) for free-form exits, exits
    with no destination, or an exit whose source room isn't mapped yet —
    there's nothing to be relative to.

    Vertical exits (u/d) move within the source plane's zstack, creating
    the adjacent-elevation plane on demand — but only once a tile is
    actually going to be written to it, since this function has two
    paths that decline to write. A vertical exit from a standalone plane
    (zstack="") has no stack to move within and is skipped, same as a
    free-form exit.

    Idempotent: if the destination room is already placed exactly where
    this exit computes, this is a no-op that returns the existing tile.

    Args:
        source_room: ObjectDB/Room the exit originates from.
        exit_obj: the Exit ObjectDB/typeclass instance.
        actor: ObjectDB/Character responsible, for signal payloads.

    Returns:
        RoomTile: destination tile (existing, unchanged, or newly placed).
        Conflict: destination is mapped elsewhere, or the computed cell
            is held by a different room.
        None: the exit doesn't participate in layout.
    """
    offset = direction.resolve(exit_obj)
    if offset is None:
        return None

    dest_room = exit_obj.destination
    if dest_room is None:
        return None

    source_tile = RoomTile.objects.filter(room=source_room).first()
    if source_tile is None:
        return None

    dx, dy, dz, kind = offset
    if kind == "vertical":
        # create=False even though this is a write path: the two early
        # returns below can decline to write a tile, and creating the
        # plane before knowing whether we will use it leaves an empty
        # one behind (`dig up` to an already-mapped room did exactly
        # that). materialise_plane() runs only on the line that writes.
        target_plane = resolve_stacked_plane(source_tile.plane, dz, create=False)
        if target_plane is None:
            return None
        target_x, target_y = source_tile.x, source_tile.y
    else:
        target_plane = source_tile.plane
        target_x, target_y = source_tile.x + dx, source_tile.y + dy

    dest_tile = RoomTile.objects.filter(room=dest_room).first()
    if dest_tile is not None:
        # Compared through plane_key so a PendingPlane target (which has
        # no pk) still answers "is the destination already here?".
        already_there = (plane_key_for_id(dest_tile.plane_id), dest_tile.x, dest_tile.y) == (
            plane_key(target_plane),
            target_x,
            target_y,
        )
        if already_there:
            return dest_tile
        conflict = Conflict(
            plane=target_plane, x=target_x, y=target_y, room=dest_room, holder=dest_tile
        )
        signals.tile_conflicted.send(sender=RoomTile, conflict=conflict, actor=actor)
        return conflict

    return place_tile(dest_room, materialise_plane(target_plane), target_x, target_y, actor=actor)


def move_tile(room, x, y, *, plane=None, actor=None):
    """
    Explicitly reposition a room's existing tile.

    Args:
        room: ObjectDB/Room whose tile is being moved.
        x, y (int): new coordinates.
        plane (MapPlane or None): new plane; defaults to the tile's
            current plane (a same-plane move).
        actor: ObjectDB/Character responsible, for signal payloads.

    Returns:
        RoomTile: the moved tile, or
        Conflict: the target cell is held by a different room, or
        None: the room has no existing tile to move.
    """
    tile = RoomTile.objects.filter(room=room).first()
    if tile is None:
        return None

    target_plane = plane or tile.plane
    holder = RoomTile.objects.filter(plane=target_plane, x=x, y=y).exclude(room=room).first()
    if holder:
        conflict = Conflict(plane=target_plane, x=x, y=y, room=room, holder=holder)
        signals.tile_conflicted.send(sender=RoomTile, conflict=conflict, actor=actor)
        return conflict

    tile.plane = target_plane
    tile.x = x
    tile.y = y
    # Refresh the denormalized snapshot on the same terms as place_tile,
    # so the two write paths can't leave +map/check reporting drift that
    # depends only on which one last touched the tile.
    tile.room_name = _room_label(room)
    tile.terrain = resolve_terrain(room)
    tile.save()
    signals.tile_placed.send(sender=RoomTile, tile=tile, actor=actor, created=False)
    return tile


def unplace_tile(room):
    """Remove a room's tile from the map entirely. Returns True if one existed."""
    deleted, _ = RoomTile.objects.filter(room=room).delete()
    return bool(deleted)


def set_pin(room, pinned):
    """
    Set (or clear) the pinned flag on a room's tile.

    Returns:
        RoomTile: the updated tile, or None if the room has no tile.
    """
    tile = RoomTile.objects.filter(room=room).first()
    if tile is None:
        return None
    tile.pinned = bool(pinned)
    tile.save(update_fields=["pinned"])
    return tile


def apply_plan(plan, *, actor=None):
    """
    Write a layout.plan() result to the database.

    Delete-then-recreate every mover's tile, not ordered in-place
    updates: the "who currently holds my target" relation among
    plan.moves has in-degree <= 1 (layout._propose claims cells
    first-wins, so proposals — and therefore move targets — are
    cell-unique), which means the movers decompose into simple paths
    *and simple cycles*. A cyclic rearrangement (a ring of rooms
    rotating one step) has no free cell to start an in-place update
    from, so ordering the writes cannot work in general. Deleting every
    mover's tile first, then writing every target, sidesteps that
    entirely — and it means SQLite's per-statement UNIQUE check on
    (plane, x, y) never sees a target that's still held by a mover
    that hasn't been rewritten yet.

    All of it is one transaction: plan.moves is only safe to write as a
    whole — a plan is not a sequence of independent place_tile() calls,
    it is the specific set layout.plan() proved mutually compatible.
    Writing part of it can land the map in a state layout.plan() never
    considered and never validated.

    A PendingPlane target (a stacked plane layout.plan() referenced but
    did not create — see PendingPlane) is materialised here, immediately
    before the tile that needs it is written, via materialise_plane().
    So a plan that turns out to write nothing (every move blocked) never
    creates an empty plane either.

    tile_placed is deferred to transaction.on_commit, so a receiver only
    ever sees committed state: it can't roll back a reflow by raising,
    it can't observe a half-written map, and — the case a plain "fire
    after the atomic block" would get wrong — it doesn't fire at all if
    an enclosing transaction later rolls back. That matters because the
    atomic() below is normally *nested*: +map/reflow/apply wraps plan()
    and this call in one transaction, so leaving the inner block is a
    savepoint release, not a commit. There are no receivers today; this
    is forward-looking.

    RoomTile primary keys are NOT stable across a reflow: a moved room's
    tile is deleted and recreated with a new pk. Nothing in this
    contrib references a RoomTile pk (only room_id and (plane, x, y)),
    so this is safe, but consuming code must not assume a tile's pk
    survives a reflow.

    Args:
        plan (layout.ReflowPlan): as returned by layout.plan(). Only
            plan.moves is written — pinned_skips and blocked are reports
            for the caller to render, not instructions to act on.
        actor: ObjectDB/Character responsible for the write, for signal
            payloads.

    Returns:
        int: number of tiles written (len(plan.moves)).

    Raises:
        IntegrityError: the map changed underneath this plan between
            when it was computed and when this was called — e.g. the
            exit-creation listener wrote a tile mid-reflow. Nothing is
            written; the whole transaction rolls back. Callers should
            wrap layout.plan() and this call in one shared
            transaction.atomic() (nesting is free) and catch this rather
            than let a builder see a traceback.
    """
    written = 0
    with transaction.atomic():
        room_ids = [move.room.id for move in plan.moves]
        RoomTile.objects.filter(room_id__in=room_ids).delete()
        for move in plan.moves:
            target_plane = materialise_plane(move.plane)
            tile = RoomTile.objects.create(
                room=move.room,
                plane=target_plane,
                x=move.x,
                y=move.y,
                room_name=_room_label(move.room),
                terrain=resolve_terrain(move.room),
                pinned=move.pinned,
            )
            # Default-arg binding, not closure capture: a bare lambda in
            # a loop would send the last tile N times.
            transaction.on_commit(
                lambda t=tile, c=move.created: signals.tile_placed.send(
                    sender=RoomTile, tile=t, actor=actor, created=c
                )
            )
            written += 1

    return written
