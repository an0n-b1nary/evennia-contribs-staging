# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Django admin registrations for evennia_scenes."""

from django.contrib import admin

from evennia_scenes.models import LogEntry, LogEntryVersion, Scene, SceneParticipant


@admin.register(Scene)
class SceneAdmin(admin.ModelAdmin):
    list_display = ["pk", "title", "status", "room_name", "creator_name", "created_at"]  # noqa: RUF012
    list_filter = ["status", "privacy", "is_archived"]  # noqa: RUF012
    search_fields = ["title", "room_name", "creator_name"]  # noqa: RUF012
    readonly_fields = ["created_at", "started_at", "ended_at"]  # noqa: RUF012


@admin.register(SceneParticipant)
class SceneParticipantAdmin(admin.ModelAdmin):
    list_display = ["pk", "scene", "character_name", "role", "pose_count", "is_active"]  # noqa: RUF012
    list_filter = ["role", "is_active"]  # noqa: RUF012
    search_fields = ["character_name"]  # noqa: RUF012


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = [  # noqa: RUF012
        "pk",
        "scene",
        "author_name",
        "log_type",
        "created_at",
        "is_deleted",
    ]
    list_filter = ["log_type", "is_deleted"]  # noqa: RUF012
    search_fields = ["author_name", "content"]  # noqa: RUF012


@admin.register(LogEntryVersion)
class LogEntryVersionAdmin(admin.ModelAdmin):
    list_display = ["pk", "parent", "version_number", "editor_name", "created_at"]  # noqa: RUF012
    search_fields = ["editor_name"]  # noqa: RUF012
