# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""DRF serializers for evennia_boards API."""

from rest_framework import serializers

from evennia_boards.models import Board, Post


class BoardSerializer(serializers.ModelSerializer):
    """Board summary including post count."""

    post_count = serializers.SerializerMethodField()

    class Meta:
        model = Board
        fields = [  # noqa: RUF012
            "id",
            "name",
            "description",
            "board_type",
            "order",
            "is_read_only",
            "post_count",
            "created_at",
        ]

    def get_post_count(self, obj):
        return obj.posts.count()


class PostSerializer(serializers.ModelSerializer):
    """Board post with board name denormalized."""

    board_name = serializers.CharField(source="board.name", read_only=True)

    class Meta:
        model = Post
        fields = [  # noqa: RUF012
            "id",
            "board",
            "board_name",
            "post_number",
            "title",
            "content",
            "author_name",
            "parent_post",
            "xp_flagged",
            "created_at",
            "updated_at",
        ]
