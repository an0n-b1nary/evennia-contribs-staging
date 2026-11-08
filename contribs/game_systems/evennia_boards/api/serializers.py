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
        from evennia_boards.presentation import PolicyContext, visible_post_count

        context = self.context.get("boards_policy")
        if context is None:
            request = self.context.get("request")
            context = PolicyContext(request.user if request else None)
        posts = obj.posts.select_related("author", "board", "parent_post", "parent_post__author")
        return visible_post_count(context.viewer, posts, context=context)


class PostSerializer(serializers.ModelSerializer):
    """Board post with board name denormalized."""

    board_name = serializers.CharField(source="board.name", read_only=True)
    parent_post_label = serializers.CharField(read_only=True, allow_null=True, required=False)

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
            "parent_post_label",
            "xp_flagged",
            "created_at",
            "updated_at",
        ]

    def to_representation(self, instance):
        """Serialize only the safe projection, never masked model attributes."""
        from django.http import Http404

        from evennia_boards.presentation import PolicyContext

        context = self.context.get("boards_policy")
        if context is None:
            request = self.context.get("request")
            context = PolicyContext(request.user if request else None)
        safe = context.project(instance)
        if safe is None:
            raise Http404
        if safe.is_placeholder:
            context.serialized_placeholder_ids.add(safe.pk)
        return {
            "id": safe.pk,
            "board": safe.board_id,
            "board_name": safe.board.name,
            "post_number": safe.post_number,
            "title": safe.title,
            "content": safe.content,
            "author_name": safe.author_name,
            "parent_post": (
                None if safe.parent_post and safe.parent_post.is_suppressed else safe.parent_post_id
            ),
            "parent_post_label": safe.parent_post_label,
            "xp_flagged": instance.xp_flagged,
            "created_at": self.fields["created_at"].to_representation(safe.created_at),
            "updated_at": self.fields["updated_at"].to_representation(safe.updated_at),
        }
