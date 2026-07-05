# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django admin registration for evennia_calendar."""

from django.contrib import admin

from evennia_calendar.models import (
    RSVP,
    CalendarEvent,
    ClusterRSVP,
    ClusterRSVPPreference,
    EventCluster,
    EventExclusion,
    EventTag,
    PriorityToken,
    SceneCalendarLink,
)


class RSVPInline(admin.TabularInline):
    model = RSVP
    extra = 0
    readonly_fields = ["created_at", "updated_at"]  # noqa: RUF012
    fields = [  # noqa: RUF012
        "character_name",
        "status",
        "waitlist_position",
        "cluster_rsvp",
        "created_at",
    ]


class ClusterRSVPPreferenceInline(admin.TabularInline):
    model = ClusterRSVPPreference
    extra = 0
    fields = ["rank", "event"]  # noqa: RUF012


class ClusterRSVPInline(admin.TabularInline):
    model = ClusterRSVP
    extra = 0
    readonly_fields = ["created_at", "updated_at"]  # noqa: RUF012
    fields = ["character_name", "status", "created_at"]  # noqa: RUF012


@admin.register(EventTag)
class EventTagAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]  # noqa: RUF012
    search_fields = ["name"]  # noqa: RUF012


@admin.register(EventCluster)
class EventClusterAdmin(admin.ModelAdmin):
    list_display = ["pk", "title", "creator_name", "is_locked", "created_at"]  # noqa: RUF012
    list_filter = ["is_locked"]  # noqa: RUF012
    search_fields = ["title", "creator_name"]  # noqa: RUF012
    readonly_fields = ["created_at", "updated_at"]  # noqa: RUF012
    inlines = [ClusterRSVPInline]  # noqa: RUF012


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = [  # noqa: RUF012
        "pk",
        "title",
        "scheduled_time",
        "emphasis",
        "is_staff_event",
        "participant_cap",
        "is_cancelled",
        "cluster",
    ]
    list_filter = ["emphasis", "is_staff_event", "is_cancelled"]  # noqa: RUF012
    search_fields = ["title", "creator_name"]  # noqa: RUF012
    readonly_fields = ["created_at", "updated_at", "lottery_drawn_at"]  # noqa: RUF012
    filter_horizontal = ["tags"]  # noqa: RUF012
    inlines = [RSVPInline]  # noqa: RUF012


@admin.register(RSVP)
class RSVPAdmin(admin.ModelAdmin):
    list_display = [  # noqa: RUF012
        "pk",
        "character_name",
        "event",
        "status",
        "waitlist_position",
        "created_at",
    ]
    list_filter = ["status"]  # noqa: RUF012
    search_fields = ["character_name"]  # noqa: RUF012
    readonly_fields = ["created_at", "updated_at"]  # noqa: RUF012


@admin.register(ClusterRSVP)
class ClusterRSVPAdmin(admin.ModelAdmin):
    list_display = ["pk", "character_name", "cluster", "status", "created_at"]  # noqa: RUF012
    list_filter = ["status"]  # noqa: RUF012
    search_fields = ["character_name"]  # noqa: RUF012
    readonly_fields = ["created_at", "updated_at"]  # noqa: RUF012
    inlines = [ClusterRSVPPreferenceInline]  # noqa: RUF012


@admin.register(PriorityToken)
class PriorityTokenAdmin(admin.ModelAdmin):
    list_display = [  # noqa: RUF012
        "pk",
        "character_name",
        "scope",
        "source_event",
        "source_cluster",
        "is_redeemed",
        "created_at",
    ]
    list_filter = ["scope"]  # noqa: RUF012
    search_fields = ["character_name"]  # noqa: RUF012
    readonly_fields = ["created_at"]  # noqa: RUF012


@admin.register(EventExclusion)
class EventExclusionAdmin(admin.ModelAdmin):
    list_display = ["pk", "event_a", "event_b", "creator_name", "created_at"]  # noqa: RUF012
    readonly_fields = ["created_at"]  # noqa: RUF012


@admin.register(SceneCalendarLink)
class SceneCalendarLinkAdmin(admin.ModelAdmin):
    list_display = ["pk", "event", "scene_id", "created_at"]  # noqa: RUF012
    readonly_fields = ["created_at"]  # noqa: RUF012
    search_fields = ["event__title"]  # noqa: RUF012
