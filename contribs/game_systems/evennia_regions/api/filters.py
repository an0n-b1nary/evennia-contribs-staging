# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""django-filter FilterSet for the evennia_regions REST API. Requires [web] extra."""

import django_filters

from evennia_regions.models import Region


class RegionFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(field_name="name", lookup_expr="icontains")

    class Meta:
        model = Region
        fields = ["name"]  # noqa: RUF012
