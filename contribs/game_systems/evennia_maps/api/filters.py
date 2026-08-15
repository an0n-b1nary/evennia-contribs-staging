# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""django-filter FilterSet for the evennia_maps REST API. Requires [web] extra."""

import django_filters

from evennia_maps.models import MapPlane


class PlaneFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(field_name="name", lookup_expr="icontains")
    zstack = django_filters.CharFilter(field_name="zstack", lookup_expr="exact")

    class Meta:
        model = MapPlane
        fields = ["zstack"]  # noqa: RUF012
