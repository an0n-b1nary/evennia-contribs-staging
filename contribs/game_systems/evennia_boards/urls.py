# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
URL patterns for evennia_boards website views.

Include in your game's URLconf with an app_namespace::

    from django.urls import include, path
    urlpatterns += [
        path("", include(("evennia_boards.urls", "evennia_boards"))),
    ]

Generates:
    /boards/                                 evennia_boards:board-list
    /boards/<pk>/                            evennia_boards:board-detail
    /boards/<pk>/new/                        evennia_boards:post-create
    /boards/<pk>/posts/<post_id>/reply/      evennia_boards:post-reply
    /boards/<pk>/posts/<post_id>/edit/       evennia_boards:post-edit
"""

from django.urls import path

from evennia_boards.views import (
    BoardDetailView,
    BoardListView,
    PostCreateView,
    PostEditView,
    PostReplyView,
)

urlpatterns = [
    path("boards/", BoardListView.as_view(), name="board-list"),
    path("boards/<int:pk>/", BoardDetailView.as_view(), name="board-detail"),
    path("boards/<int:pk>/new/", PostCreateView.as_view(), name="post-create"),
    path(
        "boards/<int:pk>/posts/<int:post_id>/reply/",
        PostReplyView.as_view(),
        name="post-reply",
    ),
    path(
        "boards/<int:pk>/posts/<int:post_id>/edit/",
        PostEditView.as_view(),
        name="post-edit",
    ),
]
