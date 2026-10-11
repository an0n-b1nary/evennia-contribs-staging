# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""django-filter FilterSets for evennia_lore API."""

import django_filters
from django.db.models import Q

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
    kind = django_filters.CharFilter(field_name="kind", lookup_expr="exact")
    affirmation = django_filters.CharFilter(method="filter_affirmation")

    class Meta:
        model = LoreEntry
        fields = ["privacy", "status", "kind"]  # noqa: RUF012

    def filter_affirmation(self, queryset, name, value):
        """Filter by affirmation; only staff may list declined entries."""
        from evennia_lore.models import LoreEntry
        from evennia_lore.permissions import get_character_id, is_staff_user

        if not is_staff_user(self.request):
            if value == LoreEntry.Affirmation.DECLINED:
                return queryset.none()
            if value == LoreEntry.Affirmation.NONE:
                # Match the serialized state: other authors' declines read as
                # "none". Excluding them here would reveal a private decline by
                # comparing the unfiltered listing with ?affirmation=none.
                hidden_declines = Q(affirmation=LoreEntry.Affirmation.DECLINED)
                character_id = get_character_id(self.request.user) if self.request else None
                if character_id:
                    hidden_declines &= ~Q(author_id=character_id)
                return queryset.filter(Q(affirmation=value) | hidden_declines)
        return queryset.filter(affirmation=value)

    def filter_region(self, queryset, name, value):
        """Filter entries linked to a region via the LoreRegionLink bridge."""
        from evennia_lore.models import LoreRegionLink

        entry_ids = LoreRegionLink.objects.filter(region_id=value).values_list(
            "entry_id", flat=True
        )
        return queryset.filter(pk__in=entry_ids)
