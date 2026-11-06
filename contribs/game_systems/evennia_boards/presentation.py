# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Viewer-scoped, immutable board projections and unread exclusions.

This module is the only player-facing adapter between raw ``Post`` rows and
their display values. A context caches a sender's Links policy once for the
request or command, and its frozen projections never retain a raw Post object.
Suppression receipts affect unread state only; they never change presentation.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from django.db import transaction
from evennia.accounts.models import AccountDB

from evennia_links.ignoring import ignore_mode

PLACEHOLDER_TITLE = "[A post by an ignored player.]"
HIDDEN_PARENT_LABEL = "[reply to a hidden post]"


def account_for(viewer):
    """Resolve the account without requiring Social or a selected character."""
    if isinstance(viewer, AccountDB):
        return viewer
    if not viewer:
        return None
    return getattr(viewer, "account", None) or getattr(getattr(viewer, "db", None), "account", None)


def web_viewer(request):
    """Use the selected web character, or the account when none is selected."""
    from evennia_links.characters import web_character

    return web_character(request.user) or request.user


def _save_receipts(account, post_ids, *, account_locked=False):
    """Idempotently persist exact unread exclusions for an account."""
    ids = set(post_ids)
    if not account or not account.pk or not ids:
        return

    from evennia_boards.models import Post, PostReadSuppression

    def save():
        existing_ids = set(Post.all_objects.filter(pk__in=ids).values_list("pk", flat=True))
        PostReadSuppression.objects.bulk_create(
            [
                PostReadSuppression(account_id=account.pk, post_id=post_id)
                for post_id in existing_ids
            ],
            ignore_conflicts=True,
        )

    if account_locked:
        save()
        return

    with transaction.atomic():
        locked_account = AccountDB.objects.select_for_update().get(pk=account.pk)
        locked_account.attributes.reset_cache()
        save()


def commit_rendered_state(account, *, placeholder_ids=(), board_id=None, high_water=None):
    """Merge rendered receipts and an optional full-board marker under one lock."""
    if not account or not account.pk:
        return
    ids = set(placeholder_ids)
    with transaction.atomic():
        locked_account = AccountDB.objects.select_for_update().get(pk=account.pk)
        locked_account.attributes.reset_cache()
        if board_id is not None and high_water is not None:
            markers = locked_account.attributes.get("boards_web_read", default={}) or {}
            markers = dict(markers) if isinstance(markers, Mapping) else {}
            key = str(board_id)
            markers[key] = max(int(markers.get(key, 0)), int(high_water))
            locked_account.attributes.add("boards_web_read", markers)
        _save_receipts(locked_account, ids, account_locked=True)


@dataclass(frozen=True)
class BoardReference:
    """Safe board fields used by a displayed post reference."""

    pk: int
    name: str


@dataclass(frozen=True)
class ParentPresentation:
    """A parent reference with no access to the underlying Post instance."""

    pk: int
    post_number: int
    title: str
    author_name: str
    is_suppressed: bool = False


@dataclass(frozen=True)
class PostPresentation:
    """Immutable, safe subset of a post suitable for player-facing output."""

    pk: int
    board_id: int
    board: BoardReference
    post_number: int
    title: str
    content: str
    author_name: str
    author_id: int | None
    created_at: object
    updated_at: object
    parent_post_id: int | None
    parent_post: ParentPresentation | None
    parent_post_label: str | None
    is_placeholder: bool


