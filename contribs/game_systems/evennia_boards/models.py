# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Board, Post, Subscription, PostVersion, and PostCalendarLink models.

Models:
- Board: named bulletin board with OOC/IC type, ordering, and read-only flag.
- Post(AbstractArchived): per-board auto-numbered threaded posts with soft-archive
  and XP anti-gaming flags. Archived posts are excluded by the default manager.
- Subscription: account-level board subscriptions with last-notified timestamp.
- PostVersion(AbstractVersion): append-only edit history for posts.
- PostCalendarLink: optional bridge linking a Post to a calendar event. The
  calendar reference is stored as an integer soft-ref (event_id) so evennia_boards
  has no hard FK dependency on a calendar app. Register the cleanup hook in your
  game's LinksConfig.ready() via connect_soft_ref_cleanup.

AbstractArchived and AbstractVersion are provided by evennia-links (hard dependency).
"""

from django.db import models
from django.db.models import Max

from evennia_links import AbstractArchived, AbstractAuthoredLink, AbstractVersion


class Board(models.Model):
    """
    A named bulletin board.

    Boards are admin-created. They are ordered by ``order`` for numbered
    access (+bb 1, +bb 2, …).

    board_type controls whether posts are narrative / XP-eligible:
      ``ooc`` — standard out-of-character communication.
      ``ic``  — in-character narrative board; posts are XP-eligible when
                evennia-xp is installed and the integration is registered.
    """

    class BoardType(models.TextChoices):
        OOC = "ooc", "OOC"
        IC = "ic", "IC"

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    board_type = models.CharField(
        max_length=3,
        choices=BoardType.choices,
        default=BoardType.OOC,
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order in +bb listing. Lower numbers appear first.",
    )
    is_read_only = models.BooleanField(
        default=False,
        help_text="If True, only staff (BOARDS_STAFF_LOCK permission) can post.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "name"]  # noqa: RUF012

    def __str__(self):
        return f"Board: {self.name} ({self.get_board_type_display()})"


class Post(AbstractArchived):
    """
    A single message on a bulletin board.

    Posts are numbered per-board (post_number), starting at 1. The sequence
    never resets even when earlier posts are archived; gaps are intentional.
    Replies share the same numbering sequence as top-level posts.

    Edit history is tracked via PostVersion. Archival (soft-delete) is handled
    by AbstractArchived — the default manager excludes archived posts; use
    all_objects to include them.

    xp_flagged / xp_flag_reason are written by the anti-gaming sweep
    (integrations/xp.py) and read by the cutscene collector. Staff can clear
    these fields after review. Both fields are meaningful only when evennia-xp
    is installed and the integration is registered.
    """

    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    post_number = models.PositiveIntegerField(
        help_text="Auto-incremented per board. Used for +bb Board/1 addressing.",
    )
    title = models.CharField(max_length=255)
    content = models.TextField()

    author = models.ForeignKey(
        "objects.ObjectDB",
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        help_text="The character who created this post.",
    )
    author_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Denormalized author name for display after character deletion.",
    )

    parent_post = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replies",
        help_text="Set when this post is a reply to another post.",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    xp_flagged = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "Set by the anti-gaming sweep (integrations/xp.py) when this post "
            "looks like cutscene spam. Flagged posts are excluded from XP awards "
            "until staff review and clear the flag."
        ),
    )
    xp_flag_reason = models.CharField(
        max_length=500,
        blank=True,
        help_text="Auto-generated reason stored by the anti-gaming sweep.",
    )

    # Secondary manager — AbstractArchived's ArchivedManager is the default.
    # Use all_objects in admin, migrations, and anywhere archived posts must be visible.
    all_objects = models.Manager()

    class Meta:
        ordering = ["board", "post_number"]  # noqa: RUF012
        unique_together = [("board", "post_number")]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["board", "created_at"]),
        ]

    def __str__(self):
        return f"[{self.board.name}/{self.post_number}] {self.title}"

    @classmethod
    def create_post(cls, board, author, title, content, parent_post=None):
        """
        Create a new post on *board* and fire the ``post_created`` signal.

        Uses all_objects for the max-number query so archived posts do not
        create gaps in the numbering sequence.

        Args:
            board: Board instance.
            author: ObjectDB (Character), or None for system posts.
            title: str — post title.
            content: str — post body.
            parent_post: Post instance to reply to, or None for top-level.

        Returns:
            The newly created Post instance.
        """
        from evennia_boards.signals import post_created

        current_max = (
            cls.all_objects.filter(board=board).aggregate(max_num=Max("post_number")).get("max_num")
        ) or 0

        post = cls.objects.create(
            board=board,
            post_number=current_max + 1,
            title=title,
            content=content,
            author=author,
            author_name=author.key if author else "System",
            parent_post=parent_post,
        )
        post_created.send(sender=cls, post=post, board=board)
        return post


class Subscription(models.Model):
    """
    An account's subscription to a board for new-post login notifications.

    Account-level (not character-level) so subscriptions persist across
    character swaps and multiple alts. The login listener reads
    last_notified_at and bulk-updates it after each notification sweep.
    """

    account = models.ForeignKey(
        "accounts.AccountDB",
        on_delete=models.CASCADE,
        related_name="evennia_board_subscriptions",
    )
    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    last_notified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Updated after each login notification sweep. Posts created after "
            "this timestamp count as unread for the next login."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("account", "board")]  # noqa: RUF012

    def __str__(self):
        return f"{self.account} → {self.board.name}"

    def unread_count(self):
        """Count posts on this board created after last_notified_at.

        Uses Post.objects (the ArchivedManager default) so archived posts
        are excluded. Returns 0 if last_notified_at is None (all posts
        are considered unread).
        """
        qs = Post.objects.filter(board=self.board)
        if self.last_notified_at:
            qs = qs.filter(created_at__gt=self.last_notified_at)
        return qs.count()


class PostVersion(AbstractVersion):
    """
    Edit history for board posts (append-only snapshots of old content).

    Each edit snapshots the old content before the change. The live content
    always lives on Post.content. Rolling back creates a new version rather
    than rewriting history.

    See evennia_links.AbstractVersion for create_version() and rollback_to().
    """

    parent = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="versions",
    )

    class Meta(AbstractVersion.Meta):
        unique_together = [("parent", "version_number")]  # noqa: RUF012


class PostCalendarLink(AbstractAuthoredLink):
    """
    Optional bridge: link a board Post to a calendar event.

    The calendar reference is stored as an integer soft-ref (event_id) so
    evennia_boards has no FK dependency on any calendar app. The link
    migrates and ships unconditionally; the cascade-cleanup hook is only
    registered when the calendar app label is in INSTALLED_APPS (see apps.py).

    To activate cascade cleanup, add to your game's LinksConfig.ready()::

        from evennia_links import connect_soft_ref_cleanup
        from evennia_boards.models import PostCalendarLink
        from myapp.calendar.models import CalendarEvent
        connect_soft_ref_cleanup(CalendarEvent, PostCalendarLink, "event_id")

    Or rely on evennia_boards' apps.py which auto-registers the hook when
    BOARDS_CALENDAR_APP_LABEL is present in INSTALLED_APPS.

    Note: in games that also use evennia_links' bridge layer (e.g. a game that
    keeps PostCalendarLink in world/links/), this model may exist as a
    duplicate. MIGRATION_NOTES.md documents the divergence.
    """

    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="calendar_links",
        help_text="The board post associated with this calendar event.",
    )
    event_id = models.PositiveBigIntegerField(
        db_index=True,
        help_text="PK of the CalendarEvent. Stored as integer soft-ref (no FK).",
    )

    link_fields = ("post", "event_id")

    class Meta(AbstractAuthoredLink.Meta):
        unique_together = [("post", "event_id")]  # noqa: RUF012

    def __str__(self):
        return f"Post #{self.post_id} ↔ CalendarEvent #{self.event_id}"
