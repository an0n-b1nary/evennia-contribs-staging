# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Signals for evennia_boards.

post_created         — fired by Post.create_post() after a new post is saved.
                       kwargs: post (Post), board (Board)

board_unread_notified — reserved for future notification infrastructure.
                        kwargs: account (AccountDB), board (Board),
                                unread_count (int)
"""

from django.dispatch import Signal

post_created = Signal()
board_unread_notified = Signal()
