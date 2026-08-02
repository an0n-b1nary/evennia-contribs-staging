# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Web views for evennia_regions. Requires [web] extra.

Read-only views for browsing geographic regions and their member rooms.

**Privacy.** The member-room list names rooms and prints their dbrefs, so it
is filtered through evennia_regions.permissions.is_room_web_visible() for
non-staff visitors. Membership *counts* that would include hidden rooms are
staff-only for the same reason: publishing one tells a visitor how many
rooms they are not being shown.

Views:
    RegionListView   — /regions/       paginated list of all regions
    RegionDetailView — /regions/<pk>/  region info + member rooms
"""

from django.views.generic import DetailView, ListView

from evennia_regions.models import Region
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
        context["memberships"] = memberships
        return context
