# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""django-filter FilterSets for the evennia_plots API."""

import django_filters

from evennia_plots.models import PlotThread


class PlotThreadFilter(django_filters.FilterSet):
    tag = django_filters.CharFilter(field_name="tags__name", lookup_expr="icontains")
    status = django_filters.CharFilter(field_name="status", lookup_expr="exact")

    class Meta:
        model = PlotThread
        fields = ["status"]  # noqa: RUF012
