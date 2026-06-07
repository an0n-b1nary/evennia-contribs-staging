# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Signal listeners for evennia_boards.

Connects to Evennia's SIGNAL_ACCOUNT_POST_LOGIN to notify accounts of
unread posts on subscribed boards. The notification fires automatically
on every login — no game-side wiring required.
"""

import logging

from evennia.server.signals import SIGNAL_ACCOUNT_POST_LOGIN

logger = logging.getLogger("evennia")


def _notify_board_subscriptions(sender, session=None, **kwargs):
    """Notify *sender* (an Account) of unread posts on their subscriptions.

    Fires on every login via SIGNAL_ACCOUNT_POST_LOGIN. Degrades to a
    no-op when the account has no subscriptions. Bulk-updates
    last_notified_at for all subscriptions in a single query after notify.
    """
    from django.utils import timezone

    from evennia_boards.models import Subscription

    account = sender
    subs = Subscription.objects.filter(account=account).select_related("board")
    if not subs.exists():
        return

    lines = []
    now = timezone.now()
    pks = []
    for sub in subs:
        count = sub.unread_count()
        if count:
            plural = "s" if count != 1 else ""
            lines.append(f"  |w{sub.board.name}|n: {count} new post{plural}")
        pks.append(sub.pk)

    if lines:
        msg = "|wNew board posts:|n\n" + "\n".join(lines)
        msg += "\nUse |w+bb <board>|n to read."
        account.msg(msg, session=session)

    Subscription.objects.filter(pk__in=pks).update(last_notified_at=now)


def connect():
    """Connect board listeners. Called from BoardsConfig.ready().

    The dispatch_uid makes the connection idempotent across module reloads,
    preventing duplicate login notifications.
    """
    SIGNAL_ACCOUNT_POST_LOGIN.connect(
        _notify_board_subscriptions,
        dispatch_uid="evennia_boards.notify_board_subscriptions",
    )
