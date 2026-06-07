# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
from django.contrib import admin

from evennia_boards.models import Board, Post, PostCalendarLink, PostVersion, Subscription


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    list_display = ["pk", "name", "board_type", "order", "is_read_only", "created_at"]  # noqa: RUF012
    list_filter = ["board_type", "is_read_only"]  # noqa: RUF012
    search_fields = ["name", "description"]  # noqa: RUF012
    ordering = ["order", "name"]  # noqa: RUF012


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = [  # noqa: RUF012
        "pk",
        "board",
        "post_number",
        "title",
        "author_name",
        "xp_flagged",
        "created_at",
        "is_archived",
    ]
    list_filter = ["board", "is_archived", "xp_flagged"]  # noqa: RUF012
    search_fields = ["title", "author_name", "content"]  # noqa: RUF012
    readonly_fields = ["post_number", "created_at", "updated_at"]  # noqa: RUF012
    raw_id_fields = ["author", "parent_post"]  # noqa: RUF012


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["pk", "account", "board", "last_notified_at", "created_at"]  # noqa: RUF012
    list_filter = ["board"]  # noqa: RUF012
    search_fields = ["account__username"]  # noqa: RUF012
    raw_id_fields = ["account"]  # noqa: RUF012


@admin.register(PostVersion)
class PostVersionAdmin(admin.ModelAdmin):
    list_display = [  # noqa: RUF012
        "pk",
        "parent",
        "version_number",
        "editor_name",
        "is_rollback",
        "created_at",
    ]
    list_filter = ["is_rollback"]  # noqa: RUF012
    search_fields = ["editor_name"]  # noqa: RUF012
    raw_id_fields = ["parent", "editor"]  # noqa: RUF012
    readonly_fields = ["version_number", "created_at"]  # noqa: RUF012


@admin.register(PostCalendarLink)
class PostCalendarLinkAdmin(admin.ModelAdmin):
    list_display = ["pk", "post", "event_id", "created_by_name", "created_at"]  # noqa: RUF012
    search_fields = ["created_by_name"]  # noqa: RUF012
    raw_id_fields = ["post", "created_by"]  # noqa: RUF012
    readonly_fields = ["created_at"]  # noqa: RUF012
