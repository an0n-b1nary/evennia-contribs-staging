# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.contrib import admin

from evennia_regions.models import Region


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = [  # noqa: RUF012
        "name",
        "member_count",
        "created_by_name",
        "created_at",
        "is_archived",
    ]
    list_filter = ["is_archived"]  # noqa: RUF012
    search_fields = ["name", "description"]  # noqa: RUF012
    readonly_fields = ["created_at", "archived_at"]  # noqa: RUF012
