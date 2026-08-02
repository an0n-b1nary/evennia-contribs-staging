# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Map management command for evennia_maps.

The map grows on its own as builders `dig`/`@tunnel` — the exit-creation
signal listener (listeners.py) auto-places a destination room relative to
its mapped source. +map is the manual override/inspection layer on top of
that: bootstrapping a room onto a fresh plane, fixing a conflict, pinning
a landmark room so auto-placement/reflow never moves it, and reconciling
drift.

Staff (MAPS_STAFF_LOCK, default Builder+) manage placement; all players
can view.

Add to your CharacterCmdSet::

    from evennia_maps.commands import CmdMap

Settings:
    MAPS_STAFF_LOCK — lock string for staff operations (default "cmd:perm(Builder)").
"""

from django.db import IntegrityError, transaction
from evennia.commands.default.muxcommand import MuxCommand

from evennia_maps import layout, placement
from evennia_maps.direction import resolve as resolve_direction
from evennia_maps.models import MapPlane, RoomTile
from evennia_maps.permissions import is_staff


def _room_ref(caller, ref):
    room = caller.search(ref, global_search=True)
    return room


def _holder_label(holder_room_id):
    holder = RoomTile.objects.filter(room_id=holder_room_id).first()
    return (holder.room_name if holder else None) or f"#{holder_room_id}"


def _explain(conflict):
    """Render a LayoutConflict reason as a builder-facing sentence."""
    if conflict.reason == layout.ROOM_AMBIGUOUS:
        return "reachable at two different coordinates (exits disagree)"
    holder_label = _holder_label(conflict.holder_room_id)
    if conflict.reason == layout.CELL_CONTESTED:
        return f"same cell as {holder_label} (overlapping geometry)"
    return f"cell held by {holder_label}, which this reflow does not move"


def _explain_blocked(blocked):
    """Render a layout.Blocked reason as a builder-facing sentence."""
    holder_label = _holder_label(blocked.holder_room_id)
    if blocked.reason == layout.BLOCKED_BY_PINNED:
        return f"held by {holder_label}, which is pinned"
    if blocked.reason == layout.BLOCKED_BY_BLOCKED:
        return f"held by {holder_label}, which is itself blocked"
    return f"held by {holder_label}, which this reflow does not move"


class CmdMap(MuxCommand):
    """
    View and manage the room map.

    Usage:
        +map                            - Render the map of your current plane
        +map/here                       - Same as above
        +map/place <#room>=<plane>      - (Staff) Place a room at (0,0) on
                                           <plane>; a new plane name creates an
                                           interior plane
        +map/move <#room>=<x>,<y>       - (Staff) Reposition a placed room
        +map/unplace <#room>            - (Staff) Remove a room from the map
        +map/pin <#room>                - (Staff) Protect a tile from
                                           auto-placement/reflow
        +map/unpin <#room>              - (Staff) Clear the pin
        +map/reflow <#room>             - (Staff) Dry-run BFS from <#room>;
                                           reports the moves a reflow would make
        +map/reflow/apply <#room>       - (Staff) Writes exactly those moves,
                                           in one transaction (never moves a
                                           pinned tile; a move blocked by one
                                           doesn't stop the rest of the map)
        +map/check                      - Lint: unmapped neighbors, missing
                                           terrain snapshots
    """

    key = "+map"
    aliases = []  # noqa: RUF012
    help_category = "Building"
    locks = "cmd:all()"

    def func(self):
        if not self.switches:
            self._do_render()
            return

        switch = self.switches[0].lower()
        dispatch = {
            "here": self._do_render,
            "place": self._do_place,
            "move": self._do_move,
            "unplace": self._do_unplace,
            "pin": lambda: self._do_pin(True),
            "unpin": lambda: self._do_pin(False),
            "reflow": self._do_reflow,
            "check": self._do_check,
        }
        handler = dispatch.get(switch)
        if handler:
            handler()
        else:
            self.caller.msg(f"|rUnknown switch: /{switch}|n")

    # ------------------------------------------------------------------
    # Read-only
    # ------------------------------------------------------------------

    def _do_render(self):
        room = self.caller.location
        if not room:
            self.caller.msg("You have no location.")
            return
        tile = RoomTile.objects.filter(room=room).first()
        if not tile:
            self.caller.msg("Your current room isn't on the map yet.")
            return

        radius = 10
        tiles = RoomTile.objects.filter(
            plane=tile.plane,
            x__gte=tile.x - radius,
            x__lte=tile.x + radius,
            y__gte=tile.y - radius,
            y__lte=tile.y + radius,
        )
        by_coord = {(t.x, t.y): t for t in tiles}

        xs = [c[0] for c in by_coord] or [tile.x]
        ys = [c[1] for c in by_coord] or [tile.y]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        lines = [f"|w{tile.plane.name}|n (elevation {tile.plane.elevation})"]
        for y in range(max_y, min_y - 1, -1):
            row = []
            for x in range(min_x, max_x + 1):
                if (x, y) == (tile.x, tile.y):
                    row.append("|y@|n")
                elif (x, y) in by_coord:
                    row.append("|w#|n")
                else:
                    row.append("|x.|n")
            lines.append("".join(row))
        lines.append(f"|y@|n = here   |w#|n = room   ({len(by_coord)} tile(s) shown)")
        self.caller.msg("\n".join(lines))

    # ------------------------------------------------------------------
    # Staff-only
    # ------------------------------------------------------------------

    def _do_place(self):
        if not is_staff(self.caller):
            self.caller.msg("|rYou need staff permissions to place rooms.|n")
            return
        if not self.lhs or not self.rhs:
            self.caller.msg("Usage: +map/place <#room>=<plane>")
            return
        room = _room_ref(self.caller, self.lhs.strip())
        if not room:
            return
        plane_name = self.rhs.strip()
        plane = MapPlane.objects.filter(name__iexact=plane_name).first()
        plane_created = plane is None
        if plane is None:
            plane = MapPlane.objects.create(
                name=plane_name,
                created_by=self.caller,
                created_by_name=self.caller.key,
            )
        result = placement.place_tile(room, plane, 0, 0, actor=self.caller)
        if isinstance(result, placement.Conflict):
            self.caller.msg(
                f"|r(0,0) on {plane.name} is already held by "
                f"{result.holder.room_name or f'#{result.holder.room_id}'}.|n Use +map/move instead."
            )
            return
        verb = "created and placed on" if plane_created else "placed on"
        self.caller.msg(f"|w{room.key}|n {verb} |w{plane.name}|n at (0, 0).")

    def _do_move(self):
        if not is_staff(self.caller):
            self.caller.msg("|rYou need staff permissions to move rooms.|n")
            return
        if not self.lhs or not self.rhs:
            self.caller.msg("Usage: +map/move <#room>=<x>,<y>")
            return
        room = _room_ref(self.caller, self.lhs.strip())
        if not room:
            return
        try:
            x_str, y_str = self.rhs.split(",")
            x, y = int(x_str.strip()), int(y_str.strip())
        except ValueError:
            self.caller.msg("|rCoordinates must be <x>,<y> integers.|n")
            return
        result = placement.move_tile(room, x, y, actor=self.caller)
        if result is None:
            self.caller.msg(f"|r{room.key} isn't on the map yet. Use +map/place first.|n")
            return
        if isinstance(result, placement.Conflict):
            self.caller.msg(
                f"|r({x}, {y}) is already held by "
                f"{result.holder.room_name or f'#{result.holder.room_id}'}.|n"
            )
            return
        self.caller.msg(f"Moved |w{room.key}|n to ({x}, {y}) on |w{result.plane.name}|n.")

    def _do_unplace(self):
        if not is_staff(self.caller):
            self.caller.msg("|rYou need staff permissions to unplace rooms.|n")
            return
        name = self.args.strip()
        if not name:
            self.caller.msg("Usage: +map/unplace <#room>")
            return
        room = _room_ref(self.caller, name)
        if not room:
            return
        if placement.unplace_tile(room):
            self.caller.msg(f"Removed |w{room.key}|n from the map.")
        else:
            self.caller.msg(f"|r{room.key} wasn't on the map.|n")

    def _do_pin(self, pinned):
        if not is_staff(self.caller):
            self.caller.msg("|rYou need staff permissions to pin rooms.|n")
            return
        name = self.args.strip()
        if not name:
            self.caller.msg(f"Usage: +map/{'pin' if pinned else 'unpin'} <#room>")
            return
        room = _room_ref(self.caller, name)
        if not room:
            return
        tile = placement.set_pin(room, pinned)
        if tile is None:
            self.caller.msg(f"|r{room.key} isn't on the map yet.|n")
            return
        state = "pinned" if pinned else "unpinned"
        self.caller.msg(f"|w{room.key}|n is now {state}.")

    def _do_reflow(self):
        if not is_staff(self.caller):
            self.caller.msg("|rYou need staff permissions to reflow the map.|n")
            return
        name = self.args.strip()
        if not name:
            self.caller.msg("Usage: +map/reflow[/apply] <#room>")
            return
        room = _room_ref(self.caller, name)
        if not room:
            return

        apply = "apply" in self.switches
        written = 0
        try:
            if apply:
                # plan() and apply_plan() share one transaction so a
                # write that lands between them (e.g. the exit-creation
                # listener firing on a `dig` elsewhere) rolls back
                # cleanly instead of leaving a partial reflow.
                with transaction.atomic():
                    result = layout.plan(room)
                    written = placement.apply_plan(result, actor=self.caller)
            else:
                result = layout.plan(room)
        except ValueError:
            self.caller.msg(f"|r{room.key} isn't on the map yet. Use +map/place first.|n")
            return
        except IntegrityError:
            self.caller.msg("|rMap changed underneath this reflow; nothing was written.|n")
            return

        # Dry-run and apply render the same ReflowPlan, so what apply
        # writes is always exactly what the dry run promised.
        lines = [f"|wReflow from {room.key}|n ({'applying' if apply else 'dry run'}):"]
        for move in result.moves:
            lines.append(f"  {move.room.key} -> {move.plane.name}({move.x},{move.y})")
        for skip_room, plane, x, y in result.pinned_skips:
            lines.append(f"  |x(skipped, pinned)|n {skip_room.key} -> {plane.name}({x},{y})")
        for b in result.blocked:
            lines.append(
                f"  |r(blocked)|n {b.room.key} -> {b.plane.name}({b.x},{b.y}) "
                f"— {_explain_blocked(b)}"
            )

        if result.report.conflicts:
            lines.append("|rConflicts:|n")
            for c in result.report.conflicts:
                lines.append(f"  {c.room.key} at {c.plane.name}({c.x},{c.y}) — {_explain(c)}")

        summary = (
            f"{len(result.report.assignments)} room(s) reachable, "
            f"{len(result.report.conflicts)} conflict(s), "
            f"{len(result.pinned_skips)} pinned tile(s) skipped, "
            f"{len(result.blocked)} blocked"
        )
        if apply:
            summary += f", {written} written"
        else:
            summary += f", {len(result.moves)} move(s) planned"
        lines.append(summary)
        self.caller.msg("\n".join(lines))

    def _do_check(self):
        if not is_staff(self.caller):
            self.caller.msg("|rYou need staff permissions to run map checks.|n")
            return
        missing_terrain = RoomTile.objects.filter(terrain="").select_related("plane")
        # One query for the whole placed-room set, rather than an
        # .exists() per exit per tile — this loop walks the entire map.
        placed_room_ids = set(RoomTile.objects.values_list("room_id", flat=True))
        gaps = []
        for tile in RoomTile.objects.select_related("plane").all():
            for exit_obj in tile.room.exits:
                if resolve_direction(exit_obj) is None:
                    continue
                dest = exit_obj.destination
                if dest and dest.id not in placed_room_ids:
                    gaps.append((tile, exit_obj, dest))

        lines = ["|wMap check|n"]
        lines.append(f"Tiles missing terrain: {missing_terrain.count()}")
        for t in missing_terrain[:10]:
            lines.append(f"  #{t.room_id} {t.room_name} on {t.plane.name}")
        lines.append(f"Unmapped neighbors (canonical exit, no destination tile): {len(gaps)}")
        for tile, exit_obj, dest in gaps[:10]:
            lines.append(f"  {tile.room_name} --{exit_obj.key}--> {dest.key} (unmapped)")
        self.caller.msg("\n".join(lines))
