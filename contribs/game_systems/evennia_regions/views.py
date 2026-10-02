# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Web views for evennia_regions. Requires [web] extra.

Read-only views for browsing geographic regions and their member rooms.

**Privacy.** The member-room list names rooms and links to their public detail
pages, so it is filtered through evennia_regions.permissions.is_room_web_visible() for
non-staff visitors. Membership *counts* that would include hidden rooms are
staff-only for the same reason: publishing one tells a visitor how many
rooms they are not being shown.

Views:
    RegionListView   — /regions/       paginated list of all regions
    RegionDetailView — /regions/<pk>/  region info + member rooms
"""

from django.apps import apps
from django.conf import settings
from django.http import Http404
from django.urls import NoReverseMatch, reverse
from django.views.generic import DetailView, ListView
from evennia.objects.models import ObjectDB
from evennia.objects.objects import DefaultRoom

from evennia_regions.models import Region, RegionMembership
from evennia_regions.permissions import is_room_web_visible, is_staff_user


class RegionListView(ListView):
    """Paginated list of all regions."""

    model = Region
    template_name = "evennia_regions/region_list.html"
    context_object_name = "regions"
    paginate_by = 25

    def get_queryset(self):
        return Region.objects.all().order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Regions"
        # Region.member_count() counts every membership, including rooms the
        # detail page withholds — see the module docstring. Room privacy
        # lives in Evennia Attributes rather than a column, so there is no
        # cheap SQL-level "visible member count" to show instead.
        context["show_member_counts"] = is_staff_user(self.request)
        return context


class RegionDetailView(DetailView):
    """Region detail: description and member rooms."""

    model = Region
    template_name = "evennia_regions/region_detail.html"
    context_object_name = "region"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        staff = is_staff_user(self.request)
        memberships = self.object.memberships.select_related("room").order_by("room_name")
        if not staff:
            memberships = [m for m in memberships if is_room_web_visible(m.room)]
        for membership in memberships:
            try:
                membership.room_url = reverse(
                    "evennia_regions:room-detail", kwargs={"pk": membership.room_id}
                )
            except NoReverseMatch:
                membership.room_url = ""
        context["memberships"] = memberships
        context["linked_lore"] = _linked_lore(self.object)
        return context


def _linked_lore(region):
    """Resolve published lore links when the optional contrib is installed."""
    try:
        link_model = apps.get_model(
            getattr(settings, "REGIONS_LORE_APP_LABEL", "evennia_lore"), "LoreRegionLink"
        )
        lore_model = apps.get_model(
            getattr(settings, "REGIONS_LORE_APP_LABEL", "evennia_lore"), "LoreEntry"
        )
    except (LookupError, ValueError):
        return []
    entry_ids = link_model.objects.filter(region_id=region.pk).values_list("entry_id", flat=True)
    entries = list(
        lore_model.objects.filter(
            pk__in=entry_ids,
            status=lore_model.Status.PUBLISHED,
            is_archived=False,
        ).order_by("entry_number")
    )
    for entry in entries:
        try:
            entry.entry_url = reverse("lore-detail", kwargs={"pk": entry.pk})
        except NoReverseMatch:
            entry.entry_url = ""
    return entries


class RoomDetailView(DetailView):
    """Show a visible room and its installed region/map destinations."""

    model = ObjectDB
    template_name = "evennia_regions/room_detail.html"
    context_object_name = "room"

    def get_object(self, queryset=None):
        room = super().get_object(queryset)
        if not room.is_typeclass(DefaultRoom, exact=False) or (
            not is_staff_user(self.request) and not is_room_web_visible(room)
        ):
            raise Http404
        return room

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        room = self.object
        context["page_title"] = room.key
        context["description"] = getattr(getattr(room, "db", None), "desc", "") or ""
        # RegionMembership uses related_name="+", so query by room explicitly.
        context["memberships"] = list(
            RegionMembership.objects.filter(room=room, region__is_archived=False).select_related(
                "region"
            )
        )
        context["tiles"] = _room_tiles(room)
        return context


def _room_tiles(room):
    """Return map placements without making maps a hard dependency."""
    try:
        tile_model = apps.get_model(
            getattr(settings, "REGIONS_MAPS_APP_LABEL", "evennia_maps"), "RoomTile"
        )
    except (LookupError, ValueError):
        return []
    tiles = list(
        tile_model.objects.filter(room=room, plane__is_archived=False).select_related("plane")
    )
    for tile in tiles:
        try:
            tile.map_url = reverse("evennia_maps:plane-detail", kwargs={"pk": tile.plane_id})
        except NoReverseMatch:
            tile.map_url = ""
    return tiles
