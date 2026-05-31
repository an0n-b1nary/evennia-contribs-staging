# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.contrib import admin

from evennia_rptracker.models import RPSession, RPSessionPartner


class RPSessionPartnerInline(admin.TabularInline):
    model = RPSessionPartner
    extra = 0
    readonly_fields = ["partner", "partner_name", "pose_count"]  # noqa: RUF012


@admin.register(RPSession)
class RPSessionAdmin(admin.ModelAdmin):
    list_display = [  # noqa: RUF012
        "pk",
        "character_name",
        "status",
        "room_name",
        "pose_count",
        "started_at",
        "ended_at",
        "ended_manually",
        "xp_awarded",
    ]
    list_filter = ["status", "ended_manually", "xp_awarded"]  # noqa: RUF012
    search_fields = ["character_name", "room_name", "flag_reason"]  # noqa: RUF012
    readonly_fields = [  # noqa: RUF012
        "started_at",
        "activated_at",
        "ended_at",
        "flagged_at",
        "flagged_by",
        "flagged_by_name",
    ]
    inlines = [RPSessionPartnerInline]  # noqa: RUF012


@admin.register(RPSessionPartner)
class RPSessionPartnerAdmin(admin.ModelAdmin):
    list_display = ["pk", "session", "partner_name", "pose_count"]  # noqa: RUF012
    search_fields = ["partner_name"]  # noqa: RUF012
