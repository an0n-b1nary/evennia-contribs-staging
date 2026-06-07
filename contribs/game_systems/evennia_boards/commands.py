# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Bulletin board command for evennia_boards.

Classic MUSH BBS commands for reading, posting, replying, and managing
board subscriptions. Maps to the Board, Post, Subscription, PostVersion
models defined in evennia_boards.models.

Add to your CharacterCmdSet and AccountCmdSet::

    from evennia_boards.commands import CmdBoard
    self.add(CmdBoard)

Write operations (+bb/post, /reply, /edit) are guarded to require a
puppeted Character; bare reads (+bb, +bb <board>, +bb <board>/<post>)
and subscriptions work from Account-level sessions too.
"""

from django.conf import settings
from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils.eveditor import EvEditor

# Screenreader support — optional; falls back to always-False when
# evennia-accessibility is not installed.
try:
    from evennia_accessibility.utils import uses_screenreader
except ImportError:

    def uses_screenreader(_caller):
        return False


def is_staff(character):
    """Check if *character* has boards staff permissions.

    Reads BOARDS_STAFF_LOCK (default ``cmd:perm(Builder)``). Strips the
    ``cmd:`` prefix before calling ``locks.check_lockstring``.
    """
    lock_expr = getattr(settings, "BOARDS_STAFF_LOCK", "cmd:perm(Builder)")
    expr = lock_expr[4:] if lock_expr.startswith("cmd:") else lock_expr
    try:
        return bool(character.locks.check_lockstring(character, expr))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lookup_board(arg):
    """Resolve a board by 1-indexed position or case-insensitive name.

    Returns:
        (Board, None) on success.
        (None, error_str) on failure.
    """
    from evennia_boards.models import Board

    arg = arg.strip()
    if arg.isdigit():
        idx = int(arg) - 1
        boards = list(Board.objects.all())
        if 0 <= idx < len(boards):
            return boards[idx], None
        return None, f"No board at position {arg}. Use |w+bb|n to list boards."
    try:
        return Board.objects.get(name__iexact=arg), None
    except Board.DoesNotExist:
        return None, f"No board named '{arg}'. Use |w+bb|n to list boards."
    except Board.MultipleObjectsReturned:
        return None, f"Multiple boards match '{arg}'. Be more specific."


def _lookup_post(board, arg):
    """Resolve a post by post_number on *board* (archived posts appear not found).

    Returns:
        (Post, None) on success.
        (None, error_str) on failure.
    """
    from evennia_boards.models import Post

    if not arg.isdigit():
        return (
            None,
            f"Post number must be an integer. Usage: |w+bb {board.name}/<number>|n",
        )
    post_num = int(arg)
    try:
        return Post.objects.get(board=board, post_number=post_num), None
    except Post.DoesNotExist:
        return None, f"No post #{post_num} on {board.name}."


def _resolve_account(caller):
    """Return the AccountDB for this caller (Character or Account)."""
    return getattr(caller, "account", caller)


def _requires_character(caller):
    """Return True if caller is a puppeted Character (has an .account attr)."""
    return hasattr(caller, "account")


# ---------------------------------------------------------------------------
# EvEditor callbacks
# ---------------------------------------------------------------------------


def _bb_load(caller):
    """Load existing content into the EvEditor buffer (edit mode only)."""
    ctx = getattr(caller.ndb, "_bb_context", None)
    if not ctx:
        return ""
    if ctx.get("mode") == "edit":
        from evennia_boards.models import Post

        try:
            return Post.all_objects.get(pk=ctx["post_pk"]).content
        except Post.DoesNotExist:
            caller.msg("|rError: the post no longer exists.|n")
            return ""
    return ""


def _bb_save(caller, buffer):
    """Save the EvEditor buffer according to the current context mode."""
    ctx = getattr(caller.ndb, "_bb_context", None)
    if not ctx:
        caller.msg("|rError: no board editing context found.|n")
        return False

    content = buffer.strip()
    if not content:
        caller.msg("Nothing to save — buffer is empty.")
        return False

    mode = ctx.get("mode")

    if mode == "post":
        from evennia_boards.models import Board, Post

        try:
            board = Board.objects.get(pk=ctx["board_pk"])
        except Board.DoesNotExist:
            caller.msg("|rError: the board no longer exists.|n")
            return False
        Post.create_post(board=board, author=caller, title=ctx["title"], content=content)
        caller.msg(f"|gPost created on {board.name}.|n")
        return True

    elif mode == "reply":
        from evennia_boards.models import Board, Post

        try:
            board = Board.objects.get(pk=ctx["board_pk"])
            parent = Post.all_objects.get(pk=ctx["parent_post_pk"])
        except (Board.DoesNotExist, Post.DoesNotExist):
            caller.msg("|rError: the board or parent post no longer exists.|n")
            return False
        Post.create_post(
            board=board,
            author=caller,
            title=f"Re: {parent.title}",
            content=content,
            parent_post=parent,
        )
        caller.msg(f"|gReply posted on {board.name}.|n")
        return True

    elif mode == "edit":
        from evennia_boards.models import Post, PostVersion

        try:
            post = Post.all_objects.get(pk=ctx["post_pk"])
        except Post.DoesNotExist:
            caller.msg("|rError: the post no longer exists.|n")
            return False
        old_content = post.content
        if content == old_content.strip():
            caller.msg("No changes to save.")
            return True
        PostVersion.create_version(parent=post, content=old_content, editor=caller)
        post.content = content
        post.save(update_fields=["content", "updated_at"])
        caller.msg("|gPost updated.|n")
        return True

    caller.msg("|rError: unknown editor mode.|n")
    return False


def _bb_quit(caller):
    """Clean up the board editing context on editor close."""
    caller.ndb._bb_context = None
    caller.msg("Board editor closed.")


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


class CmdBoard(MuxCommand):
    """
    Read and manage bulletin boards.

    Usage:
        +bb                         - List all boards
        +bb <board>                 - Read posts on a board
        +bb <board>/<post>          - Read a specific post
        +bb/post <board>=<title>    - Create a new post (opens editor)
        +bb/reply <board>/<post>    - Reply to a post (opens editor)
        +bb/edit <board>/<post>     - Edit your own post (opens editor)
        +bb/subscribe <board>       - Subscribe to a board
        +bb/unsubscribe <board>     - Unsubscribe from a board
        +bb/archive <board>/<post>  - Archive a post (staff only)

    Boards can be referenced by number (1, 2, 3…) or by name.
    Post numbers are per-board (e.g. +bb General/1).

    Subscribed boards notify you of new posts on login.
    IC boards (marked [IC]) hold narrative posts that may earn XP.
    """

    key = "+bb"
    aliases = ["+board"]  # noqa: RUF012
    help_category = "Communication"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        switches = [s.lower() for s in self.switches]

        if not switches:
            if not self.args:
                self._list_boards()
            elif "/" in self.args:
                board_arg, post_arg = self.args.split("/", 1)
                board, err = _lookup_board(board_arg.strip())
                if err:
                    caller.msg(err)
                    return
                post, err = _lookup_post(board, post_arg.strip())
                if err:
                    caller.msg(err)
                    return
                self._read_post(board, post)
            else:
                board, err = _lookup_board(self.args)
                if err:
                    caller.msg(err)
                    return
                self._read_board(board)
            return

        switch = switches[0]
        dispatch = {
            "post": self._post,
            "reply": self._reply,
            "edit": self._edit,
            "subscribe": self._subscribe,
            "unsubscribe": self._unsubscribe,
            "archive": self._archive,
        }
        handler = dispatch.get(switch)
        if handler:
            handler()
        else:
            caller.msg(f"|rUnknown switch:|n /{switch}. See |whelp +bb|n for usage.")

    # -----------------------------------------------------------------------
    # Read operations
    # -----------------------------------------------------------------------

    def _list_boards(self):
        from evennia_boards.models import Board, Subscription

        caller = self.caller
        boards = list(Board.objects.all())
        if not boards:
            caller.msg("No bulletin boards configured.")
            return

        account = _resolve_account(caller)
        sub_board_ids = set(
            Subscription.objects.filter(account=account).values_list("board_id", flat=True)
        )

        if uses_screenreader(caller):
            count = len(boards)
            lines = [f"Bulletin Boards: {count} board{'s' if count != 1 else ''}"]
            for idx, board in enumerate(boards, start=1):
                post_count = board.posts.count()
                tags = []
                if board.pk in sub_board_ids:
                    tags.append("subscribed")
                if board.board_type == board.BoardType.IC:
                    tags.append("IC")
                if board.is_read_only:
                    tags.append("read-only")
                tag_str = f" ({', '.join(tags)})" if tags else ""
                desc = f": {board.description}" if board.description else ""
                lines.append(
                    f"  {idx}. {board.name}{tag_str}"
                    f" — {post_count} post{'s' if post_count != 1 else ''}{desc}"
                )
            caller.msg("\n".join(lines))
            return

        lines = ["|wBulletin Boards|n", "-" * 60]
        for idx, board in enumerate(boards, start=1):
            post_count = board.posts.count()
            sub_tag = "|g[sub]|n " if board.pk in sub_board_ids else "      "
            type_tag = " |c[IC]|n" if board.board_type == board.BoardType.IC else ""
            ro_tag = " |y[read-only]|n" if board.is_read_only else ""
            lines.append(
                f"  {idx:2}. {sub_tag}|w{board.name}|n{type_tag}{ro_tag}"
                f" — {post_count} post{'s' if post_count != 1 else ''}"
            )
            if board.description:
                lines.append(f"        {board.description}")
        lines.append("-" * 60)
        lines.append("Use |w+bb <board>|n to read, |w+bb/subscribe <board>|n to subscribe.")
        caller.msg("\n".join(lines))

    def _read_board(self, board):
        from evennia_boards.models import Post

        caller = self.caller
        posts = Post.objects.filter(board=board).order_by("post_number")
        type_tag = " |c[IC]|n" if board.board_type == board.BoardType.IC else ""

        if uses_screenreader(caller):
            sr_type = " (IC)" if board.board_type == board.BoardType.IC else ""
            lines = [f"Board: {board.name}{sr_type}"]
            if board.description:
                lines.append(f"  {board.description}")
            if not posts.exists():
                lines.append("  No posts yet.")
            else:
                for post in posts:
                    reply_str = (
                        f" (reply to #{post.parent_post.post_number})"
                        if post.parent_post_id
                        else ""
                    )
                    lines.append(
                        f"  Post {post.post_number}: {post.title}{reply_str}"
                        f" — by {post.author_name}"
                        f" ({post.created_at.strftime('%Y-%m-%d')})"
                    )
            caller.msg("\n".join(lines))
            return

        lines = [f"|wBoard: {board.name}|n{type_tag}"]
        if board.description:
            lines.append(f"  {board.description}")
        lines.append("-" * 60)
        if not posts.exists():
            lines.append("  No posts yet.")
        else:
            for post in posts:
                reply_tag = "  Re: " if post.parent_post_id else ""
                lines.append(
                    f"  {post.post_number:3}. {reply_tag}|w{post.title}|n"
                    f" — {post.author_name}"
                    f" ({post.created_at.strftime('%Y-%m-%d')})"
                )
        lines.append("-" * 60)
        lines.append(f"Use |w+bb {board.name}/<number>|n to read a post.")
        caller.msg("\n".join(lines))

    def _read_post(self, board, post):
        caller = self.caller
        lines = [
            f"|wPost #{post.post_number} — {post.title}|n",
            f"  |wBoard:|n  {board.name}",
            f"  |wAuthor:|n {post.author_name}",
            f"  |wDate:|n   {post.created_at.strftime('%Y-%m-%d %H:%M')} UTC",
        ]
        if post.parent_post_id and post.parent_post:
            lines.append(
                f"  |wReply to:|n #{post.parent_post.post_number}" f" — {post.parent_post.title}"
            )
        lines.append("-" * 60)
        lines.append(post.content)
        lines.append("-" * 60)
        replies = post.replies.filter(is_archived=False).order_by("post_number")
        if replies.exists():
            lines.append("|wReplies:|n")
            for reply in replies:
                lines.append(
                    f"  #{reply.post_number} |w{reply.title}|n"
                    f" — {reply.author_name}"
                    f" ({reply.created_at.strftime('%Y-%m-%d')})"
                )
        caller.msg("\n".join(lines))

    # -----------------------------------------------------------------------
    # Write operations (require Character puppet)
    # -----------------------------------------------------------------------

    def _post(self):
        caller = self.caller
        if not _requires_character(caller):
            caller.msg("You must be playing as a character to post.")
            return
        if not self.lhs or not self.rhs:
            caller.msg("Usage: |w+bb/post <board>=<title>|n")
            return
        board, err = _lookup_board(self.lhs)
        if err:
            caller.msg(err)
            return
        if board.is_read_only and not is_staff(caller):
            caller.msg(f"|r{board.name} is read-only.|n Staff only.")
            return
        title = self.rhs.strip()
        if not title:
            caller.msg("Usage: |w+bb/post <board>=<title>|n")
            return
        if getattr(caller.ndb, "_bb_context", None):
            caller.msg(
                "You already have a board editor open. "
                "Finish or close it first (|w:wq|n to save, |w:q|n to quit)."
            )
            return
        caller.ndb._bb_context = {"mode": "post", "board_pk": board.pk, "title": title}
        EvEditor(
            caller,
            loadfunc=_bb_load,
            savefunc=_bb_save,
            quitfunc=_bb_quit,
            key="bb_post_editor",
            persistent=False,
        )

    def _reply(self):
        caller = self.caller
        if not _requires_character(caller):
            caller.msg("You must be playing as a character to post.")
            return
        if not self.args or "/" not in self.args:
            caller.msg("Usage: |w+bb/reply <board>/<post#>|n")
            return
        board_arg, post_arg = self.args.split("/", 1)
        board, err = _lookup_board(board_arg.strip())
        if err:
            caller.msg(err)
            return
        if board.is_read_only and not is_staff(caller):
            caller.msg(f"|r{board.name} is read-only.|n Staff only.")
            return
        post, err = _lookup_post(board, post_arg.strip())
        if err:
            caller.msg(err)
            return
        if getattr(caller.ndb, "_bb_context", None):
            caller.msg(
                "You already have a board editor open. "
                "Finish or close it first (|w:wq|n to save, |w:q|n to quit)."
            )
            return
        caller.ndb._bb_context = {
            "mode": "reply",
            "board_pk": board.pk,
            "parent_post_pk": post.pk,
        }
        EvEditor(
            caller,
            loadfunc=_bb_load,
            savefunc=_bb_save,
            quitfunc=_bb_quit,
            key="bb_reply_editor",
            persistent=False,
        )

    def _edit(self):
        caller = self.caller
        if not _requires_character(caller):
            caller.msg("You must be playing as a character to edit posts.")
            return
        if not self.args or "/" not in self.args:
            caller.msg("Usage: |w+bb/edit <board>/<post#>|n")
            return
        board_arg, post_arg = self.args.split("/", 1)
        board, err = _lookup_board(board_arg.strip())
        if err:
            caller.msg(err)
            return
        post, err = _lookup_post(board, post_arg.strip())
        if err:
            caller.msg(err)
            return
        if post.author != caller and not is_staff(caller):
            caller.msg("|rYou can only edit your own posts.|n")
            return
        if getattr(caller.ndb, "_bb_context", None):
            caller.msg(
                "You already have a board editor open. "
                "Finish or close it first (|w:wq|n to save, |w:q|n to quit)."
            )
            return
        caller.ndb._bb_context = {"mode": "edit", "post_pk": post.pk}
        EvEditor(
            caller,
            loadfunc=_bb_load,
            savefunc=_bb_save,
            quitfunc=_bb_quit,
            key="bb_edit_editor",
            persistent=False,
        )

    # -----------------------------------------------------------------------
    # Subscription management
    # -----------------------------------------------------------------------

    def _subscribe(self):
        caller = self.caller
        if not self.args:
            caller.msg("Usage: |w+bb/subscribe <board>|n")
            return
        board, err = _lookup_board(self.args)
        if err:
            caller.msg(err)
            return
        from evennia_boards.models import Subscription

        account = _resolve_account(caller)
        _, created = Subscription.objects.get_or_create(account=account, board=board)
        if created:
            caller.msg(
                f"|gSubscribed to {board.name}.|n " f"You will be notified of new posts on login."
            )
        else:
            caller.msg(f"You are already subscribed to {board.name}.")

    def _unsubscribe(self):
        caller = self.caller
        if not self.args:
            caller.msg("Usage: |w+bb/unsubscribe <board>|n")
            return
        board, err = _lookup_board(self.args)
        if err:
            caller.msg(err)
            return
        from evennia_boards.models import Subscription

        account = _resolve_account(caller)
        deleted, _ = Subscription.objects.filter(account=account, board=board).delete()
        if deleted:
            caller.msg(f"|yUnsubscribed from {board.name}.|n")
        else:
            caller.msg(f"You are not subscribed to {board.name}.")

    # -----------------------------------------------------------------------
    # Staff operations
    # -----------------------------------------------------------------------

    def _archive(self):
        caller = self.caller
        if not is_staff(caller):
            caller.msg("|rOnly staff can archive posts.|n")
            return
        if not self.args or "/" not in self.args:
            caller.msg("Usage: |w+bb/archive <board>/<post#>|n")
            return
        board_arg, post_arg = self.args.split("/", 1)
        board, err = _lookup_board(board_arg.strip())
        if err:
            caller.msg(err)
            return
        post, err = _lookup_post(board, post_arg.strip())
        if err:
            caller.msg(err)
            return
        post.archive(editor=caller)
        caller.msg(f"|yPost #{post.post_number} on {board.name} archived.|n")
