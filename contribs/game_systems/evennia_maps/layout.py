# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Read-only BFS layout engine for evennia_maps.

walk() traces canonical exits outward from an origin room's existing
tile, proposing (room, plane, x, y) assignments for every room reachable
and flagging genuine conflicts. It never writes a RoomTile; +map/reflow
(dry-run) reads this report directly.

plan() runs the same BFS and then decides which of those assignments can
actually be written — see "Why a single pass under-reports" below. Both
+map/reflow (dry-run) and +map/reflow/apply render a plan() result, so
they cannot disagree; only /apply calls placement.apply_plan() on it.

Neither walk() nor plan() writes a RoomTile, or scaffolds a MapPlane row
for a not-yet-existing vertical-stack plane — vertical exits resolve to
a placement.PendingPlane instead (placement.resolve_stacked_plane
called with create=False). Only placement.apply_plan() materialises a
PendingPlane, and only immediately before writing a tile onto it. Before
this was deliberate, a dry run over a u/d exit into a new stacked plane
left an empty MapPlane row behind even when nothing was ever applied;
now that "planned but never applied" is the common case (see below), an
empty scaffold on every dry run would accumulate fast.

**Proposal and validation are two separate phases, deliberately.** A
reflow moves many rooms at once, so a room's *current* position says
nothing about whether its cell will still be occupied afterwards. Fusing
the phases means validating early rooms against pre-reflow state: insert
one room into an N-room corridor and every downstream room appears to
collide with its predecessor, because BFS reaches the claimant before it
reaches the room that is about to vacate. _propose() therefore computes
every final position first with no DB consultation at all, and
_validate() then judges those positions against the map — where a cell
held by a room that is itself moving is not a conflict.

Three conflict reasons are distinguished (LayoutConflict.reason):

    cell_held      — the cell belongs to a room outside this walk, which
                     is not moving and will still be there afterwards.
    cell_contested — two different rooms in this walk resolve to the same
                     cell (overlapping geometry).
    room_ambiguous — one room is reachable at two different coordinates
                     by two different paths (non-Euclidean topology).

**Why plan() needs a second, fixed-point pass on top of _validate().**
_validate() judges each proposal against the map's *current* state, so a
cell held by a fellow participant reads as fine — that participant is
"moving too". But some participants never actually move: a pinned tile,
or a room whose own target was itself cell_held-conflicted. Any mover
whose target is currently held by one of those is blocked — and because
that mover then also never vacates its own current cell, the room that
wanted *that* cell is transitively blocked too. This cascades: blocking
one mover can block another, which can block another. A single pass
that only checks "is my target held by something not moving" catches
the first blocked mover but misses everyone downstream of it, and would
report a plan that then tries to write a room onto a still-occupied
cell. _plan_moves() therefore runs a worklist to the fixed point:
removing a room from the movable set can only ever shrink it further,
so this always terminates, and it never removes a room that could
actually move (see the reason each removal is seeded/cascaded).

Three block reasons (Blocked.reason), parallel to LayoutConflict.reason:

    blocked_by_pinned    — target is held by a pinned tile.
    blocked_by_immovable — target is held by a participant whose own
                            move was rejected (e.g. cell_held elsewhere).
    blocked_by_blocked   — target is held by a mover that is itself
                            blocked (the cascade case).