class PolicyContext:
    """One presentation-policy cache for one request or command evaluation."""

    def __init__(self, viewer, *, staff=None):
        self.viewer = viewer
        self.account = account_for(viewer)
        if staff is None:
            from evennia_boards.commands import is_staff

            staff = is_staff(viewer)
        self.staff = bool(staff)
        self._modes = {}
        self.hidden_ids = set()
        self.placeholder_ids = set()
        self.serialized_placeholder_ids = set()

    def mode_for(self, sender):
        """Evaluate Links once for this distinct sender in this context."""
        if self.staff or sender is None:
            return None
        key = getattr(sender, "pk", None)
        if key is None:
            key = id(sender)
        if key not in self._modes:
            self._modes[key] = ignore_mode(self.viewer, sender, "boards")
        return self._modes[key]

    def project_many(self, posts, *, persist_hidden=True):
        """Map raw posts to immutable projections; hidden posts map to None."""
        projected = {}
        for post in posts:
            mode = self.mode_for(post.author)
            if mode == "hide":
                self.hidden_ids.add(post.pk)
                projected[post.pk] = None
                continue

            parent, parent_label, title = self._parent_projection(post)
            is_placeholder = mode == "placeholder"
            if is_placeholder:
                self.placeholder_ids.add(post.pk)
            projected[post.pk] = PostPresentation(
                pk=post.pk,
                board_id=post.board_id,
                board=BoardReference(post.board_id, post.board.name),
                post_number=post.post_number,
                title=PLACEHOLDER_TITLE if is_placeholder else title,
                content="" if is_placeholder else post.content,
                author_name="" if is_placeholder else post.author_name,
                author_id=None if is_placeholder else post.author_id,
                created_at=post.created_at,
                updated_at=post.updated_at,
                parent_post_id=post.parent_post_id,
                parent_post=parent,
                parent_post_label=parent_label,
                is_placeholder=is_placeholder,
            )
        if persist_hidden:
            self.persist_hidden()
        return projected

    def _parent_projection(self, post):
        title = self._safe_title(post)
        if not post.parent_post_id:
            return None, None, title
        raw_parent = post.parent_post
        if raw_parent is None:
            return None, None, title
        mode = self.mode_for(raw_parent.author)
        suppressed = mode in ("placeholder", "hide")
        if mode == "hide":
            self.hidden_ids.add(raw_parent.pk)
        parent = ParentPresentation(
            pk=raw_parent.pk,
            post_number=raw_parent.post_number,
            title=HIDDEN_PARENT_LABEL if suppressed else self._safe_title(raw_parent),
            author_name="" if suppressed else raw_parent.author_name,
            is_suppressed=suppressed,
        )
        return parent, HIDDEN_PARENT_LABEL if suppressed else None, title

    def _safe_title(self, post, visited=None):
        """Remove inherited titles through filtered ancestry without recursion."""
        visited = set() if visited is None else visited
        inherited_depth = 0
        current = post
        while True:
            if current.pk in visited:
                safe_title = f"post #{current.post_number}"
                break
            visited.add(current.pk)
            if not current.parent_post_id:
                safe_title = current.title
                break
            parent = current.parent_post
            if parent is None or current.title != f"Re: {parent.title}":
                safe_title = current.title
                break
            parent_mode = self.mode_for(parent.author)
            if parent_mode in ("placeholder", "hide"):
                safe_title = f"post #{parent.post_number}"
                inherited_depth += 1
                break
            inherited_depth += 1
            current = parent
        return "Re: " * inherited_depth + safe_title

    def project(self, post):
        """Project one Post while applying any current hide receipt."""
        return self.project_many([post]).get(post.pk)

    def persist_hidden(self, *, account_locked=False):
        """Persist evaluated hides, never fail-open outcomes or placeholders."""
        if self.hidden_ids and self.account:
            _save_receipts(self.account, self.hidden_ids, account_locked=account_locked)
            self.hidden_ids.clear()

    def commit_placeholders(self, post_ids):
        """Persist only placeholder ids known to this context and actually shown."""
        ids = set(post_ids).intersection(self.placeholder_ids)
        _save_receipts(self.account, ids)


def visible_post_count(viewer, posts, *, context=None):
    """Count active/raw candidate rows after current hide policy projection."""
    context = context or PolicyContext(viewer)
    projection = context.project_many(list(posts))
    return sum(value is not None for value in projection.values())


def unread_post_count(viewer, posts, *, context=None, placeholder_ids=()):
    """Count candidates minus exact receipts and posts hidden by current policy."""
    from evennia_boards.models import PostReadSuppression

    rows = list(posts)
    if not rows:
        return 0
    context = context or PolicyContext(viewer)
    projection = context.project_many(rows)
    account = context.account
    read_ids = set()
    if account:
        read_ids = set(
            PostReadSuppression.objects.filter(
                account=account, post_id__in=[post.pk for post in rows]
            ).values_list("post_id", flat=True)
        )
    will_show_ids = set(placeholder_ids)
    return sum(
        value is not None and post_id not in read_ids and post_id not in will_show_ids
        for post_id, value in projection.items()
    )


def register_policy_snapshot(sender, viewer, kind=None, **kwargs):
    """Persist old-policy hides before Social changes an effective policy."""
    if kind not in (None, "boards"):
        return
    account = account_for(viewer)
    if not account:
        return
    # Social calls this from inside its atomic Account lock. Refresh Attributes
    # before constructing the old-policy context, then include archived posts.
    account.attributes.reset_cache()
    from evennia_boards.models import Post

    context = PolicyContext(account)
    posts = Post.all_objects.only("pk", "author_id").select_related("author")
    for post in posts.iterator():
        if context.mode_for(post.author) == "hide":
            context.hidden_ids.add(post.pk)
    context.persist_hidden(account_locked=True)
