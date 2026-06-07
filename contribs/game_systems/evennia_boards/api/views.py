# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
DRF viewsets for evennia_boards API.

Authentication: SessionAuthentication (explicit — does not rely on global
REST_FRAMEWORK defaults). Requires IsAuthenticated.

Both viewsets are read-only. Posts can be filtered by board with ?board=<id>.
"""

from rest_framework.authentication import SessionAuthentication
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ReadOnlyModelViewSet

from evennia_boards.api.pagination import BoardsCursorPagination
from evennia_boards.api.serializers import BoardSerializer, PostSerializer
from evennia_boards.models import Board, Post


class BoardViewSet(ReadOnlyModelViewSet):
    """All bulletin boards, ordered by display order."""

    serializer_class = BoardSerializer
    authentication_classes = [SessionAuthentication]  # noqa: RUF012
    permission_classes = [IsAuthenticated]  # noqa: RUF012
    pagination_class = BoardsCursorPagination
    filter_backends = [OrderingFilter]  # noqa: RUF012
    ordering_fields = ["order", "name", "created_at"]  # noqa: RUF012
    ordering = ["order"]  # noqa: RUF012

    def get_queryset(self):
        return Board.objects.all().order_by("order")


class PostViewSet(ReadOnlyModelViewSet):
    """Board posts. Filter by board with ?board=<id>.

    Archived posts are excluded (uses the default ArchivedManager).

    Usage::

        /api/boards/posts/
        /api/boards/posts/?board=<id>
    """

    serializer_class = PostSerializer
    authentication_classes = [SessionAuthentication]  # noqa: RUF012
    permission_classes = [IsAuthenticated]  # noqa: RUF012
    pagination_class = BoardsCursorPagination
    filter_backends = [OrderingFilter]  # noqa: RUF012
    ordering_fields = ["created_at", "post_number"]  # noqa: RUF012
    ordering = ["post_number"]  # noqa: RUF012

    def get_queryset(self):
        qs = Post.objects.order_by("post_number")
        board_id = self.request.query_params.get("board")
        if board_id:
            qs = qs.filter(board_id=board_id)
        return qs