A reflow with no blockers converges in a single apply; a corridor with
an obstruction at the far end cascades to zero moves, matching the
all-or-nothing intuition for that shape without special-casing it —
independent branches elsewhere in the same walk are unaffected.
"""

from collections import deque
from dataclasses import dataclass, field

from evennia_maps import direction
from evennia_maps.models import MapPlane, RoomTile
from evennia_maps.placement import (
    PendingPlane,
    plane_key,
    plane_key_for_id,
    resolve_stacked_plane,
)

CELL_HELD = "cell_held"
CELL_CONTESTED = "cell_contested"
ROOM_AMBIGUOUS = "room_ambiguous"

BLOCKED_BY_PINNED = "blocked_by_pinned"
BLOCKED_BY_IMMOVABLE = "blocked_by_immovable"
BLOCKED_BY_BLOCKED = "blocked_by_blocked"


@dataclass
class LayoutConflict:
    """A proposed position the walk could not honour. See module docstring."""

    room: object
    plane: MapPlane
    x: int
    y: int
    reason: str = CELL_HELD
    holder_room_id: int = None  # None for room_ambiguous (no rival room)


@dataclass
class LayoutReport:
    """Proposed assignments and conflicts discovered by walk()."""

    assignments: list = field(default_factory=list)  # [(room, plane, x, y, unchanged)]
    conflicts: list = field(default_factory=list)  # [LayoutConflict]
    unmapped_exits: list = field(default_factory=list)  # free-form exits skipped


@dataclass(frozen=True)
class Move:
    """A tile write plan.moves says is safe to make."""

    room: object
    plane: object  # MapPlane or a placement.PendingPlane yet to be materialised
    x: int
    y: int
    created: bool  # False if room already had a tile (this is a move, not a placement)
    pinned: bool  # always False — movers are never pinned, by construction; see apply_plan()


@dataclass(frozen=True)
class Blocked:
    """A move plan.plan() could not make room for. See module docstring."""

    room: object
    plane: object
    x: int
    y: int
    holder_room_id: int  # the room whose presence caused the block
    reason: str = BLOCKED_BY_IMMOVABLE


@dataclass
class ReflowPlan:
    """
    The result of plan(): what a reflow from some origin would write.

    .moves is the maximal set of writes that can be made together without
    any of them landing on an occupied cell — dry-run and apply render
    this same object, so what apply writes is always exactly what the
    dry run promised.
    """

    report: LayoutReport  # walk()'s assignments/conflicts/unmapped_exits
    moves: list = field(default_factory=list)  # [Move]
    pinned_skips: list = field(default_factory=list)  # [(room, plane, x, y)]
    blocked: list = field(default_factory=list)  # [Blocked]


@dataclass
class _ValidateContext:
    """
    Internal-only: the query results _validate() computes and discards.

    walk() only needs the LayoutReport; plan()'s fixed-point pass also
    needs to know who currently holds a cell (to seed blocking), where
    each participant currently sits (to find what a blocked room keeps
    occupying), and whether a participant's tile is pinned. All three
    come from the same two queries _validate() already runs — exposing
    them here means plan() costs no additional query over walk().
    """

    holder_by_cell: dict  # cell -> room_id, for every tile on a target plane
    current_cell_by_room_id: dict  # participant room_id -> its current cell
    pinned_by_room_id: dict  # participant room_id -> bool


def walk(origin_room):
    """
    BFS over canonical exits starting from origin_room's current tile.

    Args:
        origin_room: ObjectDB/Room already placed on the map.

    Returns:
        LayoutReport. Every entry in .assignments is safe to apply as far
            as the map's current state can tell; anything the walk had to
            reject is in .conflicts instead. Note this does NOT account
            for write-time ordering between assignments — use plan() to
            get a set that is actually safe to write together.

    Raises:
        ValueError: origin_room has no existing RoomTile to walk from.
    """
    report, _context = _run(origin_room)
    return report


def plan(origin_room):
    """
    Compute the maximal set of tile moves a reflow from origin_room can
    make without any of them landing on a still-occupied cell.

    Runs the same BFS as walk() (no extra query), then a fixed-point pass
    over the resulting assignments — see the module docstring for why a
    single pass under-reports which movers are blocked. No writes;
    placement.apply_plan() is the write side of this.

    Args:
        origin_room: ObjectDB/Room already placed on the map.

    Returns:
        ReflowPlan.

    Raises:
        ValueError: origin_room has no existing RoomTile to walk from.
    """
    report, context = _run(origin_room)
    return _plan_moves(report, context)


def _run(origin_room):
    """Shared prefix of walk() and plan(): BFS + validate, no writes."""
    origin_tile = RoomTile.objects.filter(room=origin_room).first()
    if origin_tile is None:
        raise ValueError("origin_room has no existing tile to walk from")

    proposals, report = _propose(origin_room, origin_tile)
    return _validate(proposals, report)


def _propose(origin_room, origin_tile):
    """
    Phase 1: BFS the exit graph, resolving every reachable room to a cell.

    Consults no existing RoomTile state — the point is to know where
    everything *ends up* before judging any of it. Cells are claimed
    first-wins so the resulting proposal set is internally consistent
    (one room per cell, one cell per room) and can be applied as-is.

    A vertical exit into a stacked plane that doesn't exist yet resolves
    to a placement.PendingPlane rather than scaffolding a real MapPlane
    row (resolve_stacked_plane(create=False)) — this function never
    writes anything, including plane rows, so a dry run or a plan that is
    never applied leaves nothing behind. Cells are therefore keyed by
    placement.plane_key(plane), not plane.id, since a PendingPlane has no
    pk and two different not-yet-created planes must not collide on None.

    Returns:
        tuple: (proposals, report) where proposals is
            [(room, plane, x, y)] and report carries the conflicts and
            unmapped exits found during traversal.
    """
    report = LayoutReport()
    origin_cell = (plane_key(origin_tile.plane), origin_tile.x, origin_tile.y)

    proposals = [(origin_room, origin_tile.plane, origin_tile.x, origin_tile.y)]
    claimed_by_cell = {origin_cell: origin_room.id}
    cell_by_room_id = {origin_room.id: origin_cell}

    queue = deque([(origin_room, origin_tile.plane, origin_tile.x, origin_tile.y)])

    while queue:
        room, plane, x, y = queue.popleft()
        for exit_obj in room.exits:
            offset = direction.resolve(exit_obj)
            if offset is None:
                report.unmapped_exits.append(exit_obj)
                continue

            dest_room = exit_obj.destination
            if dest_room is None:
                continue

            dx, dy, dz, kind = offset
            if kind == "vertical":
                target_plane = resolve_stacked_plane(plane, dz, create=False)
                if target_plane is None:
                    continue
                target_x, target_y = x, y
            else:
                target_plane = plane
                target_x, target_y = x + dx, y + dy

            cell = (plane_key(target_plane), target_x, target_y)

            # Already reached by an earlier path? Agreeing is fine (the
            # graph is simply cyclic); disagreeing means the room sits at
            # two coordinates at once, which is the non-Euclidean
            # topology +map/check exists to surface.
            previous_cell = cell_by_room_id.get(dest_room.id)
            if previous_cell is not None:
                if previous_cell != cell:
                    report.conflicts.append(
                        LayoutConflict(
                            room=dest_room,
                            plane=target_plane,
                            x=target_x,
                            y=target_y,
                            reason=ROOM_AMBIGUOUS,
                        )
                    )
                continue

            rival_id = claimed_by_cell.get(cell)
            if rival_id is not None:
                report.conflicts.append(
                    LayoutConflict(
                        room=dest_room,
                        plane=target_plane,
                        x=target_x,
                        y=target_y,
                        reason=CELL_CONTESTED,
                        holder_room_id=rival_id,
                    )
                )
                continue

            claimed_by_cell[cell] = dest_room.id
            cell_by_room_id[dest_room.id] = cell
            proposals.append((dest_room, target_plane, target_x, target_y))
            queue.append((dest_room, target_plane, target_x, target_y))

    return proposals, report


def _validate(proposals, report):
    """
    Phase 2: judge the proposed positions against the map as it stands.

    A proposed cell is only genuinely taken when its current occupant is
    *not itself part of this reflow* — participants are all moving at
    once, so their pre-reflow positions are about to be vacated.

    Two queries total regardless of map size: one for existing tiles on
    the affected planes (to find outside holders), one for the
    participants' current positions (to mark unchanged rooms and, for
    plan()'s benefit, to record which are pinned). A PendingPlane never
    holds a tile — it doesn't exist yet — so it's excluded from the
    first query's plane_id__in rather than passed through, which would
    otherwise ask the DB to filter on a plane with no pk.

    Returns:
        tuple: (LayoutReport, _ValidateContext). walk() uses only the
            report; plan() also needs the context for its fixed-point
            pass, at no extra query cost.
    """
    participant_ids = {room.id for room, _, _, _ in proposals}
    plane_ids = {plane.pk for _, plane, _, _ in proposals if not isinstance(plane, PendingPlane)}

    # These rows come from values_list, so the plane is a bare pk —
    # plane_key_for_id() builds the same key plane_key() would, keeping
    # one definition of a cell key rather than two that must be kept in
    # step by hand.
    holder_by_cell = {
        (plane_key_for_id(plane_id), x, y): room_id
        for plane_id, x, y, room_id in RoomTile.objects.filter(plane_id__in=plane_ids).values_list(
            "plane_id", "x", "y", "room_id"
        )
    }
    current_cell_by_room_id = {}
    pinned_by_room_id = {}
    for room_id, plane_id, x, y, pinned in RoomTile.objects.filter(
        room_id__in=participant_ids
    ).values_list("room_id", "plane_id", "x", "y", "pinned"):
        current_cell_by_room_id[room_id] = (plane_key_for_id(plane_id), x, y)
        pinned_by_room_id[room_id] = pinned

    for room, plane, x, y in proposals:
        cell = (plane_key(plane), x, y)
        holder_id = holder_by_cell.get(cell)
        if holder_id is not None and holder_id != room.id and holder_id not in participant_ids:
            report.conflicts.append(
                LayoutConflict(
                    room=room,
                    plane=plane,
                    x=x,
                    y=y,
                    reason=CELL_HELD,
                    holder_room_id=holder_id,
                )
            )
            continue
        unchanged = current_cell_by_room_id.get(room.id) == cell
        report.assignments.append((room, plane, x, y, unchanged))

    context = _ValidateContext(
        holder_by_cell=holder_by_cell,
        current_cell_by_room_id=current_cell_by_room_id,
        pinned_by_room_id=pinned_by_room_id,
    )
    return report, context


def _plan_moves(report, context):
    """
    Phase 3 (plan() only): the fixed-point pass over walk()'s assignments.

    See the module docstring for why a single pass under-reports which
    movers are blocked. This runs a worklist to the least fixed point:
    seed with movers whose target is held by a room that will not move
    (pinned, or itself rejected by _validate), then cascade — a newly
    blocked mover keeps occupying its own current cell, so whatever
    other mover wanted that cell is blocked too.

    Returns:
        ReflowPlan.
    """
    pinned_skips = []
    candidates = {}  # room_id -> (room, plane, x, y); the movable set, shrinks as we go
    for room, plane, x, y, unchanged in report.assignments:
        if unchanged:
            continue
        if context.pinned_by_room_id.get(room.id, False):
            pinned_skips.append((room, plane, x, y))
            continue
        candidates[room.id] = (room, plane, x, y)

    # Proposals are cell-unique (first-wins in _propose), so movers'
    # targets must be too — this is a genuine 1:1 map, which is what
    # makes a plain dict lookup the right tool for "who wants this cell".
    targets_by_cell = {}
    for room_id, (_room, plane, x, y) in candidates.items():
        cell = (plane_key(plane), x, y)
        assert cell not in targets_by_cell, "reflow proposals must be cell-unique"
        targets_by_cell[cell] = room_id

    blocked_reason = {}
    blocked_holder = {}
    worklist = deque()

    def _mark(room_id, holder_id, *, cascaded):
        if room_id in blocked_reason:
            return
        if cascaded:
            reason = BLOCKED_BY_BLOCKED
        elif context.pinned_by_room_id.get(holder_id, False):
            reason = BLOCKED_BY_PINNED
        else:
            reason = BLOCKED_BY_IMMOVABLE
        blocked_reason[room_id] = reason
        blocked_holder[room_id] = holder_id
        worklist.append(room_id)

    # Seed: a mover whose target is currently held by a room that isn't
    # itself a mover. Such a holder can only be an immovable participant
    # here — _validate already excluded outsider-held targets entirely
    # (they're in report.conflicts as cell_held, never in assignments).
    for room_id, (_room, plane, x, y) in candidates.items():
        cell = (plane_key(plane), x, y)
        holder_id = context.holder_by_cell.get(cell)
        if holder_id is not None and holder_id != room_id and holder_id not in candidates:
            _mark(room_id, holder_id, cascaded=False)

    # Cascade: once a room is confirmed blocked, it never vacates its own
    # current cell — so whatever mover targeted that cell is blocked too.
    while worklist:
        blocker_id = worklist.popleft()
        blocker_cell = context.current_cell_by_room_id.get(blocker_id)
        if blocker_cell is None:
            continue  # the blocker has no existing tile — nothing to keep occupied
        rival_id = targets_by_cell.get(blocker_cell)
        if rival_id is not None and rival_id != blocker_id and rival_id not in blocked_reason:
            _mark(rival_id, blocker_id, cascaded=True)

    moves = []
    blocked = []
    for room_id, (room, plane, x, y) in candidates.items():
        if room_id in blocked_reason:
            blocked.append(
                Blocked(
                    room=room,
                    plane=plane,
                    x=x,
                    y=y,
                    holder_room_id=blocked_holder[room_id],
                    reason=blocked_reason[room_id],
                )
            )
            continue
        moves.append(
            Move(
                room=room,
                plane=plane,
                x=x,
                y=y,
                created=room_id not in context.current_cell_by_room_id,
                pinned=False,  # candidates excludes pinned tiles above, by construction
            )
        )

    return ReflowPlan(
        report=report,
        moves=moves,
        pinned_skips=pinned_skips,
        blocked=blocked,
    )
