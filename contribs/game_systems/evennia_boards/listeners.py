# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Signal listeners for evennia_boards.

Connects to Evennia's SIGNAL_ACCOUNT_POST_LOGIN to notify accounts of
unread posts on subscribed boards. The notification fires automatically
on every login — no game-side wiring required.
"""

from django.db import transaction
from evennia.server.signals import SIGNAL_ACCOUNT_POST_LOGIN

from evennia_boards.signals import post_created
from evennia_links.ignoring import ignore_policy_changing


def _notify_board_subscriptions(sender, session=None, **kwargs):
    """Run the legacy login receiver with the supplied connection."""
    from evennia_boards.notices import notify_login

    notify_login(sender, session)


def _queue_board_activity(sender, post, board, **kwargs):
    """Discover subscribers only after the normal post writer commits."""
    from evennia_boards.notices import post_committed

    transaction.on_commit(
        lambda: post_committed(board.pk, post.pk), using=post._state.db, robust=True
    )


def connect():
    """Connect board listeners. Called from BoardsConfig.ready().

    The dispatch_uid makes the connection idempotent across module reloads,
    preventing duplicate login notifications.
    """
    SIGNAL_ACCOUNT_POST_LOGIN.connect(
        _notify_board_subscriptions,
        dispatch_uid="evennia_boards.notify_board_subscriptions",
    )
    post_created.connect(_queue_board_activity, dispatch_uid="evennia_boards.queue_activity")
    ignore_policy_changing.connect(
        _snapshot_policy_before_change,
        dispatch_uid="evennia_boards.snapshot_ignore_policy",
    )


def _snapshot_policy_before_change(sender, viewer, kind=None, **kwargs):
    """Save old-policy hidden posts before Social mutates a reader's policy."""
    from evennia_boards.presentation import register_policy_snapshot

    return register_policy_snapshot(sender, viewer, kind=kind, **kwargs)
