# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""django-filter FilterSets for evennia_lore API."""

import django_filters

from evennia_lore.models import LoreEntry, LoreTag


class LoreTagFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(field_name="name", lookup_expr="icontains")
    is_major = django_filters.BooleanFilter(field_name="is_major")

    class Meta:
        model = LoreTag
        fields = ["name", "is_major"]  # noqa: RUF012


class LoreEntryFilter(django_filters.FilterSet):
    tag = django_filters.CharFilter(field_name="tags__name", lookup_expr="icontains")
    privacy = django_filters.CharFilter(field_name="privacy", lookup_expr="exact")
    status = django_filters.CharFilter(field_name="status", lookup_expr="exact")
    region = django_filters.NumberFilter(method="filter_region")

    class Meta:
        model = LoreEntry
        fields = ["privacy", "status"]  # noqa: RUF012

    def filter_region(self, queryset, name, value):
        """Filter entries linked to a region via the LoreRegionLink bridge."""
        from evennia_lore.models import LoreRegionLink

        entry_ids = LoreRegionLink.objects.filter(region_id=value).values_list(
            "entry_id", flat=True
        )
        return queryset.filter(pk__in=entry_ids)
