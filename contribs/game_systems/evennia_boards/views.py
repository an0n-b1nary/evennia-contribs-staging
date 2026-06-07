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


class BoardListView(ListView):
    """Paginated list of all boards with post counts."""

    model = Board
    template_name = "evennia_boards/board_list.html"
    context_object_name = "boards"

    def get_queryset(self):
        return Board.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Bulletin Boards"
        for board in context["boards"]:
            board._post_count = board.posts.count()
        return context


class BoardDetailView(DetailView):
    """Board detail showing posts. Supports ?show_replies=0 to hide replies."""

    model = Board
    template_name = "evennia_boards/board_detail.html"
    context_object_name = "board"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        board = self.object
        context["page_title"] = f"Board: {board.name}"
        posts = Post.objects.filter(board=board).order_by("post_number")
        show_replies = self.request.GET.get("show_replies", "1")
        if show_replies != "1":
            posts = posts.filter(parent_post__isnull=True)
        context["posts"] = posts
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
        context["parent_post"] = parent
        context["page_title"] = f"Reply to #{parent.post_number}: {parent.title}"
        context["cancel_url"] = reverse("evennia_boards:board-detail", kwargs={"pk": board.pk})
        return context

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
