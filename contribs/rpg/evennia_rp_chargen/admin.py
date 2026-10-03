# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django admin for evennia_rp_chargen."""

from django.contrib import admin

from evennia_rp_chargen.models import CharacterBuild


@admin.register(CharacterBuild)
class CharacterBuildAdmin(admin.ModelAdmin):
    list_display = ("character_name", "status", "finalized_at", "reviewed_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("character_name",)
    readonly_fields = ("character", "created_at", "updated_at", "finalized_at", "reviewed_at")
