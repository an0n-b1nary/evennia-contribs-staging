# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.contrib import admin

from evennia_plots.models import (
    PlotArc,
    PlotBoardLink,
    PlotBonusCredit,
    PlotCalendarLink,
    PlotParticipant,
    PlotTag,
    PlotThread,
    PlotUpdate,
    ScenePlotLink,
    ThreadLink,
)


class PlotUpdateInline(admin.TabularInline):
    model = PlotUpdate
    extra = 0
    readonly_fields = ["block_number", "author_name", "created_at", "edited_at"]  # noqa: RUF012
    fields = ["block_number", "update_type", "content", "author_name", "created_at", "edited_at"]  # noqa: RUF012


class PlotParticipantInline(admin.TabularInline):
    model = PlotParticipant
    extra = 0
    readonly_fields = ["joined_at"]  # noqa: RUF012
    fields = ["character_name", "is_active", "joined_at"]  # noqa: RUF012


class ThreadLinkInline(admin.TabularInline):
    model = ThreadLink
    fk_name = "from_thread"
    extra = 0
    readonly_fields = ["created_at"]  # noqa: RUF012
    fields = ["to_thread", "link_type", "is_accepted", "created_by_name", "created_at"]  # noqa: RUF012


class ScenePlotLinkInline(admin.TabularInline):
    model = ScenePlotLink
    extra = 0
    readonly_fields = ["scene_id", "created_by_name", "created_at"]  # noqa: RUF012
    fields = ["scene_id", "created_by_name", "created_at"]  # noqa: RUF012


class PlotCalendarLinkInline(admin.TabularInline):
    model = PlotCalendarLink
    extra = 0
    readonly_fields = ["event_id", "advance_notice_met", "created_by_name", "created_at"]  # noqa: RUF012
    fields = ["event_id", "advance_notice_met", "created_by_name", "created_at"]  # noqa: RUF012


class PlotBoardLinkInline(admin.TabularInline):
    model = PlotBoardLink
    extra = 0
    readonly_fields = ["post_id", "is_ic_post", "created_by_name", "created_at"]  # noqa: RUF012
    fields = ["post_id", "is_ic_post", "created_by_name", "created_at"]  # noqa: RUF012


@admin.register(PlotTag)
class PlotTagAdmin(admin.ModelAdmin):
    list_display = ["name", "is_major", "created_by_name", "created_at"]  # noqa: RUF012
    list_filter = ["is_major"]  # noqa: RUF012
    search_fields = ["name"]  # noqa: RUF012
    readonly_fields = ["created_at"]  # noqa: RUF012


@admin.register(PlotThread)
class PlotThreadAdmin(admin.ModelAdmin):
    list_display = [  # noqa: RUF012
        "plot_number",
        "name",
        "status",
        "privacy",
        "creator_name",
        "arc",
        "bonus_xp_computed",
        "bonus_xp_awarded",
        "created_at",
    ]
    list_filter = ["status", "privacy", "bonus_xp_awarded"]  # noqa: RUF012
    search_fields = ["name", "creator_name"]  # noqa: RUF012
    readonly_fields = ["plot_number", "created_at", "concluded_at", "archived_at"]  # noqa: RUF012
    filter_horizontal = ["tags", "invited_characters"]  # noqa: RUF012
    inlines = [  # noqa: RUF012
        PlotUpdateInline,
        PlotParticipantInline,
        ThreadLinkInline,
        ScenePlotLinkInline,
        PlotCalendarLinkInline,
        PlotBoardLinkInline,
    ]
    ordering = ["-created_at"]  # noqa: RUF012


@admin.register(PlotArc)
class PlotArcAdmin(admin.ModelAdmin):
    list_display = ["arc_number", "name", "status", "creator_name", "created_at"]  # noqa: RUF012
    list_filter = ["status"]  # noqa: RUF012
    search_fields = ["name", "creator_name"]  # noqa: RUF012
    readonly_fields = ["arc_number", "created_at", "concluded_at"]  # noqa: RUF012
    filter_horizontal = ["tags"]  # noqa: RUF012
    inlines = [PlotUpdateInline]  # noqa: RUF012
    ordering = ["-created_at"]  # noqa: RUF012


@admin.register(PlotParticipant)
class PlotParticipantAdmin(admin.ModelAdmin):
    list_display = ["character_name", "thread", "is_active", "joined_at"]  # noqa: RUF012
    list_filter = ["is_active"]  # noqa: RUF012
    search_fields = ["character_name"]  # noqa: RUF012
    readonly_fields = ["joined_at"]  # noqa: RUF012


@admin.register(PlotUpdate)
class PlotUpdateAdmin(admin.ModelAdmin):
    list_display = ["block_number", "update_type", "author_name", "thread", "arc", "created_at"]  # noqa: RUF012
    list_filter = ["update_type"]  # noqa: RUF012
    search_fields = ["author_name", "content"]  # noqa: RUF012
    readonly_fields = ["block_number", "created_at", "edited_at"]  # noqa: RUF012


@admin.register(ThreadLink)
class ThreadLinkAdmin(admin.ModelAdmin):
    list_display = [  # noqa: RUF012
        "from_thread",
        "to_thread",
        "link_type",
        "is_accepted",
        "created_by_name",
        "created_at",
    ]
    list_filter = ["link_type", "is_accepted"]  # noqa: RUF012
    readonly_fields = ["created_at"]  # noqa: RUF012


@admin.register(ScenePlotLink)
class ScenePlotLinkAdmin(admin.ModelAdmin):
    list_display = ["scene_id", "thread", "created_by_name", "created_at"]  # noqa: RUF012
    readonly_fields = ["created_at"]  # noqa: RUF012


@admin.register(PlotCalendarLink)
class PlotCalendarLinkAdmin(admin.ModelAdmin):
    list_display = ["thread", "event_id", "advance_notice_met", "created_at"]  # noqa: RUF012
    list_filter = ["advance_notice_met"]  # noqa: RUF012
    readonly_fields = ["created_at"]  # noqa: RUF012


@admin.register(PlotBoardLink)
class PlotBoardLinkAdmin(admin.ModelAdmin):
    list_display = ["thread", "post_id", "is_ic_post", "created_by_name", "created_at"]  # noqa: RUF012
    list_filter = ["is_ic_post"]  # noqa: RUF012
    readonly_fields = ["created_at"]  # noqa: RUF012


@admin.register(PlotBonusCredit)
class PlotBonusCreditAdmin(admin.ModelAdmin):
    list_display = ["thread", "character_id", "character_name", "created_at"]  # noqa: RUF012
    search_fields = ["character_name"]  # noqa: RUF012
    readonly_fields = ["created_at"]  # noqa: RUF012
