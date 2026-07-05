# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.contrib import admin

from evennia_lore.models import (
    LoreAcquisition,
    LoreEntry,
    LoreInspirationCredit,
    LoreRegionLink,
    LoreSceneLink,
    LoreTag,
    LoreVersion,
    PlotLoreLink,
)


@admin.register(LoreTag)
class LoreTagAdmin(admin.ModelAdmin):
    list_display = ["name", "is_major", "created_by_name", "created_at"]  # noqa: RUF012
    list_filter = ["is_major"]  # noqa: RUF012
    search_fields = ["name"]  # noqa: RUF012
    readonly_fields = ["created_at"]  # noqa: RUF012


class LoreVersionInline(admin.TabularInline):
    model = LoreVersion
    extra = 0
    readonly_fields = ["version_number", "editor_name", "created_at", "is_rollback"]  # noqa: RUF012
    fields = ["version_number", "editor_name", "is_rollback", "created_at"]  # noqa: RUF012


class LoreSceneLinkInline(admin.TabularInline):
    model = LoreSceneLink
    extra = 0
    readonly_fields = ["scene_id", "created_by_name", "created_at"]  # noqa: RUF012
    fields = ["scene_id", "created_by_name", "created_at"]  # noqa: RUF012


class PlotLoreLinkInline(admin.TabularInline):
    model = PlotLoreLink
    extra = 0
    readonly_fields = ["thread_id", "created_by_name", "created_at"]  # noqa: RUF012
    fields = ["thread_id", "created_by_name", "created_at"]  # noqa: RUF012


class LoreRegionLinkInline(admin.TabularInline):
    model = LoreRegionLink
    extra = 0
    readonly_fields = ["region_id", "created_by_name", "created_at"]  # noqa: RUF012
    fields = ["region_id", "created_by_name", "created_at"]  # noqa: RUF012


@admin.register(LoreEntry)
class LoreEntryAdmin(admin.ModelAdmin):
    list_display = [  # noqa: RUF012
        "entry_number",
        "title",
        "status",
        "privacy",
        "author_name",
        "is_flagged",
        "created_at",
    ]
    list_filter = ["status", "privacy", "is_flagged", "is_archived"]  # noqa: RUF012
    search_fields = ["title", "body", "author_name"]  # noqa: RUF012
    readonly_fields = ["entry_number", "created_at", "updated_at", "reviewed_at"]  # noqa: RUF012
    raw_id_fields = ["author", "flagged_by", "reviewed_by"]  # noqa: RUF012
    filter_horizontal = ["tags", "rooms", "objects_tagged"]  # noqa: RUF012
    inlines = [LoreVersionInline, LoreSceneLinkInline, PlotLoreLinkInline, LoreRegionLinkInline]  # noqa: RUF012
    ordering = ["-created_at"]  # noqa: RUF012


@admin.register(LoreAcquisition)
class LoreAcquisitionAdmin(admin.ModelAdmin):
    list_display = ["character_name", "entry", "source", "acquired_at"]  # noqa: RUF012
    list_filter = ["source"]  # noqa: RUF012
    search_fields = ["character_name", "entry__title"]  # noqa: RUF012
    readonly_fields = ["acquired_at"]  # noqa: RUF012
    raw_id_fields = ["entry", "character", "shared_by"]  # noqa: RUF012


@admin.register(LoreInspirationCredit)
class LoreInspirationCreditAdmin(admin.ModelAdmin):
    list_display = ["pk", "character_name", "link", "created_at"]  # noqa: RUF012
    readonly_fields = ["created_at"]  # noqa: RUF012
    search_fields = ["character_name"]  # noqa: RUF012
