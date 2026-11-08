# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Web views for evennia_boards. Requires [web] extra.

Read-only:
    /boards/                            BoardListView
    /boards/<pk>/                       BoardDetailView

Authoring (login + active puppet required):
    /boards/<pk>/new/                   PostCreateView
    /boards/<pk>/posts/<post_id>/reply/ PostReplyView
    /boards/<pk>/posts/<post_id>/edit/  PostEditView

Permission rules:
    - Read-only boards: non-staff cannot post or reply.
    - PostEditView: author or staff (BOARDS_STAFF_LOCK) may edit.
    - Edit snapshots old content via PostVersion before mutating.

Wire into your game's URLconf::

    from django.urls import include, path
    urlpatterns += [path("", include("evennia_boards.urls"))]
"""

from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import DetailView, FormView, ListView
from evennia.objects.models import ObjectDB

from evennia_boards.authoring import BoardsAuthoringMixin
from evennia_boards.forms import PostEditForm, PostForm
from evennia_boards.models import Board, Post, PostVersion
from evennia_boards.permissions import get_character_id, is_staff_user
from evennia_boards.presentation import (
    HIDDEN_PARENT_LABEL,
    PolicyContext,
    commit_rendered_state,
    unread_post_count,
    web_viewer,
)


class BoardListView(ListView):
    """Boards with their latest post and account-specific web unread state."""

    model = Board
    template_name = "evennia_boards/board_list.html"
    context_object_name = "boards"

    def get_queryset(self):
        return Board.objects.all()

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        response["Cache-Control"] = "private, no-store"
        account = self.request.user
        if getattr(account, "is_authenticated", False):
            ids = tuple(getattr(self, "_placeholder_ids", ()))
            response.add_post_render_callback(
                lambda rendered: commit_rendered_state(account, placeholder_ids=ids)
            )
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Bulletin Boards"
        account = self.request.user
        context["show_unread"] = account.is_authenticated
        markers = (
            account.attributes.get("boards_web_read", default={})
            if account.is_authenticated
            else {}
        )
        boards = list(context["boards"])
        context["boards"] = boards
        policy = PolicyContext(web_viewer(self.request), staff=is_staff_user(self.request))
        rows = list(
            Post.objects.filter(board_id__in=[board.pk for board in boards])
            .select_related("author", "board", "parent_post", "parent_post__author")
            .order_by("board_id", "-post_number")
        )
        projected = policy.project_many(rows)
        latest_by_board = {}
        for row in rows:
            safe = projected[row.pk]
            if safe is not None and row.board_id not in latest_by_board:
                latest_by_board[row.board_id] = safe

        placeholder_ids = []
        for board in boards:
            latest = latest_by_board.get(board.pk)
            board.latest_title = latest.title if latest else None
            board.latest_author = latest.author_name if latest else ""
            board.latest_number = latest.post_number if latest else None
            board.latest_time = latest.created_at if latest else None
            board.latest_placeholder = bool(latest and latest.is_placeholder)
            board.has_posts = any(row.board_id == board.pk for row in rows)
            if latest and latest.is_placeholder:
                placeholder_ids.append(latest.pk)
            if account.is_authenticated:
                candidates = Post.objects.filter(
                    board=board,
                    post_number__gt=markers.get(str(board.pk), 0),
                ).select_related("author", "board", "parent_post", "parent_post__author")
                board.unread_count = unread_post_count(
                    policy.viewer,
                    candidates,
                    context=policy,
                    placeholder_ids=placeholder_ids,
                )
            else:
                board.unread_count = 0
        self._placeholder_ids = tuple(placeholder_ids)
        return context


class BoardDetailView(DetailView):
    """Board detail showing posts. Supports ?show_replies=0 to hide replies."""

    model = Board
    template_name = "evennia_boards/board_detail.html"
    context_object_name = "board"

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        response["Cache-Control"] = "private, no-store"
        account = self.request.user
        if getattr(account, "is_authenticated", False):
            ids = tuple(getattr(self, "_placeholder_ids", ()))
            board_id = self.object.pk if context["show_replies"] else None
            high_water = self._board_high_water if board_id is not None else None
            response.add_post_render_callback(
                lambda rendered: commit_rendered_state(
                    account,
                    placeholder_ids=ids,
                    board_id=board_id,
                    high_water=high_water,
                )
            )
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        board = self.object
        context["page_title"] = f"Board: {board.name}"
        posts = Post.objects.filter(board=board).order_by("post_number")
        show_replies = self.request.GET.get("show_replies", "1")
        if show_replies != "1":
            posts = posts.filter(parent_post__isnull=True)
        rows = list(posts.select_related("author", "board", "parent_post", "parent_post__author"))
        self._board_high_water = max((row.post_number for row in rows), default=None)
        policy = PolicyContext(web_viewer(self.request), staff=is_staff_user(self.request))
        projected = policy.project_many(rows)
        context["posts"] = [projected[row.pk] for row in rows if projected[row.pk] is not None]
        self._placeholder_ids = tuple(post.pk for post in context["posts"] if post.is_placeholder)
        context["show_replies"] = show_replies == "1"
        context["is_staff"] = is_staff_user(self.request)
        context["character_id"] = get_character_id(self.request.user)
        return context


class PostCreateView(BoardsAuthoringMixin, FormView):
    """Create a new top-level post on a board."""

    form_class = PostForm
    template_name = "evennia_boards/post_form.html"

    def _get_board(self):
        if not hasattr(self, "_board"):
            self._board = get_object_or_404(Board, pk=self.kwargs["pk"])
        return self._board

    def get_permission_target(self):
        return self._get_board()

    def check_permission(self, character_id, target):
        if target.is_read_only and not is_staff_user(self.request):
            raise PermissionDenied("This board is read-only.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        board = self._get_board()
        context["board"] = board
        context["page_title"] = f"New Post on {board.name}"
        context["cancel_url"] = reverse("evennia_boards:board-detail", kwargs={"pk": board.pk})
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        board = self._get_board()
        character = get_object_or_404(ObjectDB, pk=character_id)
        Post.create_post(
            board=board,
            author=character,
            title=form.cleaned_data["title"],
            content=form.cleaned_data["content"],
        )
        return HttpResponseRedirect(reverse("evennia_boards:board-detail", kwargs={"pk": board.pk}))


class PostReplyView(BoardsAuthoringMixin, FormView):
    """Create a reply to an existing post."""

    form_class = PostForm
    template_name = "evennia_boards/post_form.html"

    def _get_board(self):
        if not hasattr(self, "_board"):
            self._board = get_object_or_404(Board, pk=self.kwargs["pk"])
        return self._board

    def _get_parent_post(self):
        if not hasattr(self, "_parent_post"):
            self._parent_post = get_object_or_404(
                Post, pk=self.kwargs["post_id"], board=self._get_board()
            )
        return self._parent_post

    def get_permission_target(self):
        return self._get_board()

    def check_permission(self, character_id, target):
        if target.is_read_only and not is_staff_user(self.request):
            raise PermissionDenied("This board is read-only.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        board = self._get_board()
        parent = self._get_parent_post()
        context["board"] = board
        policy = PolicyContext(web_viewer(self.request), staff=is_staff_user(self.request))
        parent_view = policy.project(parent)
        context["parent_post_number"] = parent.post_number
        self._placeholder_parent_id = None
        if parent_view is None:
            context["parent_post"] = None
            context["parent_post_label"] = HIDDEN_PARENT_LABEL
            context["page_title"] = f"Reply to #{parent.post_number}: {HIDDEN_PARENT_LABEL}"
        else:
            context["parent_post"] = parent_view
            context["parent_post_label"] = None
            if parent_view.is_placeholder:
                self._placeholder_parent_id = parent.pk
            context["page_title"] = f"Reply to #{parent.post_number}: {parent_view.title}"
        context["cancel_url"] = reverse("evennia_boards:board-detail", kwargs={"pk": board.pk})
        return context

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        parent_id = getattr(self, "_placeholder_parent_id", None)
        account = self.request.user
        if parent_id and getattr(account, "is_authenticated", False):
            response.add_post_render_callback(
                lambda rendered: commit_rendered_state(account, placeholder_ids=(parent_id,))
            )
        return response

    def form_valid(self, form):
        character_id = self.get_character()
        board = self._get_board()
        parent = self._get_parent_post()
        character = get_object_or_404(ObjectDB, pk=character_id)
        Post.create_post(
            board=board,
            author=character,
            title=form.cleaned_data["title"],
            content=form.cleaned_data["content"],
            parent_post=parent,
        )
        return HttpResponseRedirect(reverse("evennia_boards:board-detail", kwargs={"pk": board.pk}))


class PostEditView(BoardsAuthoringMixin, FormView):
    """Edit an existing post. Snapshots old content in PostVersion before saving."""

    form_class = PostEditForm
    template_name = "evennia_boards/post_edit_form.html"

    def _get_post(self):
        if not hasattr(self, "_post"):
            self._post = get_object_or_404(
                Post, pk=self.kwargs["post_id"], board_id=self.kwargs["pk"]
            )
        return self._post

    def get_permission_target(self):
        return self._get_post()

    def check_permission(self, character_id, target):
        if target.author_id != character_id and not is_staff_user(self.request):
            raise PermissionDenied("You can only edit your own posts.")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self._get_post()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        post = self._get_post()
        context["post"] = post
        context["board"] = post.board
        context["page_title"] = f"Edit Post #{post.post_number}"
        context["cancel_url"] = reverse("evennia_boards:board-detail", kwargs={"pk": post.board_id})
        return context

    def form_valid(self, form):
        character_id = self.get_character()
        post = self._get_post()
        character = get_object_or_404(ObjectDB, pk=character_id)
        # Re-fetch pre-edit content from DB for the version snapshot (ModelForm
        # has already mutated the instance in-place during validation).
        old_content = Post.all_objects.values_list("content", flat=True).get(pk=post.pk)
        PostVersion.create_version(parent=post, content=old_content, editor=character)
        post.title = form.cleaned_data["title"]
        post.content = form.cleaned_data["content"]
        post.save(update_fields=["title", "content", "updated_at"])
        return HttpResponseRedirect(
            reverse("evennia_boards:board-detail", kwargs={"pk": post.board_id})
        )
