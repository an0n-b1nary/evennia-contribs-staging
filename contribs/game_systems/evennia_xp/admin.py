# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django admin registration for evennia_xp."""

from django.contrib import admin

from evennia_xp.models import CharacterXP, XPLog


@admin.register(XPLog)
class XPLogAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "character_name",
        "character_id",
        "amount",
        "source_type",
        "source_ref_id",
        "week",
        "multiplier_applied",
        "awarded_at",
        "granted_by_name",
    )
    list_filter = ("source_type", "week")
    search_fields = ("character_name", "reason", "granted_by_name")
    readonly_fields = (
        "character_id",
        "character_name",
        "amount",
        "source_type",
        "source_ref_id",
        "week",
        "multiplier_applied",
        "awarded_at",
        "granted_by_id",
        "granted_by_name",
    )
    ordering = ("-awarded_at",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CharacterXP)
class CharacterXPAdmin(admin.ModelAdmin):
    list_display = (
        "character_name",
        "character_id",
        "total_earned",
        "total_spent",
        "current_balance",
        "last_payout_week",
        "updated_at",
    )
    search_fields = ("character_name",)
    readonly_fields = (
        "character_id",
        "character_name",
        "total_earned",
        "total_spent",
        "current_balance",
        "last_payout_week",
        "updated_at",
    )
    ordering = ("-total_earned",)

    def has_add_permission(self, request):
        return False
