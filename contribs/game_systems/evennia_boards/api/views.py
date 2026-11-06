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
from evennia_boards.permissions import is_staff_user
from evennia_boards.presentation import PolicyContext, commit_rendered_state, web_viewer


class _PrivateResponseMixin:
    """Prevent personalized board projections from entering shared caches."""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response


class BoardViewSet(_PrivateResponseMixin, ReadOnlyModelViewSet):
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

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["boards_policy"] = PolicyContext(
            web_viewer(self.request), staff=is_staff_user(self.request)
        )
        return context


class PostViewSet(_PrivateResponseMixin, ReadOnlyModelViewSet):
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

    def _get_policy(self):
        if not hasattr(self, "_boards_policy"):
            self._boards_policy = PolicyContext(
                web_viewer(self.request), staff=is_staff_user(self.request)
            )
        return self._boards_policy

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["boards_policy"] = self._get_policy()
        return context

    def get_queryset(self):
        qs = Post.objects.order_by("post_number")
        board_id = self.request.query_params.get("board")
        if board_id:
            qs = qs.filter(board_id=board_id)
        qs = qs.select_related("author", "board", "parent_post", "parent_post__author")
        rows = list(qs)
        projection = self._get_policy().project_many(rows)
        hidden_ids = [post_id for post_id, safe in projection.items() if safe is None]
        return qs.exclude(pk__in=hidden_ids)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        policy = getattr(self, "_boards_policy", None)
        if policy and response.status_code < 400 and policy.serialized_placeholder_ids:
            placeholder_ids = tuple(policy.serialized_placeholder_ids)
            response.add_post_render_callback(
                lambda rendered: commit_rendered_state(
                    policy.account, placeholder_ids=placeholder_ids
                )
            )
        return response
