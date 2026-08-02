# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Region management command for evennia_regions.

Creates, views, and assigns rooms to geographic regions. A room may belong
to several regions at once (many-to-many). One membership per room may be
flagged the primary — the deterministic answer scalar readers use.

Staff (REGIONS_STAFF_LOCK, default Builder+) manage region definitions and
membership. All players can view regions and check which region(s) their
current room belongs to.

Add to your CharacterCmdSet::

    from evennia_regions.commands import CmdRegion

Settings:
    REGIONS_STAFF_LOCK — lock string for staff operations (default "cmd:perm(Builder)").
"""

from django.db import transaction
from evennia.commands.default.muxcommand import MuxCommand

from evennia_links import EditingMixin
from evennia_regions.models import Region, RegionMembership
from evennia_regions.permissions import is_staff


class CmdRegion(EditingMixin, MuxCommand):
    """
    View and manage geographic regions.

    Usage:
        +region                              - List all regions with room counts
        +region/view <name>                  - View a region's rooms and details
        +region/here                         - Show the region(s) of your current room
        +region/create <name>=<description>  - (Staff) Create a new region
        +region/edit <name>                  - (Staff) Edit region description
        +region/add-room <name>=<#dbref>     - (Staff) Add a room to a region
        +region/remove-room <name>=<#dbref>  - (Staff) Remove a room from a region
        +region/here-add <name>              - (Staff) Add current room to a region
        +region/primary <name>[=<#dbref>]    - (Staff) Set a room's primary region
                                               (omit the dbref for current room)
    """

    key = "+region"
    aliases = []  # noqa: RUF012
    help_category = "Building"
    locks = "cmd:all()"

    def func(self):
        if not self.switches:
            self._do_list()
            return

        switch = self.switches[0].lower()
        dispatch = {
            "view": self._do_view,
            "here": self._do_here,
            "create": self._do_create,
            "edit": self._do_edit,
            "add-room": self._do_add_room,
            "remove-room": self._do_remove_room,
            "here-add": self._do_here_add,
            "primary": self._do_primary,
        }
        handler = dispatch.get(switch)
        if handler:
            handler()
        else:
            self.caller.msg(f"|rUnknown switch: /{switch}|n")

    # ------------------------------------------------------------------
    # Read-only switches
    # ------------------------------------------------------------------

    def _do_list(self):
        regions = Region.objects.all().order_by("name")
        if not regions.exists():
            self.caller.msg("No regions have been defined yet.")
            return
        lines = ["|wRegions|n", "-" * 50]
        for r in regions:
            count = r.member_count()
            desc = r.description
            snippet = (desc[:57] + "…") if len(desc) > 60 else desc
            room_label = f"{count} room{'s' if count != 1 else ''}"
            lines.append(f"  |w{r.name}|n ({room_label}) — {snippet}")
        lines.append("-" * 50)
        self.caller.msg("\n".join(lines))

    def _do_view(self):
        name = self.args.strip()
        if not name:
            self.caller.msg("Usage: +region/view <name>")
            return
        try:
            region = Region.objects.get(name__iexact=name)
        except Region.DoesNotExist:
            self.caller.msg(f"|rNo region named '{name}' found.|n")
            return

        members = region.memberships.order_by("room_name")
        lines = [
            f"|wRegion: {region.name}|n",
            f"Created by: {region.created_by_name or 'Unknown'} on "
            f"{region.created_at.strftime('%Y-%m-%d')}",
            f"Description: {region.description or '(none)'}",
            f"Rooms ({region.member_count()}):",
        ]
        if members.exists():
            for m in members:
                star = " |y(primary)|n" if m.is_primary else ""
                lines.append(f"  |w#{m.room_id}|n {m.room_name}{star}")
        else:
            lines.append("  (no rooms assigned)")
        self.caller.msg("\n".join(lines))

    def _do_here(self):
        room = self.caller.location
        if not room:
            self.caller.msg("You have no location.")
            return
        memberships = list(
            RegionMembership.objects.select_related("region")
            .filter(room=room)
            .order_by("region__name")
        )
        if not memberships:
            self.caller.msg(f"This room (|w{room.key}|n) has not been assigned to any region.")
            return
        lines = [f"This room (|w{room.key}|n) is part of:"]
        for m in memberships:
            star = " |y(primary)|n" if m.is_primary else ""
            lines.append(f"  |w{m.region.name}|n{star}")
        self.caller.msg("\n".join(lines))

    # ------------------------------------------------------------------
    # Staff-only switches
    # ------------------------------------------------------------------

    def _do_create(self):
        if not is_staff(self.caller):
            self.caller.msg("|rYou need staff permissions to create regions.|n")
            return
        if not self.lhs or not self.rhs:
            self.caller.msg("Usage: +region/create <name>=<description>")
            return
        name = self.lhs.strip()
        description = self.rhs.strip()
        if Region.objects.filter(name__iexact=name).exists():
            self.caller.msg(f"|rA region named '{name}' already exists.|n")
            return
        region = Region.create_region(name=name, creator=self.caller, description=description)
        self.caller.msg(f"Created region |w{region.name}|n.")

    def _do_edit(self):
        if not is_staff(self.caller):
            self.caller.msg("|rYou need staff permissions to edit regions.|n")
            return
        name = self.args.strip()
        if not name:
            self.caller.msg("Usage: +region/edit <name>")
            return
        try:
            region = Region.objects.get(name__iexact=name)
        except Region.DoesNotExist:
            self.caller.msg(f"|rNo region named '{name}' found.|n")
            return
        self.start_edit(region, field_name="description")

    def _do_add_room(self):
        if not is_staff(self.caller):
            self.caller.msg("|rYou need staff permissions to modify region membership.|n")
            return
        if not self.lhs or not self.rhs:
            self.caller.msg("Usage: +region/add-room <name>=<#dbref>")
            return
        region_name = self.lhs.strip()
        room_ref = self.rhs.strip()
        try:
            region = Region.objects.get(name__iexact=region_name)
        except Region.DoesNotExist:
            self.caller.msg(f"|rNo region named '{region_name}' found.|n")
            return
        room = self.caller.search(room_ref, global_search=True)
        if not room:
            return
        self._assign_room_to_region(room, region)

    def _do_remove_room(self):
        if not is_staff(self.caller):
            self.caller.msg("|rYou need staff permissions to modify region membership.|n")
            return
        if not self.lhs or not self.rhs:
            self.caller.msg("Usage: +region/remove-room <name>=<#dbref>")
            return
        region_name = self.lhs.strip()
        room_ref = self.rhs.strip()
        try:
            region = Region.objects.get(name__iexact=region_name)
        except Region.DoesNotExist:
            self.caller.msg(f"|rNo region named '{region_name}' found.|n")
            return
        room = self.caller.search(room_ref, global_search=True)
        if not room:
            return
        membership = RegionMembership.objects.filter(region=region, room=room).first()
        if not membership:
            self.caller.msg(f"|rRoom #{room.id} ({room.key}) is not in the {region.name} region.|n")
            return
        was_primary = membership.is_primary
        with transaction.atomic():
            membership.delete()
            # Keep the "a room with memberships has a primary" invariant:
            # promote the earliest survivor when the primary was removed.
            successor = (
                RegionMembership.objects.filter(room=room).order_by("created_at", "pk").first()
                if was_primary
                else None
            )
            if successor:
                successor.is_primary = True
                successor.save(update_fields=["is_primary"])
        self.caller.msg(f"Removed |w{room.key}|n from region |w{region.name}|n.")
        if successor:
            self.caller.msg(f"|w{successor.region.name}|n is now the primary region for this room.")

    def _do_here_add(self):
        if not is_staff(self.caller):
            self.caller.msg("|rYou need staff permissions to modify region membership.|n")
            return
        name = self.args.strip()
        if not name:
            self.caller.msg("Usage: +region/here-add <name>")
            return
        room = self.caller.location
        if not room:
            self.caller.msg("You have no location.")
            return
        try:
            region = Region.objects.get(name__iexact=name)
        except Region.DoesNotExist:
            self.caller.msg(f"|rNo region named '{name}' found.|n")
            return
        self._assign_room_to_region(room, region)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _assign_room_to_region(self, room, region):
        """Add room to region (M2M). No-op if already a member; the room's
        first-ever membership is flagged primary automatically."""
        existing = RegionMembership.objects.filter(room=room, region=region).first()
        if existing:
            self.caller.msg(f"|w{room.key}|n is already in region |w{region.name}|n.")
            return
        is_first = not RegionMembership.objects.filter(room=room).exists()
        RegionMembership.objects.create(
            region=region,
            room=room,
            room_name=room.key,
            created_by=self.caller,
            created_by_name=self.caller.key,
            is_primary=is_first,
        )
        self.caller.msg(f"Added |w{room.key}|n to region |w{region.name}|n.")

    def _do_primary(self):
        if not is_staff(self.caller):
            self.caller.msg("|rYou need staff permissions to set a room's primary region.|n")
            return
        region_name = self.lhs.strip()
        if not region_name:
            self.caller.msg("Usage: +region/primary <name>[=<#dbref>]")
            return
        try:
            region = Region.objects.get(name__iexact=region_name)
        except Region.DoesNotExist:
            self.caller.msg(f"|rNo region named '{region_name}' found.|n")
            return
        # No room given → operate on the caller's current room (the "here" form).
        if self.rhs:
            room = self.caller.search(self.rhs.strip(), global_search=True)
            if not room:
                return
        else:
            room = self.caller.location
            if not room:
                self.caller.msg("You have no location.")
                return
        try:
            membership = RegionMembership.objects.get(room=room, region=region)
        except RegionMembership.DoesNotExist:
            self.caller.msg(f"|r{room.key} is not a member of region {region.name}.|n")
            return
        with transaction.atomic():
            RegionMembership.objects.filter(room=room, is_primary=True).update(is_primary=False)
            membership.is_primary = True
            membership.save(update_fields=["is_primary"])
        self.caller.msg(f"|w{region.name}|n is now the primary region for |w{room.key}|n.")
